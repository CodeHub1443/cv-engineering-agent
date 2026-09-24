"""
cv_agent.datasets.leakage — deterministic split-leakage checks (docs/DATA.md).

Responsibility: given recorded splits, per-item attributes and a declared split
policy, decide whether the split may be accepted. Five checks, one per row of
docs/DATA.md's leakage table: temporal, camera, subject, annotation_round,
near_duplicate. Pure functions over their arguments: no I/O, no clock, no
randomness, no image access; a report depends only on the *set* of inputs, never
on their order.

Fail-closed: a check that cannot be verified (a needed attribute is missing, two
hash widths cannot be compared) produces a finding and a "failed" status — never
a silent pass. A check that does not apply under the declared policy is reported
as "not_applicable", visibly, so the recorded report shows what was and was not
checked.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from cv_agent.datasets.models import (
    AnnotationRound,
    DatasetItem,
    DatasetSplit,
    SplitPolicy,
    require_timestamp,
)

LeakageCheckName = Literal[
    "temporal", "camera", "subject", "annotation_round", "near_duplicate"
]
CheckStatus = Literal["passed", "failed", "not_applicable"]

CHECK_ORDER: tuple[LeakageCheckName, ...] = (
    "temporal",
    "camera",
    "subject",
    "annotation_round",
    "near_duplicate",
)


@dataclass(frozen=True)
class LeakageFinding:
    """One reason a check failed. `code` is a stable machine-readable identifier."""

    check: LeakageCheckName
    code: str
    detail: str
    item_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckResult:
    check: LeakageCheckName
    status: CheckStatus
    findings: tuple[LeakageFinding, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class LeakageReport:
    """Every check's outcome, in CHECK_ORDER. This is what a manifest records."""

    results: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        return all(r.status != "failed" for r in self.results)

    @property
    def findings(self) -> tuple[LeakageFinding, ...]:
        return tuple(f for r in self.results for f in r.findings)

    def result(self, check: str) -> CheckResult:
        for r in self.results:
            if r.check == check:
                return r
        raise KeyError(check)


class LeakageError(ValueError):
    """A split failed a leakage check; `report` carries every finding."""

    def __init__(self, report: LeakageReport) -> None:
        self.report = report
        summary = "; ".join(f"{f.check}/{f.code}: {f.detail}" for f in report.findings)
        super().__init__(f"split rejected by leakage check: {summary}")


def _sorted(findings: Iterable[LeakageFinding]) -> tuple[LeakageFinding, ...]:
    return tuple(sorted(findings, key=lambda f: (f.code, f.item_ids, f.detail)))


def _result(
    check: LeakageCheckName, findings: Iterable[LeakageFinding], note: str = ""
) -> CheckResult:
    ordered = _sorted(findings)
    return CheckResult(check, "failed" if ordered else "passed", ordered, note)


def _not_applicable(check: LeakageCheckName, note: str) -> CheckResult:
    return CheckResult(check, "not_applicable", (), note)


def _straddles(
    groups: dict[str, list[DatasetItem]], split_of: dict[str, str]
) -> list[tuple[str, list[DatasetItem], list[str]]]:
    """Group keys whose items sit in more than one split."""
    result: list[tuple[str, list[DatasetItem], list[str]]] = []
    for key in sorted(groups):
        members = groups[key]
        splits = sorted({split_of[m.item_id] for m in members})
        if len(splits) > 1:
            result.append((key, members, splits))
    return result


def _ids(items: Iterable[DatasetItem]) -> tuple[str, ...]:
    return tuple(sorted(i.item_id for i in items))


