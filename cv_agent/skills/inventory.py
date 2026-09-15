"""
cv_agent.skills.inventory — Aggregates one or more SkillSource objects.

The resolver and CLI talk to a SkillInventory, never to a SkillSource
directly, so adding a second source later (repository skills, a remote
catalog, MCP-discovered capabilities — see spec/06-tooling-and-mcp.md, not
built) is a one-line change here, not a resolver rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from cv_agent.skills.models import Skill
from cv_agent.skills.source import SkillSource


@dataclass
class SkillInventory:
    """Discovered-skill catalogue, aggregated from one or more sources."""

    sources: tuple[SkillSource, ...] = field(default_factory=tuple)
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

    def list(self) -> list[Skill]:
        self._ensure_loaded()
        return sorted(self._skills.values(), key=lambda s: s.skill_id)

    def get(self, skill_id: str) -> Optional[Skill]:
        """Return the discovered Skill for skill_id, or None if not found.

        None means exactly that — not "unavailable due to an error" — a
        missing skill is a normal, expected outcome, never fabricated.
        """
        self._ensure_loaded()
        return self._skills.get(skill_id)

    def is_discovered(self, skill_id: str) -> bool:
        return self.get(skill_id) is not None
