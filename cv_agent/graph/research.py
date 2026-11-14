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
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Literal

from cv_agent.knowledge.models import (
    IngestPath,
    ItemId,
    KnowledgeItem,
    Provenance,
    SourceClass,
)
from cv_agent.knowledge.store import KnowledgeStore
from cv_agent.llm.base import LLMProvider, LLMRequest
from cv_agent.llm.errors import LLMCallError
from cv_agent.llm.policy import DataClass, TaskClass
from cv_agent.llm.router import LLMRouter
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


_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+:-]{0,63}")


def _token(value: str, what: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ValueError(
            f"{what} must be a single identifier token (letters, digits, . _ / + : -; no spaces, "
            f"at most 64 characters), got {value!r}: free text is never allowed in a research query."
        )
    return value


def claim_query_from(topic_tags: tuple[str, ...], model_names: tuple[str, ...], metric: str) -> str:
    """Build the claim query only from structured fields (ADR-0020 G7, Q40 default-deny).

    Each field must be a single identifier token; anything resembling free text (a task
    description, a sentence, a newline) raises ``ValueError``. The query is what reaches a
    hosted tier next to fetched public text, so it may name topics, models and a metric, nothing else.
    """
    if not topic_tags:
        raise ValueError("topic_tags must not be empty.")
    tags = ", ".join(_token(t, "topic tag") for t in topic_tags)
    models = ", ".join(_token(m, "model name") for m in model_names)
    subject = f" for {models}" if models else ""
    return f"the {_token(metric, 'metric')} reported{subject} (topics: {tags})"


def _truncate_for_llm(text: str) -> str:
    if len(text) <= MAX_CONTENT_FOR_LLM:
        return text
    return text[:MAX_CONTENT_FOR_LLM] + "\n[content truncated at 8 000 characters]"


# --- Visible text and claim-term window (#145). The fetcher hands over raw HTML; reasoning needs the page
# text around the claim, not the first 8,000 characters of markup. The fetcher's contract is unchanged. ---

LEAD_CHARS = 2_000  # leading clean text kept when the page is windowed
_SEGMENT_CLIP = 600  # longest paragraph or row kept in a window
_HEADING_CLIP = 200
_GAP = "[...]"
_SKIP_TAGS = frozenset({"script", "style", "head", "nav", "aside"})
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BLOCK_TAGS = _HEADINGS | frozenset({
    "p", "div", "li", "ul", "ol", "dl", "dt", "dd", "section", "article", "pre", "blockquote", "br", "hr",
    "table", "caption", "figure", "figcaption", "header", "footer", "main", "details", "summary",
})
_QUERY_FORM = re.compile(r"the (?P<metric>\S+) reported(?: for (?P<models>.+?))? \(topics: .*\)")
_STOPWORDS = frozenset({"the", "for", "and", "with", "from", "that", "this", "extract", "main", "claim",
                        "reported", "topics", "what", "which", "about"})


@dataclass(frozen=True)
class _Seg:
    """One paragraph or table row of visible text. Rows also carry their table, whether they hold a
    header cell, and the index of the nearest heading before the table."""

    text: str
    table: int | None = None
    th: bool = False
    heading: int | None = None


class _VisibleText(HTMLParser):
    """Collects visible text as segments: skips script, style, head, nav and aside; one segment per block
    element; a table row is one segment with its cells joined by `` | ``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.segs: list[_Seg] = []
        self._skip = 0
        self._buf: list[str] = []
        self._tables: list[tuple[int, int | None]] = []  # (table id, heading index when it opened)
        self._n_tables = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._row_th = False
        self._heading: int | None = None
        self._heading_from = 0

    def _flush(self) -> None:
        text = " ".join("".join(self._buf).split())
        self._buf = []
        if text:
            self.segs.append(_Seg(text))

    def _end_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
        self._cell = None

    def _end_row(self) -> None:
        self._end_cell()
        cells, self._row = self._row, None
        if cells and any(cells) and self._tables:
            table, heading = self._tables[-1]
            self.segs.append(_Seg(" | ".join(cells), table, self._row_th, heading))

    def handle_starttag(self, tag: str, attrs: list) -> None:  # noqa: ARG002
        if tag == "body":
            self._skip = 0  # an unclosed <head> ends at <body>
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "table":
            self._flush()
            self._n_tables += 1
            self._tables.append((self._n_tables, self._heading))
        elif tag == "tr" and self._tables:
            if self._row is not None:
                self._end_row()
            self._flush()
            self._row, self._row_th = [], False
        elif tag in ("td", "th") and self._row is not None:
            self._end_cell()
            self._cell = []
            self._row_th = self._row_th or tag == "th"
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")
        elif tag in _BLOCK_TAGS and self._row is None:
            self._flush()
            if tag in _HEADINGS:
                self._heading_from = len(self.segs)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in ("td", "th"):
            self._end_cell()
        elif tag == "tr" and self._row is not None:
            self._end_row()
        elif tag == "table":
            if self._row is not None:
                self._end_row()
            if self._tables:
                self._tables.pop()
        elif tag in _BLOCK_TAGS and self._row is None:
            self._flush()
            if tag in _HEADINGS and len(self.segs) > self._heading_from:
                self._heading = len(self.segs) - 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        elif self._row is None:
            self._buf.append(data)

    def finish(self) -> list[_Seg]:
        self.close()
        if self._row is not None:
            self._end_row()
        self._flush()
        return self.segs


def _html_segments(html: str) -> list[_Seg]:
    parser = _VisibleText()
    parser.feed(html)
    return parser.finish()


def _seg_texts(segs: list[_Seg]) -> list[str]:
    return [s.text for s in segs]


def _is_html(text: str) -> bool:
    head = text[:1000].lstrip().lower()
    return head.startswith("<!doctype html") or "<html" in head or "<body" in head


def _claim_terms(claim_query: str) -> tuple[str, ...]:
    """The metric and model tokens of a ``claim_query_from`` query (topic tags are too generic to window on).

    A query not in that form falls back to its identifier tokens of three or more characters.
    """
    m = _QUERY_FORM.fullmatch(claim_query)
    if m is not None:
        return (m["metric"], *(x for x in (m["models"] or "").split(", ") if x))
    return tuple(t for t in _TOKEN.findall(claim_query) if len(t) >= 3 and t.lower() not in _STOPWORDS)


def _matches(text: str, terms: tuple[str, ...]) -> bool:
    """Whole-token, case-insensitive: ``yolo11n`` does not match ``YOLO11n-seg``."""
    return any(
        re.search(rf"(?<![A-Za-z0-9_-]){re.escape(t)}(?![A-Za-z0-9_-])", text, re.IGNORECASE) for t in terms
    )


def _render(picked: dict[int, str]) -> str:
    out: list[str] = []
    prev: int | None = None
    for i in sorted(picked):
        if prev is not None and i != prev + 1:
            out.append(_GAP)
        out.append(picked[i])
        prev = i
    return "\n".join(out)


def _window(segs: list[_Seg], terms: tuple[str, ...], cap: int) -> str:
    """The clean text if it fits ``cap``; else the leading text plus each segment naming a term, in document
    order, with a matching row's table header row and nearest heading. Never longer than ``cap``; no match
    means the leading clean text."""
    texts = _seg_texts(segs)
    clean = "\n".join(texts)
    if len(clean) <= cap:
        return clean
    hits = [i for i, t in enumerate(texts) if _matches(t, terms)]
    if not hits:
        return clean[:cap]
    header: dict[int, int] = {}
    for i, s in enumerate(segs):
        if s.table is not None and (s.table not in header or (s.th and not segs[header[s.table]].th)):
            header[s.table] = i
    picked: dict[int, str] = {}
    used = 0
    for i, t in enumerate(texts):
        if picked and used + len(t) + 1 > LEAD_CHARS:
            break
        picked[i] = t[:_SEGMENT_CLIP]
        used += len(t) + 1
    for i in hits:
        new = {i: texts[i][:_SEGMENT_CLIP]}
        table, heading = segs[i].table, segs[i].heading
        if table is not None:
            new[header[table]] = texts[header[table]][:_SEGMENT_CLIP]
            if heading is not None:
                new[heading] = texts[heading][:_HEADING_CLIP]
        new = {k: v for k, v in new.items() if k not in picked}
        if not new:
            continue
        candidate = {**picked, **new}
        if len(_render(candidate)) > cap:
            break
        picked = candidate
    return _render(picked)[:cap]


def _prepare_for_llm(content_text: str, claim_query: str) -> str:
    """What the model reads: visible text windowed on the claim terms for HTML; anything else, or any
    failure of the HTML step, is today's ``_truncate_for_llm``. Never raises."""
    if not _is_html(content_text):
        return _truncate_for_llm(content_text)
    try:
        segs = _html_segments(content_text)
        if not segs:
            return _truncate_for_llm(content_text)
        return _window(segs, _claim_terms(claim_query), MAX_CONTENT_FOR_LLM)
    except Exception:  # noqa: BLE001 — the pre-LLM step must not fail the research cycle
        return _truncate_for_llm(content_text)


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
    llm_provider: LLMProvider | None = None,
    router: LLMRouter | None = None,
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

    Give exactly one of ``llm_provider`` (used as is) or ``router`` (the provider is
    ``router.for_task(TaskClass.EXTRACTION)``, resolved only once the fetch has succeeded).
    A ``LLMCallError`` after the send (truncation, refusal, empty or unexpected stop, request
    failure) is a ``failed_extraction``; privacy, budget, credential and store errors propagate.
    """
    if (llm_provider is None) == (router is None):
        raise ValueError("perform_research needs exactly one of llm_provider or router.")

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
    provider = llm_provider if llm_provider is not None else router.for_task(TaskClass.EXTRACTION)  # type: ignore[union-attr]
    try:
        llm_response = provider.complete(
            LLMRequest(
                prompt=_EXTRACTION_PROMPT.format(
                    claim_query=request.claim_query,
                    url=final_url,
                    content_text=_prepare_for_llm(content_text, request.claim_query),
                ),
                system=_EXTRACTION_SYSTEM,
                max_tokens=512,
                data_classes=frozenset({DataClass.PUBLIC_WEB, DataClass.PROJECT_METADATA}),
            )
        )
    except LLMCallError as exc:  # diagnostics only: type, stop reason, call id; never model text
        return ResearchResult(
            status="failed_extraction",
            item_id=str(request.item_id),
            url=final_url,
            error_message=(
                f"LLM call failed after send: {type(exc).__name__} "
                f"(stop_reason={exc.stop_reason!r}, call_id={exc.call_id!r})."
            ),
        )

    extracted = _extract_json(llm_response.content)
    if not isinstance(extracted, dict):  # json.loads may yield a list, number or string (#144)
        extracted = None
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
            # conditions that came from the caller (the fallback above) are not web text: such an item is
            # PROJECT_INPUT, so the hosted payload builder excludes it (ADR-0023 §2.1, §3.4).
            ingest=(
                IngestPath.WEB_FETCH
                if _nonempty_str(extracted.get("conditions")) or request.conditions is None
                else IngestPath.PROJECT_INPUT
            ),
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
