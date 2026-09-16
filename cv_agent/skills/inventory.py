"""
cv_agent.skills.inventory — Aggregates one or more SkillSource objects.

The resolver and CLI talk to a SkillInventory, never to a SkillSource
directly, so adding a second source later (repository skills, a remote
catalog, MCP-discovered capabilities — see spec/06-tooling-and-mcp.md, not
built) is a one-line change here, not a resolver rewrite.

**Executable-status wiring (ADR-0007 §9, amending §8's revisit trigger,
which fired when ADR-0009's first real ExecutionBinding shipped):**
`SkillInventory` — not `SkillSource`, and not `TaskResolver` directly — is
the one place a discovered `Skill.executable=False` default can be
corrected to the true, live answer. It never imports
`cv_agent.execution` — it only accepts an optional, caller-supplied
`is_executable: Callable[[str], bool]` predicate at construction, exactly
the shape `SkillExecutor.can_execute`/`CVAgent.can_execute` already have.
`cv_agent.skills` stays unaware of `ExecutionBinding`/`ExecutionRegistry`
as concrete types; the application layer (`CVAgent.__init__`) is what
closes the loop by passing `self._executor.can_execute` in. No predicate
supplied (the default) reproduces the exact prior behavior — every skill
reports `executable=False`, unchanged for any caller that constructs a
`SkillInventory` directly (as most existing tests do).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Callable, Optional

from cv_agent.skills.models import Skill
from cv_agent.skills.source import SkillSource


@dataclass
class SkillInventory:
    """Discovered-skill catalogue, aggregated from one or more sources."""

    sources: tuple[SkillSource, ...] = field(default_factory=tuple)
    is_executable: Optional[Callable[[str], bool]] = None
    """Optional predicate: skill_id -> True iff a verified, registered
    execution binding exists for it right now. None (the default) means no
    caller has wired execution-awareness in — every Skill this inventory
    returns keeps its discovery-time `executable=False`. Deliberately a
    plain callback, not a dependency on any concrete execution type, so
    `cv_agent.skills` never imports `cv_agent.execution` (see module
    docstring, ADR-0007 §9)."""
    _skills: dict[str, Skill] = field(default_factory=dict, init=False, repr=False)
    _loaded: bool = field(default=False, init=False, repr=False)

    def discover(self) -> list[Skill]:
        """Run discovery across every source and cache the merged result."""
        merged: dict[str, Skill] = {}
        for source in self.sources:
            for skill in source.discover():
                if skill.skill_id in merged:
                    continue  # first source to find an id wins; see local.py
                merged[skill.skill_id] = skill
        self._skills = merged
        self._loaded = True
        return self.list()

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.discover()

    def _resolve_executable(self, skill: Skill) -> Skill:
        """Apply the `is_executable` predicate, if any, to override a
        skill's discovery-time `executable=False` with the live, true
        answer. A predicate that returns False changes nothing (the field
        is already False); this only ever makes a skill's reported status
        MORE truthful, never fabricates one beyond what the predicate
        itself reports."""
        if self.is_executable is None:
            return skill
        return dataclasses.replace(skill, executable=self.is_executable(skill.skill_id))

    def list(self) -> list[Skill]:
        self._ensure_loaded()
        return [
            self._resolve_executable(s)
            for s in sorted(self._skills.values(), key=lambda s: s.skill_id)
        ]

    def get(self, skill_id: str) -> Optional[Skill]:
        """Return the discovered Skill for skill_id, or None if not found.

        None means exactly that — not "unavailable due to an error" — a
        missing skill is a normal, expected outcome, never fabricated.
        """
        self._ensure_loaded()
        skill = self._skills.get(skill_id)
        return self._resolve_executable(skill) if skill is not None else None

    def is_discovered(self, skill_id: str) -> bool:
        self._ensure_loaded()
        return skill_id in self._skills
