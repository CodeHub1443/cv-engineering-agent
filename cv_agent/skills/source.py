"""
cv_agent.skills.source — SkillSource abstraction.

A SkillSource discovers Skill objects from one place. The resolver and CLI
depend only on this interface, never on a specific source implementation, so
new sources (a repository-local skills/ dir, a remote catalog, an
MCP-discovered capability list) can be added later without touching the
resolver. Step 2 implements exactly one source: LocalSkillSource
(cv_agent.skills.local).
"""

from __future__ import annotations

from typing import Protocol

from cv_agent.skills.models import Skill


class SkillSource(Protocol):
    """A place skills can be discovered from."""

    source_id: str
    """Stable identifier for this source, stored in Skill.source /
    SkillEvidence.source_id so a discovered skill's provenance is traceable."""

    def discover(self) -> list[Skill]:
        """
        Return the skills actually found by this source right now.

        Must not fabricate a skill that isn't really there, and must not
        raise for an empty or missing location — an empty result is a valid,
        honest answer ("nothing installed here").
        """
        ...
