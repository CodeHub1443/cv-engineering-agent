"""
cv_agent.memory.models — Project Understanding revisions and session index
entries.

Kept independent of `cv_agent.graph.state.AgentState` and
`cv_agent.requirements.models.RequirementsAnalysis` the same way ADR-0003
kept orchestration state independent of the reasoning layer's types: this
module only knows plain data, never LangGraph or the requirements analyzer
(ADR-0004 §2/§3). `requirements_analysis` below is a `dict[str, Any]` — the
already-serialized `dataclasses.asdict()` output a caller supplies, not the
`RequirementsAnalysis` dataclass itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProjectUnderstandingRevision:
    """
    One immutable, appended snapshot of the project's understanding.

    Never edited or deleted after creation (ADR-0004 §3) — a correction is a
    new revision with `supersedes` pointing at the one it replaces. The
    *current* understanding is whichever revision was appended most recently
    (`ProjectMemoryStore.get_current_understanding()`), not a separately
    tracked pointer.
    """

    revision_id: str
    """Caller-supplied, unique identifier (e.g. "PU-YYYYMMDD-NN"). This
    module does not generate IDs — that policy belongs to whichever future
    caller wires a store into `CVAgent` (ADR-0004 §9), not to the storage
    boundary itself."""

    created_at: str
    """ISO-8601 timestamp."""

    session_id: str
    """Which session produced this revision. Must be the same identifier
    used as `AgentState.session_id` / the LangGraph thread id for that run
    (ADR-0003) — this module does not enforce that alignment, the caller
    does, by construction (it is the same string, not a separate concept)."""

    requirements_analysis: dict[str, Any]
    """`dataclasses.asdict()` of a `RequirementsAnalysis` (ADR-0008),
    supplied by the caller. Opaque to this module — never parsed or
    validated here, only stored and returned verbatim."""

    supersedes: str | None = None
    """The prior `revision_id` this one replaces, or `None` for the first
    revision ever written. Not validated against existing revisions by the
    store (ADR-0004 keeps this the simplest deterministic policy justified
    by the ADR, not an elaborate change-detection system) — a dangling
    `supersedes` is the caller's mistake to avoid, not this module's to
    police."""

    note: str = ""
    """Why this revision was made, for auditability (ADR-0004 requirement
    3: "preserve enough metadata to make revisions auditable")."""


@dataclass(frozen=True)
class SessionRecord:
    """
    Lightweight index entry for one orchestration session.

    Not a transcript and not a LangGraph checkpoint — those remain
    ADR-0003's concern (`MemorySaver` / a future persistent checkpointer).
    This is metadata only: enough to answer "what sessions exist and what
    did they produce," not "what was said in them."

    Unlike `ProjectUnderstandingRevision`, a `SessionRecord` is upserted by
    `session_id` as a session progresses (e.g. `status`/`ended_at` change
    over its lifecycle) — it is not immutable-append, because a session is
    one ongoing thing being described, not a point-in-time fact being
    recorded (ADR-0004 §5 interface docstring).
    """

    session_id: str
    """Must be the exact same string as `AgentState.session_id` / the
    LangGraph thread id for that run (ADR-0003) — session identity is not
    reinvented here, only indexed."""

    started_at: str
    """ISO-8601 timestamp."""

    ended_at: str | None = None
    """ISO-8601 timestamp, or `None` while the session is still open."""

    status: str = "running"
    """Mirrors `AgentState.status` at the time of the last write for this
    session (e.g. "ready", "paused", "done", "error") — not independently
    defined here."""

    produced_revision_id: str | None = None
    """Set if this session wrote a new `ProjectUnderstandingRevision`,
    linking the two without either owning the other."""
