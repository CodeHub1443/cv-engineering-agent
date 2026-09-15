"""
cv_agent.skills.models — Skill domain model.

Deliberately independent from `cv_agent.capabilities.registry.RegistryItem`.
`RegistryItem` describes a *declared* skill/tool/agent/knowledge-source entry
from `spec/capability_registry.json` — a claim about relevance, not about
what's actually installed. `Skill` describes what a `SkillSource` actually
found in the runtime environment. Keeping them separate is the point: a
capability's `relevant_skills` list is DECLARED, a `Skill` returned by
discovery is DISCOVERED, and neither implies EXECUTABLE (see resolver.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillEvidence:
    """Where a discovered Skill actually came from — never fabricated."""

    source_id: str
    """The SkillSource.source_id that produced this evidence."""
    location: str
    """Filesystem path or URI where the skill definition was found."""
    discovered_at: str
    """ISO-8601 timestamp of the discovery run that found it."""


@dataclass(frozen=True)
class Skill:
    """
    A skill actually discovered in the runtime environment.

    Every field here is either read from the skill's own definition file or
    supplied by the SkillSource that found it — nothing is inferred from
    `spec/capability_registry.json`, documentation, or a hard-coded list.
    """

    skill_id: str
    name: str
    description: str
    source: str
    """source_id of the SkillSource that discovered this skill."""
    location: str
    """Filesystem path or URI to the skill's definition."""
    tags: tuple[str, ...] = ()
    supported_capabilities: tuple[str, ...] = ()
    """Capability IDs this skill declares it can satisfy, if it says so in its
    own metadata. Empty unless the skill's own definition states this."""
    compatible_agents: tuple[str, ...] = ()
    discovered: bool = True
    """Always True for a Skill returned by discover() — presence in this
    dataclass already means it was found. See `executable` for the separate,
    stricter question of whether an invocation binding exists."""
    executable: bool = False
    """True only if a verified execution binding exists for this skill. No
    such binding exists anywhere in this codebase yet (Step 2 scope), so this
    is always False today — see docs/state/STATUS.md."""
    evidence: SkillEvidence | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    """Any extra frontmatter fields the source found, preserved as-is."""