def _check_temporal(
    items: Sequence[DatasetItem],
    splits: Sequence[DatasetSplit],
    policy: SplitPolicy,
    split_of: dict[str, str],
) -> CheckResult:
    findings: list[LeakageFinding] = []

    by_segment: dict[str, list[DatasetItem]] = defaultdict(list)
    for it in items:
        by_segment[it.segment_id].append(it)
    for segment, members, names in _straddles(by_segment, split_of):
        findings.append(
            LeakageFinding(
                "temporal",
                "segment_straddles_splits",
                f"video segment {segment!r} appears in splits {names}",
                _ids(members),
            )
        )

    if policy.time_order is None:
        return _result("temporal", findings, "no time order declared; segment rule only")

    known = {s.name for s in splits}
    for name in policy.time_order:
        if name not in known:
            raise ValueError(f"time_order names unknown split {name!r}")

    ordered_items = [it for it in items if split_of[it.item_id] in policy.time_order]
    missing = [it for it in ordered_items if it.timestamp is None]
    if missing:
        findings.append(
            LeakageFinding(
                "temporal",
                "missing_timestamp",
                "time order is declared but some items have no timestamp",
                _ids(missing),
            )
        )
        return _result("temporal", findings)

    stamps: dict[str, datetime] = {
        it.item_id: require_timestamp(it.timestamp, "DatasetItem.timestamp")
        for it in ordered_items
    }
    if len({s.tzinfo is None for s in stamps.values()}) > 1:
        findings.append(
            LeakageFinding(
                "temporal",
                "mixed_timezone_awareness",
                "timestamps mix timezone-aware and naive values; order is not comparable",
                _ids(ordered_items),
            )
        )
        return _result("temporal", findings)

    per_split: dict[str, list[DatasetItem]] = defaultdict(list)
    for it in ordered_items:
        per_split[split_of[it.item_id]].append(it)

    order = policy.time_order
    for i, earlier in enumerate(order):
        for later in order[i + 1 :]:
            if not per_split[earlier] or not per_split[later]:
                continue
            latest = max(per_split[earlier], key=lambda x: (stamps[x.item_id], x.item_id))
            earliest = min(per_split[later], key=lambda x: (stamps[x.item_id], x.item_id))
            if stamps[latest.item_id] >= stamps[earliest.item_id]:
                findings.append(
                    LeakageFinding(
                        "temporal",
                        "time_order_violation",
                        f"split {earlier!r} must end before split {later!r} starts, but "
                        f"{latest.item_id!r} ({latest.timestamp}) is not earlier than "
                        f"{earliest.item_id!r} ({earliest.timestamp})",
                        tuple(sorted((latest.item_id, earliest.item_id))),
                    )
                )
    return _result("temporal", findings)


def _check_camera(
    items: Sequence[DatasetItem], policy: SplitPolicy, split_of: dict[str, str]
) -> CheckResult:
    if policy.camera_goal == "same_cameras":
        return _not_applicable("camera", "goal is same_cameras; cameras may span splits")
    by_camera: dict[str, list[DatasetItem]] = defaultdict(list)
    for it in items:
        by_camera[it.camera_id].append(it)
    return _result(
        "camera",
        (
            LeakageFinding(
                "camera",
                "camera_straddles_splits",
                f"camera {camera!r} appears in splits {names} but the goal is "
                "generalization to new cameras",
                _ids(members),
            )
            for camera, members, names in _straddles(by_camera, split_of)
        ),
    )


def _check_subject(
    items: Sequence[DatasetItem], policy: SplitPolicy, split_of: dict[str, str]
) -> CheckResult:
    if not policy.subject_isolation:
        return _not_applicable("subject", "subject isolation not required by the split policy")
    findings: list[LeakageFinding] = []
    unknown = [it for it in items if it.subject_ids is None]
    if unknown:
        findings.append(
            LeakageFinding(
                "subject",
                "missing_subject_ids",
                "subject isolation is required but some items do not declare subject_ids",
                _ids(unknown),
            )
        )
    by_subject: dict[str, list[DatasetItem]] = defaultdict(list)
    for it in items:
        for subject in it.subject_ids or ():
            by_subject[subject].append(it)
    for subject, members, names in _straddles(by_subject, split_of):
        findings.append(
            LeakageFinding(
                "subject",
                "subject_straddles_splits",
                f"subject {subject!r} appears in splits {names}",
                _ids(members),
            )
        )
    return _result("subject", findings)


