"""
cv_agent.graph.research — Research orchestration.

Bridges ToolExecutor (ADR-0005) and KnowledgeStore (ADR-0006) via an LLM
call (ADR-0002) that extracts a structured claim from raw fetched content.

Responsibility split enforced here, per [P§19] and ADR-0005 §13:
  - ToolExecutor / WebResearchFetchInvoker: acquisition (fetch, no reasoning)
  - LLMProvider: reasoning (claim extraction from raw content)
  - perform_research(): coordinator only — wires the two, never does either

Fail-closed throughout: every non-"stored" ResearchResult means nothing was
written to the KnowledgeStore.  The caller handles the failure.

No network access in this module — only through ToolExecutor.
No cv_agent.execution / cv_agent.skills / cv_agent.tools import except the
executor and models needed to call ToolExecutor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from cv_agent.knowledge.models import (
    ItemId,
    KnowledgeItem,
    Provenance,
    SourceClass,
)
from cv_agent.knowledge.store import KnowledgeStore
from cv_agent.llm.base import LLMProvider, LLMRequest
from cv_agent.tools.executor import ToolExecutor
from cv_agent.tools.models import ToolId, ToolRequest

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

ResearchStatus = Literal[
    "stored",             # KnowledgeItem written to KnowledgeStore
    "failed_fetch",       # ToolExecutor returned non-ok (failed/not_executable/rejected)
    "failed_extraction",  # LLM response not parseable or returned no usable claim
    "failed_provenance",  # Provenance/KnowledgeItem construction failed (mandatory field absent/invalid)
    "failed_store",       # KnowledgeStore.put() raised an exception
]

_TOOL_ID = ToolId("web-research-fetch")

# Maximum characters of fetched content sent to the LLM — bounded to keep
# prompt size predictable and avoid provider token-limit errors.
MAX_CONTENT_FOR_LLM = 8_000


@dataclass(frozen=True)
class ResearchRequest:
    """
    Inputs to perform_research(). The caller supplies everything that cannot
    be derived from the fetched content: URL, source classification, topic
    tags, staleness horizon, and the specific claim to look for.

    The LLM will attempt to extract `claim`, `conditions`, `author_or_org`,
    and `date_published` from the fetched HTML.  `author_or_org` and
    `date_published` may be provided as caller-supplied fallbacks — if the
    LLM extracts neither and no fallback is given, provenance construction
    fails closed.
    """

    url: str
    """The URL to fetch — passed verbatim to web-research-fetch."""

    item_id: ItemId
    """Caller-assigned unique identifier for the resulting KnowledgeItem."""

    source_class: SourceClass
    """Assigned by the caller, who knows the source type — never inferred by
    this module or the invoker (ADR-0005 §13 / docs/RESEARCH_POLICY.md §3)."""

    topic_tags: tuple[str, ...]
    """Deterministic retrieval keys for the resulting KnowledgeItem (ADR-0006)."""

    staleness_horizon_days: int
    """Freshness horizon in days — caller-supplied per docs/RESEARCH_POLICY.md
    §6.  Only qualitative buckets are given there, not exact numbers; the caller
    makes the judgment call."""

    claim_query: str
    """What specific claim to extract, e.g. "extract the main inference-speed
    benchmark for person detection."  Included in the LLM extraction prompt."""

    author_or_org: str | None = None
    """Fallback author/organization if the LLM cannot extract one from the
    content.  If both the LLM extraction and this fallback are None,
    provenance construction fails closed."""

    date_published: str | None = None
    """Fallback publication date (ISO 8601 YYYY-MM-DD) if the LLM cannot
    extract one.  If both the LLM extraction and this fallback are None,
    provenance construction fails closed."""

    conditions: str | None = None
    """Fallback conditions string.  When the LLM also extracts conditions from
    the content, the LLM value is preferred (it actually reads the page)."""

    context_hint: str | None = None
    """Optional caller annotation forwarded to the ToolInvoker — for the
    calling layer's logging only, never sent in the HTTP request
    (ADR-0005 §13)."""


@dataclass(frozen=True)
class ResearchResult:
    """
    Output of perform_research().

    status == "stored" means exactly one KnowledgeItem was written to the
    KnowledgeStore and knowledge_item carries it.  Any other status is
    fail-closed — nothing was written.
    """

    status: ResearchStatus
    item_id: str
    url: str
    knowledge_item: KnowledgeItem | None = None
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers — claim extraction from raw LLM response
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM = (
    "You are a structured evidence extractor for a computer vision engineering "
    "knowledge base.  You read fetched web-page content and return ONLY a JSON "
    "object with the requested fields.  Never add prose outside the JSON.  "
    "Return null for any field that is not present in the content — never fabricate."
)

_EXTRACTION_PROMPT = """\
Extract structured evidence from the following web page.

Claim to look for: {claim_query}

Return ONLY a JSON object with exactly these four keys — use null (not an empty
string) for any field you cannot find in the content:

{{
  "claim":         "<the specific claim about: {claim_query}>",
  "conditions":    "<hardware / dataset / settings the claim assumes, or null>",
  "author_or_org": "<author name or publishing organisation, or null>",
  "date_published":"<publication date as YYYY-MM-DD, or null>"
}}

Source URL: {url}
---
{content_text}
---"""


def _truncate_for_llm(text: str) -> str:
    if len(text) <= MAX_CONTENT_FOR_LLM:
        return text
    return text[:MAX_CONTENT_FOR_LLM] + "\n[content truncated at 8 000 characters]"


