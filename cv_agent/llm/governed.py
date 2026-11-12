"""
cv_agent.llm.governed — GovernedProvider (ADR-0020 §3 items 5-6, slices G2 and G3).

Responsibility: wrap one adapter so that every call is privacy-checked, length-capped, budgeted,
timed and logged exactly once, failing closed when the books cannot be written. Tier lookup,
routing and config parsing live in ``router`` and ``config.settings`` (G5): ``LLMRouter`` builds
one of these per hosted route and never builds one for the mock provider.

``complete()`` runs, in order:
0. privacy (G4): if ``hosted``, every declared data class (empty means ``{PROJECT_DATA}``) must be
   in ``allowed_hosted`` else ``LLMDataClassNotAllowedError``. This runs before everything else:
   no reservation, no budget row, no adapter call. A refusal is NOT written to ``llm_calls``,
   deliberately: no call was sent, and the log records calls (ADR-0020 §3 item 6);
1. input cap: ``len(system or "") + len(prompt) <= max_input_chars`` else ``LLMInputTooLargeError``;
2. output cap: ``request.max_tokens`` (``None`` means the tier's ``tier_max_tokens``; with no tier
   value it is required) must satisfy ``1 <= max_tokens <= min(tier, max_output_tokens)`` (thinking
   included) else ``LLMConfigError``; an explicit value above the tier is refused, never clamped.
   The adapter always receives the resolved integer;
3. reserve the worst case against the day's USD ceiling and call limit (``LLMCallStore.reserve``:
   ``LLMBudgetExceededError``, ``LLMCallLimitError`` or ``LLMClockSkewError``, no network);
4. the adapter call;
5. settle: the reservation becomes the actual cost and one call row is written.
Nothing in 0-3 touches the network, and none of their messages carries prompt text.

Settling rules:
- success: actual cost from usage (output price on ``completion_tokens``, which already
  contains thinking; cache creation and cache read tokens at the FULL input rate, because the
  cache multipliers are unverified and overcounting is the safe direction). If the actual cost
  is above the reservation it is recorded anyway and a warning is logged (a revisit trigger).
  A response with no usage at all keeps the reservation;
- an ``LLMCallError`` (the request was sent): the full reservation stays counted (whether
  failed calls are billed is unverified; safe direction), one row is written with the error's
  stop reason (or ``error:<ClassName>``), usage and request ID, then the SAME error is
  re-raised with ``call_id`` and ``tier`` filled in;
- ``LLMConfigError`` / ``LLMCredentialError`` from the adapter are raised before a request leaves
  the process: the reservation is released and no row is written;
- any other exception leaves the reservation counted (it may have been sent).
If the books cannot be written after the adapter ran, ``LLMStoreError`` is raised and the
answer is not returned; while handling an adapter error it is raised from that error.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from cv_agent.config.settings import LLMBudgetConfig
from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.catalog import Catalog, ModelFacts, load_catalog, price_for
from cv_agent.llm.clock import Clock, SystemClock, parse_utc_offset
from cv_agent.llm.errors import (
    LLMCallError,
    LLMConfigError,
    LLMCredentialError,
    LLMDataClassNotAllowedError,
    LLMInputTooLargeError,
    LLMStoreError,
)
from cv_agent.llm.policy import DEFAULT_HOSTED_ALLOWED, UNDECLARED_DATA_CLASSES, DataClass
from cv_agent.llm.sqlite_store import CallRecord, LLMCallStore

_log = logging.getLogger(__name__)

FRAMING_RESERVE_TOKENS = 512
CLOCK_SKEW_TOLERANCE_S = 300.0


def day_key_for(ts_utc: datetime, utc_offset: str) -> str:
    """The budget day of ``ts_utc``: its calendar date at a fixed UTC offset, e.g. ``2026-11-12+06:00``."""
    if ts_utc.tzinfo is None:
        raise ValueError("ts_utc must be timezone-aware")
    return f"{ts_utc.astimezone(parse_utc_offset(utc_offset)).date().isoformat()}{utc_offset}"


def resets_at_utc_for(ts_utc: datetime, utc_offset: str) -> str:
    """When the day of ``ts_utc`` ends (the next local midnight), as an ISO UTC timestamp."""
    local = ts_utc.astimezone(parse_utc_offset(utc_offset))
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return midnight.astimezone(timezone.utc).isoformat()


def worst_case_usd(
    facts: ModelFacts,
    *,
    system: Optional[str],
    prompt: str,
    max_tokens: int,
    framing_reserve_tokens: int = FRAMING_RESERVE_TOKENS,
) -> float:
    """Upper bound on one call: ``(utf8 bytes of system + prompt + reserve) x input price +
    max_tokens x output price``, with prices from the step the worst-case input falls into.

    Bytes bound tokens from above (a token is at least one byte), so this never underestimates
    the input; ``max_tokens`` includes thinking, so it covers the output.
    """
    input_tokens = len((system or "").encode("utf-8")) + len(prompt.encode("utf-8")) + framing_reserve_tokens
    step = price_for(facts, input_tokens)
    return (input_tokens * step.input_usd_per_mtok + max_tokens * step.output_usd_per_mtok) / 1_000_000


def actual_cost_usd(facts: ModelFacts, usage: dict[str, int]) -> float:
    """Cost of a finished call from its usage. Cache tokens count at the full input rate; thinking
    is inside ``completion_tokens`` and is not added again."""
    input_tokens = (
        usage.get("prompt_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
    )
    step = price_for(facts, input_tokens)
    return (input_tokens * step.input_usd_per_mtok + usage.get("completion_tokens", 0) * step.output_usd_per_mtok) / (
        1_000_000
    )


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
    """An ``LLMProvider`` that caps, budgets and logs every call of the wrapped adapter.

    ``hosted`` says whether the adapter sends data off this machine; it is required, so no caller
    can forget the privacy question. When hosted, only ``allowed_hosted`` classes may be carried
    (default: public web and project metadata; the owner widens it by a PR with a D-entry).
    ``task_class`` and ``tier`` are the strings the router passes (the ``TaskClass`` value and the
    tier name). ``thinking`` and ``effort`` are the tier's settings, recorded as given.
    The adapter's model must be in the catalog (its prices price the call), else
    ``LLMConfigError`` at construction.
    """

    def __init__(
        self,
        *,
        hosted: bool,
        task_class: str,
        tier: str,
        adapter: LLMProvider,
        store: LLMCallStore,
        store_text: bool = False,
        clock: Optional[Clock] = None,
        thinking: Optional[str] = None,
        effort: Optional[str] = None,
        budget: Optional[LLMBudgetConfig] = None,
        catalog: Optional[Catalog] = None,
        allowed_hosted: frozenset[DataClass] = DEFAULT_HOSTED_ALLOWED,
        tier_max_tokens: Optional[int] = None,
    ) -> None:
        self._tier_max_tokens = tier_max_tokens
        self._hosted = hosted
        self._allowed_hosted = allowed_hosted
        self._task_class = task_class
        self._tier = tier
        self._adapter = adapter
        self._store = store
        self._store_text = store_text
        self._clock: Clock = clock or SystemClock()
        self._thinking = thinking
        self._effort = effort
        self._budget = budget or LLMBudgetConfig()
        self._facts = (catalog or load_catalog()).facts_for(adapter.model_name)

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
        self._check_privacy(request)
        max_tokens = self._check_caps(request)
        if request.max_tokens != max_tokens:
            request = dataclasses.replace(request, max_tokens=max_tokens)  # the tier default, now explicit
        call_id = uuid.uuid4().hex
        now = self._clock.now_utc()
        offset = self._budget.day_boundary_utc_offset
        reservation = self._store.reserve(
            call_id=call_id,
            now_utc=now,
            day_key=day_key_for(now, offset),
            worst_usd=worst_case_usd(
                self._facts, system=request.system, prompt=request.prompt, max_tokens=max_tokens
            ),
            ceiling_usd=self._budget.daily_usd_ceiling,
            call_limit=self._budget.daily_call_limit,
            skew_tolerance_s=CLOCK_SKEW_TOLERANCE_S,
            prices_as_of=self._facts.prices_as_of,
            resets_at_utc=resets_at_utc_for(now, offset),
        )
        ts_utc = now.isoformat()
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
                self._store.settle(reservation, record, None)  # the full reservation stays counted
            except LLMStoreError as store_exc:
                raise store_exc from exc
            raise
        except (LLMConfigError, LLMCredentialError):
            self._store.release(reservation)  # refused before a request left the process
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
        actual = self._actual(response.usage, reservation.reserved_usd, call_id)
        self._store.settle(reservation, record, actual)  # LLMStoreError propagates: no unlogged answer
        return dataclasses.replace(response, call_id=call_id)

    def _check_privacy(self, request: LLMRequest) -> None:
        if not self._hosted:
            return
        declared = request.data_classes or UNDECLARED_DATA_CLASSES
        blocked = declared - self._allowed_hosted
        if blocked:
            raise LLMDataClassNotAllowedError(self._task_class, self._tier, frozenset(blocked))

    def _check_caps(self, request: LLMRequest) -> int:
        chars = len(request.system or "") + len(request.prompt)
        if chars > self._budget.max_input_chars:
            raise LLMInputTooLargeError(chars=chars, limit=self._budget.max_input_chars)
        limit = self._budget.max_output_tokens
        if self._tier_max_tokens is not None:
            limit = min(limit, self._tier_max_tokens)
        wanted = request.max_tokens if request.max_tokens is not None else self._tier_max_tokens
        if wanted is None:
            raise LLMConfigError("max_tokens is required: the request gave none and this provider has no tier value.")
        if not 1 <= wanted <= limit:
            raise LLMConfigError(f"max_tokens {wanted} is outside 1..{limit} (thinking included).")
        return wanted

    def _actual(self, usage: dict[str, int], reserved_usd: float, call_id: str) -> Optional[float]:
        if "prompt_tokens" not in usage and "completion_tokens" not in usage:
            return None  # no usage reported: keep the reservation rather than count zero
        actual = actual_cost_usd(self._facts, usage)
        if actual > reserved_usd:
            _log.warning(
                "LLM cost overshoot: call_id=%s model=%s reserved=$%.6f actual=$%.6f "
                "(the bytes-based estimate was too low; revisit ADR-0020)",
                call_id,
                self._adapter.model_name,
                reserved_usd,
                actual,
            )
        return actual

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
