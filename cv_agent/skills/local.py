"""
cv_agent.skills.local — Discovery of locally installed skills.

Convention discovered by inspecting this machine's actual Claude Code skill
installation (~/.claude/skills/<skill-id>/SKILL.md, some entries symlinked
from ~/.agents/skills/<skill-id>) rather than assumed: a skill is a directory
containing a SKILL.md file. The directory name is the skill id. SKILL.md may
carry a YAML-style frontmatter block (observed: name, description, owner,
version, ...) but real installed skills were also found with NO frontmatter
at all (plain prose) — the parser below must not crash on either.

This adapter never modifies anything under the scanned roots and never
copies a skill's implementation into this repository — only metadata
(id, name, description, tags, location) is retained.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cv_agent.skills.models import Skill, SkillEvidence

_SKILL_DEFINITION_FILENAME = "SKILL.md"
_ENV_VAR = "CV_AGENT_SKILL_PATHS"


def default_skill_roots() -> tuple[Path, ...]:
    """
    Default locations to scan for installed skills.

    Overridable via the CV_AGENT_SKILL_PATHS environment variable
    (os.pathsep-separated), so this is not a single hard-coded layout — it's
    a default guess, not an assumption baked into the resolver. If the env
    var is set, it *replaces* the defaults rather than extending them, so a
    test fixture can point discovery at an isolated directory.
    """
    override = os.environ.get(_ENV_VAR)
    if override:
        return tuple(Path(p) for p in override.split(os.pathsep) if p)
    home = Path.home()
    return (home / ".claude" / "skills", home / ".agents" / "skills")


def _parse_frontmatter(text: str) -> dict[str, str]:
    """
    Parse a minimal flat `key: value` YAML-style frontmatter block delimited
    by `---` lines at the top of the file. Deliberately not a full YAML
    parser (no new dependency for Step 2) — every real SKILL.md frontmatter
    observed on this machine is flat scalar key/value pairs, not nested
    structures. A file with no frontmatter (or malformed frontmatter) yields
    an empty dict rather than raising; discovery must degrade gracefully,
    not crash on a skill with unusual metadata.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def _load_skill(skill_dir: Path, source_id: str, discovered_at: str) -> Skill | None:
    definition = skill_dir / _SKILL_DEFINITION_FILENAME
    if not definition.is_file():
        return None
    try:
        text = definition.read_text(encoding="utf-8")
    except OSError:
        return None

    meta = _parse_frontmatter(text)
    skill_id = skill_dir.name
    body = text.split("---", 2)[-1] if meta else text
    description = meta.get("description") or _first_meaningful_line(body)
    tags_raw = meta.get("tags", "")
    tags = tuple(t.strip() for t in tags_raw.split(",") if t.strip())

    return Skill(
        skill_id=skill_id,
        name=meta.get("name", skill_id),
        description=description,
        source=source_id,
        location=str(definition.resolve()),
        tags=tags,
        discovered=True,
        executable=False,
        evidence=SkillEvidence(
            source_id=source_id,
            location=str(definition.resolve()),
            discovered_at=discovered_at,
        ),
        raw_metadata=meta,
    )


def _first_meaningful_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:200]
    return ""


@dataclass
class LocalSkillSource:
    """
    Discovers skills installed under one or more local directories.

    Each root is scanned one level deep for `<root>/<skill_id>/SKILL.md`.
    Symlinked skill directories (the real ~/.claude/skills/ convention on
    this machine) are followed. A root that doesn't exist is skipped, not an
    error — "not installed" is a valid, expected outcome.
    """

    roots: tuple[Path, ...] = field(default_factory=default_skill_roots)
    source_id: str = "local"

    def discover(self) -> list[Skill]:
        discovered_at = datetime.now(timezone.utc).isoformat()
        seen: dict[str, Skill] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for entry in sorted(root.iterdir()):
                if not entry.is_dir():
                    continue
                skill = _load_skill(entry, self.source_id, discovered_at)
                if skill is None:
                    continue
                if skill.skill_id in seen:
                    # Duplicate skill_id across roots (e.g. a name reused in
                    # both ~/.claude/skills and ~/.agents/skills): first
                    # discovered wins, later ones are silently superseded —
                    # not an error, but never merged/overwritten silently
                    # into a different skill's data.
                    continue
                seen[skill.skill_id] = skill
        return sorted(seen.values(), key=lambda s: s.skill_id)