def _extract_json(text: str) -> dict | None:
    """
    Best-effort JSON extraction from an LLM response.

    Tries the full string first, then the substring between the first ``{``
    and last ``}`` (handles markdown code-block wrappers).  Returns ``None``
    if both attempts fail — the caller treats this as ``"failed_extraction"``.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _date_accessed_from_timestamp(ts: str) -> str:
    """
    Convert ToolOutcome's ``date_accessed`` (ISO 8601 UTC with time:
    ``YYYY-MM-DDTHH:MM:SSZ``) to the ``YYYY-MM-DD`` form Provenance
    expects.  Falls back to today's UTC date if the value is malformed.
    """
    if len(ts) >= 10 and ts[4:5] == "-" and ts[7:8] == "-":
        return ts[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _nonempty_str(value: object) -> str | None:
    """Return the string if non-blank, else None."""
    return value if isinstance(value, str) and value.strip() else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def perform_research(
    request: ResearchRequest,
    *,
    tool_executor: ToolExecutor,
    llm_provider: LLMProvider,
    knowledge_store: KnowledgeStore,
) -> ResearchResult:
    """
    One research cycle: fetch a URL → LLM-extract a claim → store as a
    provenanced KnowledgeItem.

    Boundaries upheld:
    - Never calls the ToolInvoker directly — always through ToolExecutor.
    - Never makes network calls — acquisition is ToolExecutor's responsibility.
    - LLM is used only for claim/provenance extraction (reasoning), never for
      deciding *whether* to research or *which* URL to fetch.
    - KnowledgeStore receives only fully-validated KnowledgeItems.

    Fail-closed: any non-"stored" result means nothing was written.
    """

    # 1. Acquire raw content via ToolExecutor — never bypass the boundary
    inputs: dict = {"url": request.url}
    if request.context_hint is not None:
        inputs["context_hint"] = request.context_hint

    tool_result = tool_executor.invoke(_TOOL_ID, ToolRequest(inputs=inputs))

    if not tool_result.ok:
        return ResearchResult(
            status="failed_fetch",
            item_id=str(request.item_id),
            url=request.url,
            error_message=(
                f"ToolExecutor returned status={tool_result.status!r}: "
                + (tool_result.error.message if tool_result.error else "no detail")
            ),
        )

    output = tool_result.output or {}
    final_url: str = output.get("url") or request.url
    content_text: str = output.get("content_text") or ""
    date_accessed: str = _date_accessed_from_timestamp(output.get("date_accessed") or "")

    # 2. LLM reasoning — extract structured evidence from raw content
    llm_response = llm_provider.complete(
        LLMRequest(
            prompt=_EXTRACTION_PROMPT.format(
                claim_query=request.claim_query,
                url=final_url,
                content_text=_truncate_for_llm(content_text),
            ),
            system=_EXTRACTION_SYSTEM,
            max_tokens=512,
            temperature=0.0,
        )
    )

    extracted = _extract_json(llm_response.content)
    if extracted is None:
        return ResearchResult(
            status="failed_extraction",
            item_id=str(request.item_id),
            url=final_url,
            error_message=(
                "LLM response could not be parsed as a JSON object: "
                + repr(llm_response.content[:200])
            ),
        )

    # Validate the extracted claim — this is the one field with no fallback
    claim = _nonempty_str(extracted.get("claim"))
    if claim is None:
        return ResearchResult(
            status="failed_extraction",
            item_id=str(request.item_id),
            url=final_url,
            error_message=(
                "LLM extraction returned no usable claim "
                f"(got {extracted.get('claim')!r})."
            ),
        )

    # Optional fields: prefer LLM extraction, then fall back to caller-supplied
    conditions: str | None = _nonempty_str(extracted.get("conditions")) or request.conditions
    author_or_org: str | None = _nonempty_str(extracted.get("author_or_org")) or request.author_or_org
    date_published: str | None = _nonempty_str(extracted.get("date_published")) or request.date_published

    # 3. Provenance — fail closed when mandatory fields are absent
    if not author_or_org:
        return ResearchResult(
            status="failed_provenance",
            item_id=str(request.item_id),
            url=final_url,
            error_message=(
                "Mandatory provenance field author_or_org is missing: "
                "LLM extraction returned null and no fallback was provided."
            ),
        )
    if not date_published:
        return ResearchResult(
            status="failed_provenance",
            item_id=str(request.item_id),
            url=final_url,
            error_message=(
                "Mandatory provenance field date_published is missing: "
                "LLM extraction returned null and no fallback was provided."
            ),
        )

    try:
        provenance = Provenance(
            url=final_url,
            source_class=request.source_class,
            date_published=date_published,
            date_accessed=date_accessed,
            author_or_org=author_or_org,
        )
    except ValueError as exc:
        return ResearchResult(
            status="failed_provenance",
            item_id=str(request.item_id),
            url=final_url,
            error_message=f"Provenance construction failed: {exc}",
        )

    try:
        item = KnowledgeItem(
            item_id=request.item_id,
            claim=claim,
            conditions=conditions,
            provenance=provenance,
            topic_tags=request.topic_tags,
            staleness_horizon_days=request.staleness_horizon_days,
        )
    except ValueError as exc:
        return ResearchResult(
            status="failed_provenance",
            item_id=str(request.item_id),
            url=final_url,
            error_message=f"KnowledgeItem construction failed: {exc}",
        )

    # 4. Store — any exception is a store failure
    try:
        knowledge_store.put(item)
    except Exception as exc:  # noqa: BLE001
        return ResearchResult(
            status="failed_store",
            item_id=str(request.item_id),
            url=final_url,
            error_message=f"KnowledgeStore.put() raised: {exc}",
        )

    return ResearchResult(
        status="stored",
        item_id=str(request.item_id),
        url=final_url,
        knowledge_item=item,
    )
