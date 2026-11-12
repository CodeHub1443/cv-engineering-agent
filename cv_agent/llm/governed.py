"""
cv_agent.llm.governed — GovernedProvider skeleton (ADR-0020 §3 item 5, slice G2).

Responsibility: wrap one adapter so that every call is timed and logged exactly once, and
fail closed when the log cannot be written. Not here yet: privacy and input caps (G4),
budget and reservation (G3), tier lookup (G5). It is not wired into ``CVAgent`` or any call
site, and it is never built for the mock provider.

What is logged:
- success: one row with the response's usage, stop reason and request ID;
- an ``LLMCallError`` from the adapter (the request was sent): one row with the error's
  stop reason (or ``error:<ClassName>``), usage and request ID, then the SAME error is
  re-raised with ``call_id`` and ``tier`` filled in;
- any other adapter exception (``LLMConfigError``, ``LLMCredentialError``, ...) is raised
  before a request leaves the process, so it is not a call and writes no row.
If the log write fails after the adapter ran, ``LLMStoreError`` is raised and the answer is
not returned. If it fails while logging an adapter error, ``LLMStoreError`` is raised from
that error (the unlogged call is the graver fault).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid
from typing import Optional

from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.clock import Clock, SystemClock
from cv_agent.llm.errors import LLMCallError, LLMStoreError
from cv_agent.llm.sqlite_store import CallRecord, LLMCallStore


def prompt_payload(system: Optional[str], prompt: str) -> str:
    """The exact text that ``prompt_sha256`` covers.

    Canonical JSON of ``{"system": <str or null>, "prompt": <str>}``: keys sorted, separators
    ``,`` and ``:`` with no spaces, ``ensure_ascii=True`` (so the payload is pure ASCII and
    its UTF-8 bytes are unambiguous). JSON quoting keeps ``("ab", "c")`` and ``("a", "bc")``
    apart, and ``None`` apart from ``""``.
    """
    return json.dumps(
        {"system": system, "prompt": prompt}, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def prompt_digest(system: Optional[str], prompt: str) -> str:
    """``prompt_sha256``: hex SHA-256 of the UTF-8 bytes of :func:`prompt_payload`."""
    return hashlib.sha256(prompt_payload(system, prompt).encode("utf-8")).hexdigest()


def response_digest(content: str) -> str:
    """``response_sha256``: hex SHA-256 of the UTF-8 bytes of the returned text."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class GovernedProvider(LLMProvider):
    """An ``LLMProvider`` that logs every call of the wrapped adapter (see module docstring).

    ``task_class`` and ``tier`` are plain strings until G5 types them. ``thinking`` and
    ``effort`` are the tier's settings, recorded as given (G5 supplies them from the catalog).
    """

    def __init__(
        self,
        *,
        task_class: str,
        tier: str,
        adapter: LLMProvider,
        store: LLMCallStore,
        store_text: bool = False,
        clock: Optional[Clock] = None,
        thinking: Optional[str] = None,
        effort: Optional[str] = None,
    ) -> None:
        self._task_class = task_class
        self._tier = tier
        self._adapter = adapter
        self._store = store
        self._store_text = store_text
        self._clock: Clock = clock or SystemClock()
        self._thinking = thinking
        self._effort = effort

    @property
    def provider_name(self) -> str:
        return self._adapter.provider_name

    @property
    def model_name(self) -> str:
        return self._adapter.model_name

    @property
    def adapter_version(self) -> Optional[str]:
        return self._adapter.adapter_version

    @property
    def sdk_version(self) -> Optional[str]:
        return self._adapter.sdk_version

    @property
    def task_class(self) -> str:
        return self._task_class

    @property
    def tier_name(self) -> str:
        return self._tier

    def complete(self, request: LLMRequest) -> LLMResponse:
        call_id = uuid.uuid4().hex
        ts_utc = self._clock.now_utc().isoformat()
        started = self._clock.monotonic()
        try:
            response = self._adapter.complete(request)
        except LLMCallError as exc:
            latency_ms = self._latency_ms(started)
            exc.call_id = call_id
            exc.tier = self._tier
            record = self._record(
                request,
                call_id=call_id,
                ts_utc=ts_utc,
                latency_ms=latency_ms,
                usage=exc.usage,
                stop_reason=exc.stop_reason or f"error:{type(exc).__name__}",
                request_id=exc.request_id,
                content=None,
            )
            try:
                self._store.append(record)
            except LLMStoreError as store_exc:
                raise store_exc from exc
            raise
        latency_ms = self._latency_ms(started)
        record = self._record(
            request,
            call_id=call_id,
            ts_utc=ts_utc,
            latency_ms=latency_ms,
            usage=response.usage,
            stop_reason=response.stop_reason or "unknown",
            request_id=response.request_id,
            content=response.content,
        )
        self._store.append(record)  # LLMStoreError propagates: no unlogged answer is returned
        return dataclasses.replace(response, call_id=call_id)

    def _latency_ms(self, started: float) -> int:
        return round((self._clock.monotonic() - started) * 1000)

    def _record(
        self,
        request: LLMRequest,
        *,
        call_id: str,
        ts_utc: str,
        latency_ms: int,
        usage: dict[str, int],
        stop_reason: str,
        request_id: Optional[str],
        content: Optional[str],
    ) -> CallRecord:
        return CallRecord(
            call_id=call_id,
            ts_utc=ts_utc,
            task_class=self._task_class,
            tier=self._tier,
            provider=self._adapter.provider_name,
            model=self._adapter.model_name,
            adapter_version=self._adapter.adapter_version,
            sdk_version=self._adapter.sdk_version,
            local_model_digest=self._adapter.local_model_digest,
            local_quantization=self._adapter.local_quantization,
            max_tokens=request.max_tokens,
            thinking=self._thinking,
            effort=self._effort,
            prompt_sha256=prompt_digest(request.system, request.prompt),
            response_sha256=None if content is None else response_digest(content),
            request_id=request_id,
            input_tokens=usage.get("prompt_tokens", 0),
            cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            thinking_tokens=usage.get("thinking_tokens", 0),
            stop_reason=stop_reason,
            latency_ms=latency_ms,
            prompt_text=prompt_payload(request.system, request.prompt) if self._store_text else None,
            response_text=content if self._store_text else None,
        )
