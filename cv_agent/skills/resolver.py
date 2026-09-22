"""
cv_agent.skills.resolver — Deterministic task -> capability -> skill resolution.

No LLM, no semantic embedding, no RAG. Pure keyword/tag overlap scoring
against declared capability metadata (spec/capability_registry.json) and
discovered skill metadata (cv_agent.skills.inventory). This is intentionally
a floor, not a ceiling: TaskResolver is the interface an LLM/semantic
resolver can sit behind later (same input/output shape) without this
deterministic path being removed — it stays as the auditable fallback.

Central invariant, restated at the type level: a CapabilityMatch never
claims `executable` — a capability is a declared relevance relationship,
never a runnable thing. A SkillMatch.executable, since ADR-0007 §9 (amending
§8's fired revisit trigger), reflects whatever `Skill.executable` the
injected `SkillInventory` reports for that skill_id — copied verbatim, never
independently computed here. `TaskResolver` still imports nothing from
`cv_agent.execution` and never will; if the `SkillInventory` it was
constructed with has no execution-awareness wired in (the default), every
match's `executable` stays False, exactly as before this amendment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cv_agent.capabilities.registry import Capability, CapabilityRegistry
from cv_agent.skills.inventory import SkillInventory

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Tokens too common to carry matching signal on their own.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "on", "in", "to", "for", "of", "and", "or", "with",
        "using", "use", "it", "is", "are", "this", "that", "at", "by", "as",
    }
)


def _tokenize(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS}


def _capability_terms(cap: Capability) -> set[str]:
    terms: set[str] = set()
    terms |= _tokenize(cap.id.replace(".", " "))
    terms |= _tokenize(cap.name)
    terms |= _tokenize(cap.description)
    terms |= _tokenize(cap.category)
    for t in cap.applicable_task_types:
        terms |= _tokenize(t.replace("_", " "))
    return terms


def _skill_terms(skill_id: str, name: str, description: str, tags: tuple[str, ...]) -> set[str]:
    terms = _tokenize(skill_id.replace("-", " ")) | _tokenize(name) | _tokenize(description)
    for tag in tags:
        terms |= _tokenize(tag.replace("-", " "))
    return terms


@dataclass(frozen=True)
class CapabilityMatch:
    capability_id: str
    score: float
    matched_terms: tuple[str, ...]
    status: str
    """The capability's declared registry status (e.g. "planned"). Included
    so a resolution result never implies a matched capability is executable
    — see docs/state/STATUS.md and ADR-0001 §8a."""


@dataclass(frozen=True)
class SkillMatch:
    skill_id: str
    score: float
    matched_terms: tuple[str, ...]
    declared: bool
    """True if this skill was matched because a matched capability declares
    it in relevant_skills. False if it was matched purely by keyword overlap
    against discovered skill metadata, independent of any capability
    declaration."""
    discovered: bool
    """Always True for a SkillMatch — only discovered skills are ever
    surfaced as matches. Missing declared skills go to
    ResolutionResult.missing_skills instead, never fabricated as a match."""
    executable: bool
    """Copied from the matched `Skill.executable` (see models.Skill) at
    match time — True only if the `SkillInventory` this resolver was built
    with was given a predicate reporting a verified, registered execution
    binding for this skill_id. False by default, same as `Skill.executable`,
    for any resolver whose inventory has no execution-awareness wired in."""


@dataclass(frozen=True)
class ResolutionResult:
    task: str
    matched_capabilities: tuple[CapabilityMatch, ...]
    matched_skills: tuple[SkillMatch, ...]
    missing_skills: tuple[str, ...]
    """Skill IDs declared relevant by a matched capability but NOT found by
    discovery — DECLARED RELEVANCE without DISCOVERED AVAILABILITY."""
    evidence: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass
class TaskResolver:
    """Deterministic resolver: natural-language task -> capabilities -> skills."""

    capability_registry: CapabilityRegistry
    skill_inventory: SkillInventory
    min_score: float = 1.0
    max_capabilities: int = 5

    def resolve(self, task: str) -> ResolutionResult:
        task_terms = _tokenize(task)
        evidence: list[str] = []
        warnings: list[str] = []

        if not task_terms:
            warnings.append("Task text produced no usable keywords.")
            return ResolutionResult(task, (), (), (), (), tuple(warnings))

        cap_matches = self._match_capabilities(task_terms)
        if not cap_matches:
            warnings.append(
                "No capability matched the task's keywords "
                f"({sorted(task_terms)}); resolution is empty. This does not "
                "mean the task is impossible, only that deterministic "
                "keyword matching found nothing — a future semantic "
                "resolver may do better."
            )
            return ResolutionResult(task, (), (), (), (), tuple(warnings))

        evidence.append(
            f"Matched {len(cap_matches)} capability(ies) in "
            "spec/capability_registry.json by keyword overlap."
        )

        skill_matches, missing = self._match_skills(task_terms, cap_matches)
        if missing:
            warnings.append(
                f"{len(missing)} skill(s) are declared relevant by a matched "
                "capability but were NOT found by skill discovery: "
                f"{sorted(missing)}. Declared relevance is not evidence of "
                "availability."
            )
        if not skill_matches:
            warnings.append(
                "No discovered skill matched this task. All matched "
                "capabilities are relevant-but-unactionable without an "
                "installed, discovered skill."
            )
        else:
            evidence.append(
                f"{len(skill_matches)} discovered skill(s) are relevant to "
                "this task."
            )

        return ResolutionResult(
            task=task,
            matched_capabilities=cap_matches,
            matched_skills=skill_matches,
            missing_skills=tuple(sorted(missing)),
            evidence=tuple(evidence),
            warnings=tuple(warnings),
        )

    def _match_capabilities(self, task_terms: set[str]) -> tuple[CapabilityMatch, ...]:
        scored: list[CapabilityMatch] = []
        for cap in self.capability_registry.list():
            cap_terms = _capability_terms(cap)
            overlap = task_terms & cap_terms
            if not overlap:
                continue
            score = float(len(overlap))
            if score < self.min_score:
                continue
            scored.append(
                CapabilityMatch(
                    capability_id=cap.id,
                    score=score,
                    matched_terms=tuple(sorted(overlap)),
                    status=cap.status,
                )
            )
        scored.sort(key=lambda m: (-m.score, m.capability_id))
        return tuple(scored[: self.max_capabilities])

    def _match_skills(
        self, task_terms: set[str], cap_matches: tuple[CapabilityMatch, ...]
    ) -> tuple[tuple[SkillMatch, ...], set[str]]:
        declared_skill_ids: set[str] = set()
        for cap_match in cap_matches:
            cap = self.capability_registry.describe(cap_match.capability_id)
            declared_skill_ids |= set(cap.relevant_skills)

        discovered = {s.skill_id: s for s in self.skill_inventory.list()}
        matches: dict[str, SkillMatch] = {}
        missing: set[str] = set()

        for skill_id in declared_skill_ids:
            skill = discovered.get(skill_id)
            if skill is None:
                missing.add(skill_id)
                continue
            overlap = task_terms & _skill_terms(
                skill.skill_id, skill.name, skill.description, skill.tags
            )
            matches[skill_id] = SkillMatch(
                skill_id=skill_id,
                score=float(len(overlap)) if overlap else 0.5,
                matched_terms=tuple(sorted(overlap)),
                declared=True,
                discovered=True,
                executable=skill.executable,
            )

        for skill in discovered.values():
            if skill.skill_id in matches:
                continue
            overlap = task_terms & _skill_terms(
                skill.skill_id, skill.name, skill.description, skill.tags
            )
            if not overlap:
                continue
            matches[skill.skill_id] = SkillMatch(
                skill_id=skill.skill_id,
                score=float(len(overlap)),
                matched_terms=tuple(sorted(overlap)),
                declared=False,
                discovered=True,
                executable=skill.executable,
            )

        ranked = sorted(matches.values(), key=lambda m: (-m.score, m.skill_id))
        return tuple(ranked), missing