def _check_annotation_round(
    items: Sequence[DatasetItem],
    policy: SplitPolicy,
    rounds: Sequence[AnnotationRound],
) -> CheckResult:
    guideline_of = {r.round_id: r.guideline_ref for r in rounds}
    findings: list[LeakageFinding] = []
    undeclared = [it for it in items if it.annotation_round not in guideline_of]
    if undeclared:
        findings.append(
            LeakageFinding(
                "annotation_round",
                "undeclared_annotation_round",
                "items reference annotation rounds that are not declared: "
                f"{sorted({it.annotation_round for it in undeclared})}",
                _ids(undeclared),
            )
        )
    used = {it.annotation_round for it in items if it.annotation_round in guideline_of}
    guidelines = {guideline_of[r] for r in used}
    if len(guidelines) > 1 and not policy.allow_mixed_annotation_guidelines:
        listing = ", ".join(f"{r}->{guideline_of[r]}" for r in sorted(used))
        findings.append(
            LeakageFinding(
                "annotation_round",
                "mixed_annotation_guidelines",
                f"items were labeled under different guidelines ({listing}) and the "
                "split policy does not explicitly allow mixing",
                _ids(it for it in items if it.annotation_round in used),
            )
        )
    note = (
        "mixing of guidelines explicitly allowed by the split policy"
        if len(guidelines) > 1 and policy.allow_mixed_annotation_guidelines
        else ""
    )
    return _result("annotation_round", findings, note)


def _check_near_duplicate(
    items: Sequence[DatasetItem], policy: SplitPolicy, split_of: dict[str, str]
) -> CheckResult:
    findings: list[LeakageFinding] = []
    unhashed = [it for it in items if it.perceptual_hash is None]
    if unhashed:
        findings.append(
            LeakageFinding(
                "near_duplicate",
                "missing_perceptual_hash",
                "near-duplicate check needs a supplied perceptual hash for every item",
                _ids(unhashed),
            )
        )
    hashed = [it for it in items if it.perceptual_hash is not None]
    widths = {len(str(it.perceptual_hash)) for it in hashed}
    if len(widths) > 1:
        findings.append(
            LeakageFinding(
                "near_duplicate",
                "hash_length_mismatch",
                f"supplied hashes have different widths (hex digits: {sorted(widths)}); "
                "Hamming distance is undefined",
                _ids(hashed),
            )
        )
        return _result("near_duplicate", findings)

    values = sorted(
        ((it.item_id, int(str(it.perceptual_hash), 16)) for it in hashed), key=lambda p: p[0]
    )
    for i, (id_a, hash_a) in enumerate(values):
        for id_b, hash_b in values[i + 1 :]:
            if split_of[id_a] == split_of[id_b]:
                continue
            distance = (hash_a ^ hash_b).bit_count()
            if distance <= policy.max_hamming_distance:
                findings.append(
                    LeakageFinding(
                        "near_duplicate",
                        "near_duplicate_across_splits",
                        f"{id_a!r} ({split_of[id_a]}) and {id_b!r} ({split_of[id_b]}) have "
                        f"supplied hashes at distance {distance} "
                        f"(threshold {policy.max_hamming_distance})",
                        (id_a, id_b),
                    )
                )
    return _result("near_duplicate", findings)


def check_leakage(
    items: Sequence[DatasetItem],
    splits: Sequence[DatasetSplit],
    policy: SplitPolicy,
    annotation_rounds: Sequence[AnnotationRound],
) -> LeakageReport:
    """
    Run every leakage check and return the full report (it does not raise on leakage).

    Raises ValueError only when the inputs are structurally inconsistent — a
    report about splits that do not partition the items would be meaningless:
    an item in more than one split, an item in none, or a split naming an
    unknown item.
    """
    by_id: dict[str, DatasetItem] = {}
    for it in items:
        if it.item_id in by_id:
            raise ValueError(f"duplicate item_id {it.item_id!r}")
        by_id[it.item_id] = it

    split_of: dict[str, str] = {}
    for split in splits:
        for item_id in split.item_ids:
            if item_id not in by_id:
                raise ValueError(f"split {split.name!r} names unknown item {item_id!r}")
            if item_id in split_of:
                raise ValueError(f"item {item_id!r} is in more than one split")
            split_of[item_id] = split.name
    unassigned = sorted(set(by_id) - set(split_of))
    if unassigned:
        raise ValueError(f"items not assigned to any split: {unassigned}")

    return LeakageReport(
        results=(
            _check_temporal(items, splits, policy, split_of),
            _check_camera(items, policy, split_of),
            _check_subject(items, policy, split_of),
            _check_annotation_round(items, policy, annotation_rounds),
            _check_near_duplicate(items, policy, split_of),
        )
    )
