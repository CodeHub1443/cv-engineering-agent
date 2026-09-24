"""
Acceptance tests for cv_agent.datasets (ADR-0012, issue #59, ROADMAP Phase 5a).

Every dataset here is a small synthetic fixture. No image is read, no hash is
computed: perceptual hashes are supplied strings (docs/DATA.md leakage table).
"""

from __future__ import annotations

import ast
import dataclasses
import random
import sys
from pathlib import Path
from typing import Any

import pytest

from cv_agent.datasets import (
    AnnotationRound,
    ClassCount,
    ClassDefinition,
    CollectionConditions,
    DatasetCard,
    DatasetItem,
    DatasetManifest,
    DatasetSplit,
    DatasetStore,
    DatasetStoreError,
    InMemoryDatasetStore,
    LeakageError,
    Lineage,
    SplitPolicy,
    check_leakage,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

H_ZERO = "0000000000000000"
H_ONES = "ffffffffffffffff"
H_HALF_A = "f0f0f0f0f0f0f0f0"
H_HALF_B = "0f0f0f0f0f0f0f0f"


def item(
    item_id: str,
    *,
    segment: str | None = None,
    camera: str = "cam-A",
    ts: str | None = "2026-01-01T10:00:00",
    subjects: tuple[str, ...] | None = (),
    round_id: str = "r1",
    phash: str | None = H_ZERO,
) -> DatasetItem:
    return DatasetItem(
        item_id=item_id,
        segment_id=segment if segment is not None else f"seg-{item_id}",
        camera_id=camera,
        timestamp=ts,
        subject_ids=subjects,
        annotation_round=round_id,
        perceptual_hash=phash,
    )


def clean_items() -> list[DatasetItem]:
    """Train on cam-A (Jan), val on cam-B (Feb), test on cam-C (Mar)."""
    return [
        item("t1", camera="cam-A", ts="2026-01-01T10:00:00", phash=H_ZERO),
        item("t2", camera="cam-A", ts="2026-01-02T10:00:00", phash=H_ONES),
        item("v1", camera="cam-B", ts="2026-02-01T10:00:00", phash=H_HALF_A),
        item("x1", camera="cam-C", ts="2026-03-01T10:00:00", phash=H_HALF_B),
    ]


def clean_splits() -> list[DatasetSplit]:
    return [
        DatasetSplit("train", ("t1", "t2")),
        DatasetSplit("val", ("v1",)),
        DatasetSplit("test", ("x1",)),
    ]


def policy(**over: Any) -> SplitPolicy:
    base: dict[str, Any] = {
        "description": "camera-disjoint, time-ordered split",
        "camera_goal": "generalize_to_new_cameras",
        "time_order": ("train", "val", "test"),
        "subject_isolation": False,
    }
    base.update(over)
    return SplitPolicy(**base)


ROUNDS = (AnnotationRound("r1", "guideline-v1"), AnnotationRound("r2", "guideline-v2"))


def manifest_kwargs(**over: Any) -> dict[str, Any]:
    kw: dict[str, Any] = {
        "dataset_id": "prison-yard",
        "version": "v1",
        "created": "2026-04-01T00:00:00",
        "sources": ("site-cctv-export-1",),
        "classes": (
            ClassDefinition(
                name="wall_climb",
                definition="a person's feet leave the ground while both hands grip the wall",
                edge_cases=("leaning on the wall is negative",),
                temporal_boundary="starts at first foot-off, ends at drop or top",
            ),
        ),
        "class_distribution": (ClassCount("wall_climb", 12),),
        "items": clean_items(),
        "splits": clean_splits(),
        "split_policy": policy(),
        "annotation_version": "ann-1",
        "annotation_guideline_reference": "guideline-v1",
        "annotation_rounds": ROUNDS[:1],
        "known_issues": (),
        "lineage": None,
        "license": "internal use only",
        "collection_conditions": CollectionConditions(
            cameras=("cam-A", "cam-B", "cam-C"),
            sites=("yard-north",),
            times=("day",),
            lighting=("daylight",),
        ),
        "card": DatasetCard(
            contents="12 clips of wall-climb events",
            collection_method="exported from site NVR",
            intended_task="event detection",
            known_biases="daytime only",
            must_not_claim="night performance",
        ),
    }
    kw.update(over)
    return kw


def make_manifest(**over: Any) -> DatasetManifest:
    return DatasetManifest(**manifest_kwargs(**over))


def report_for(items: list[DatasetItem], splits: list[DatasetSplit], pol: SplitPolicy,
               rounds: tuple[AnnotationRound, ...] = ROUNDS[:1]):
    return check_leakage(items, splits, pol, rounds)


def codes(rep: Any, check: str) -> set[str]:
    return {f.code for f in rep.result(check).findings}


# ---------------------------------------------------------------------------
# Manifest construction / validation
# ---------------------------------------------------------------------------


class TestManifestConstruction:
    def test_valid_manifest_carries_every_data_md_field(self) -> None:
        m = make_manifest()
        assert (m.dataset_id, m.version) == ("prison-yard", "v1")
        assert m.created and m.sources and m.classes and m.class_distribution
        assert m.splits and m.split_policy and m.annotation_version == "ann-1"
        assert m.annotation_guideline_reference == "guideline-v1"
        assert m.known_issues == () and m.lineage is None
        assert m.license and m.collection_conditions.cameras
        assert m.card.must_not_claim

    def test_n_items_is_derived_not_supplied(self) -> None:
        assert make_manifest().n_items == 4
        with pytest.raises(TypeError):
            DatasetManifest(**manifest_kwargs(), n_items=99)  # type: ignore[call-arg]

    def test_lists_are_coerced_to_tuples_and_manifest_is_hashable(self) -> None:
        m = make_manifest(sources=["a", "b"])
        assert m.sources == ("a", "b")
        assert isinstance(m.items, tuple) and isinstance(m.splits, tuple)
        assert hash(m) == hash(make_manifest(sources=["a", "b"]))

    @pytest.mark.parametrize(
        "field",
        ["dataset_id", "version", "annotation_version", "annotation_guideline_reference", "license"],
    )
    @pytest.mark.parametrize("bad", ["", "   "])
    def test_required_text_fields_reject_blank(self, field: str, bad: str) -> None:
        with pytest.raises(ValueError, match=field):
            make_manifest(**{field: bad})

    @pytest.mark.parametrize("field", ["dataset_id", "version", "created", "license"])
    def test_required_text_fields_reject_non_string(self, field: str) -> None:
        with pytest.raises(ValueError, match=field):
            make_manifest(**{field: None})

    def test_created_must_be_iso_8601(self) -> None:
        with pytest.raises(ValueError, match="created"):
            make_manifest(created="last tuesday")

    def test_sources_required_and_nonblank(self) -> None:
        with pytest.raises(ValueError, match="sources"):
            make_manifest(sources=())
        with pytest.raises(ValueError, match="sources"):
            make_manifest(sources=("ok", " "))

    def test_string_is_not_accepted_as_a_sequence(self) -> None:
        with pytest.raises(ValueError, match="sources"):
            make_manifest(sources="site-cctv-export-1")

    def test_wrong_element_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="items"):
            make_manifest(items=["t1"])
        with pytest.raises(ValueError, match="splits"):
            make_manifest(splits=[("train", ("t1",))])

    def test_classes_required_unique_and_need_edge_cases(self) -> None:
        with pytest.raises(ValueError, match="classes"):
            make_manifest(classes=())
        cls = manifest_kwargs()["classes"][0]
        with pytest.raises(ValueError, match="duplicate"):
            make_manifest(classes=(cls, cls))
        with pytest.raises(ValueError, match="edge_cases"):
            ClassDefinition(name="x", definition="d", edge_cases=())
        with pytest.raises(ValueError, match="edge_cases"):
            ClassDefinition(name="x", definition="d", edge_cases=(" ",))

    def test_class_distribution_must_reference_defined_classes_with_valid_counts(self) -> None:
        with pytest.raises(ValueError, match="undefined class"):
            make_manifest(class_distribution=(ClassCount("ghost", 1),))
        with pytest.raises(ValueError, match="count"):
            ClassCount("wall_climb", -1)
        with pytest.raises(ValueError, match="count"):
            ClassCount("wall_climb", True)
        with pytest.raises(ValueError, match="duplicate"):
            make_manifest(class_distribution=(ClassCount("wall_climb", 1), ClassCount("wall_climb", 2)))

    def test_items_required_and_unique(self) -> None:
        with pytest.raises(ValueError, match="items"):
            make_manifest(items=(), splits=())
        with pytest.raises(ValueError, match="duplicate item_id"):
            make_manifest(items=clean_items() + [item("t1")])

    def test_item_camera_must_be_a_declared_collection_camera(self) -> None:
        cc = CollectionConditions(cameras=("cam-A", "cam-B"))
        with pytest.raises(ValueError, match="cam-C"):
            make_manifest(collection_conditions=cc)

    def test_collection_conditions_require_cameras(self) -> None:
        with pytest.raises(ValueError, match="cameras"):
            CollectionConditions(cameras=())

    def test_item_annotation_round_must_be_declared(self) -> None:
        with pytest.raises(ValueError, match="annotation_round"):
            make_manifest(annotation_rounds=(AnnotationRound("other", "g"),))

    def test_annotation_rounds_required_and_unique(self) -> None:
        with pytest.raises(ValueError, match="annotation_rounds"):
            make_manifest(annotation_rounds=())
        with pytest.raises(ValueError, match="duplicate"):
            make_manifest(annotation_rounds=(ROUNDS[0], ROUNDS[0]))

    def test_card_fields_are_all_required(self) -> None:
        for f in ("contents", "collection_method", "intended_task", "known_biases", "must_not_claim"):
            kw = {
                "contents": "c", "collection_method": "m", "intended_task": "t",
                "known_biases": "b", "must_not_claim": "n",
            }
            kw[f] = " "
            with pytest.raises(ValueError, match=f):
                DatasetCard(**kw)

    def test_known_issues_items_must_be_nonblank(self) -> None:
        with pytest.raises(ValueError, match="known_issues"):
            make_manifest(known_issues=("",))
        assert make_manifest(known_issues=("night frames missing",)).known_issues

    def test_lineage_requires_parent_and_transformation_and_cannot_self_reference(self) -> None:
        with pytest.raises(ValueError, match="parent_version"):
            Lineage(parent_version="", transformation="relabel")
        with pytest.raises(ValueError, match="transformation"):
            Lineage(parent_version="v0", transformation=" ")
        with pytest.raises(ValueError, match="own parent"):
            make_manifest(lineage=Lineage("v1", "noop"))
        assert make_manifest(version="v2", lineage=Lineage("v1", "relabel")).lineage

    def test_item_field_validation(self) -> None:
        for field in ("item_id", "segment_id", "camera_id", "annotation_round"):
            with pytest.raises(ValueError, match=field):
                DatasetItem(**{**dataclasses.asdict(item("z")), field: " "})
        with pytest.raises(ValueError, match="timestamp"):
            item("z", ts="yesterday")
        with pytest.raises(ValueError, match="perceptual_hash"):
            item("z", phash="not-hex!")
        with pytest.raises(ValueError, match="subject_ids"):
            item("z", subjects=("a", ""))

    def test_split_policy_validation(self) -> None:
        with pytest.raises(ValueError, match="camera_goal"):
            policy(camera_goal="whatever")
        with pytest.raises(ValueError, match="description"):
            policy(description=" ")
        with pytest.raises(ValueError, match="max_hamming_distance"):
            policy(max_hamming_distance=-1)
        with pytest.raises(ValueError, match="max_hamming_distance"):
            policy(max_hamming_distance=True)
        with pytest.raises(ValueError, match="time_order"):
            policy(time_order=("train",))
        with pytest.raises(ValueError, match="time_order"):
            policy(time_order=("train", "train"))
        with pytest.raises(ValueError, match="subject_isolation"):
            policy(subject_isolation="yes")

    def test_time_order_must_name_existing_splits(self) -> None:
        with pytest.raises(ValueError, match="time_order"):
            make_manifest(split_policy=policy(time_order=("train", "holdout")))


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------


class TestSplitRecording:
    def test_split_membership_is_recorded_verbatim_and_queryable(self) -> None:
        m = make_manifest()
        assert [(s.name, s.item_ids) for s in m.splits] == [
            ("train", ("t1", "t2")), ("val", ("v1",)), ("test", ("x1",)),
        ]
        assert m.split_of("v1") == "val"
        with pytest.raises(KeyError):
            m.split_of("nope")

    def test_every_item_is_in_exactly_one_split(self) -> None:
        with pytest.raises(ValueError, match="more than one split"):
            make_manifest(splits=[
                DatasetSplit("train", ("t1", "t2", "v1")), DatasetSplit("val", ("v1",)),
                DatasetSplit("test", ("x1",)),
            ])

    def test_unassigned_item_rejected(self) -> None:
        with pytest.raises(ValueError, match="not assigned"):
            make_manifest(
                splits=[DatasetSplit("train", ("t1", "t2")), DatasetSplit("val", ("v1",))],
                split_policy=policy(time_order=("train", "val")),
            )

    def test_split_referencing_unknown_item_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown item"):
            make_manifest(splits=[
                DatasetSplit("train", ("t1", "t2", "ghost")), DatasetSplit("val", ("v1",)),
                DatasetSplit("test", ("x1",)),
            ])

    def test_split_shape_rules(self) -> None:
        with pytest.raises(ValueError, match="splits"):
            make_manifest(splits=())
        with pytest.raises(ValueError, match="duplicate split"):
            make_manifest(splits=[DatasetSplit("a", ("t1", "t2")), DatasetSplit("a", ("v1", "x1"))])
        with pytest.raises(ValueError, match="item_ids"):
            DatasetSplit("train", ())
        with pytest.raises(ValueError, match="duplicate"):
            DatasetSplit("train", ("t1", "t1"))
        with pytest.raises(ValueError, match="name"):
            DatasetSplit(" ", ("t1",))


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_manifest_and_parts_are_frozen(self) -> None:
        m = make_manifest()
        for target, attr in [
            (m, "version"), (m.items[0], "camera_id"), (m.splits[0], "name"),
            (m.split_policy, "camera_goal"), (m.card, "contents"),
            (m.collection_conditions, "cameras"), (m.classes[0], "name"),
        ]:
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(target, attr, "x")

    def test_leakage_report_is_frozen(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            make_manifest().leakage_report.results = ()  # type: ignore[misc]

    def test_mutating_the_source_list_after_construction_does_not_change_the_manifest(self) -> None:
        items = clean_items()
        m = make_manifest(items=items)
        items.append(item("extra"))
        assert m.n_items == 4

    def test_store_rejects_overwriting_an_existing_version_and_keeps_original(self) -> None:
        store = InMemoryDatasetStore()
        original = make_manifest()
        store.put_manifest(original)
        changed = make_manifest(license="something else")
        with pytest.raises(DatasetStoreError, match="already exists"):
            store.put_manifest(changed)
        assert store.get_manifest("prison-yard", "v1") is original


# ---------------------------------------------------------------------------
# Leakage checks
# ---------------------------------------------------------------------------


class TestLeakageValidSplits:
    def test_clean_split_passes_every_check_and_report_is_recorded(self) -> None:
        m = make_manifest()
        rep = m.leakage_report
        assert rep.passed and rep.findings == ()
        assert [r.check for r in rep.results] == [
            "temporal", "camera", "subject", "annotation_round", "near_duplicate",
        ]
        assert rep.result("subject").status == "not_applicable"
        assert rep.result("temporal").status == "passed"

    def test_report_cannot_be_supplied_by_the_caller(self) -> None:
        with pytest.raises(TypeError):
            DatasetManifest(**manifest_kwargs(), leakage_report=None)  # type: ignore[call-arg]

    def test_recorded_report_equals_a_fresh_check(self) -> None:
        m = make_manifest()
        assert m.leakage_report == check_leakage(
            m.items, m.splits, m.split_policy, m.annotation_rounds
        )


class TestTemporalLeakage:
    def test_same_video_segment_across_splits_fails(self) -> None:
        items = clean_items()
        items[2] = item("v1", segment="seg-t1", camera="cam-B", ts="2026-02-01T10:00:00", phash=H_HALF_A)
        with pytest.raises(LeakageError) as exc:
            make_manifest(items=items)
        rep = exc.value.report
        assert not rep.passed
        f = rep.result("temporal").findings[0]
        assert f.code == "segment_straddles_splits"
        assert f.item_ids == ("t1", "v1")
        assert "seg-t1" in f.detail

    def test_time_order_violation_fails(self) -> None:
        items = clean_items()
        items[2] = item("v1", camera="cam-B", ts="2025-12-01T10:00:00", phash=H_HALF_A)  # val before train
        rep = report_for(items, clean_splits(), policy())
        assert rep.result("temporal").status == "failed"
        assert codes(rep, "temporal") == {"time_order_violation"}

    def test_equal_boundary_timestamps_count_as_overlap(self) -> None:
        items = clean_items()
        items[2] = item("v1", camera="cam-B", ts="2026-01-02T10:00:00", phash=H_HALF_A)
        assert codes(report_for(items, clean_splits(), policy()), "temporal") == {"time_order_violation"}

    def test_time_order_unverifiable_without_timestamps_fails_closed(self) -> None:
        items = clean_items()
        items[0] = item("t1", ts=None, phash=H_ZERO)
        rep = report_for(items, clean_splits(), policy())
        assert codes(rep, "temporal") == {"missing_timestamp"}

    def test_mixed_timezone_awareness_fails_closed(self) -> None:
        items = clean_items()
        items[0] = item("t1", ts="2026-01-01T10:00:00+00:00", phash=H_ZERO)
        assert codes(report_for(items, clean_splits(), policy()), "temporal") == {
            "mixed_timezone_awareness"
        }

    def test_timezone_aware_timestamps_are_compared_by_instant(self) -> None:
        items = [
            item("t1", camera="cam-A", ts="2026-01-01T12:00:00+02:00", phash=H_ZERO),  # 10:00Z
            item("v1", camera="cam-B", ts="2026-01-01T11:00:00+00:00", phash=H_HALF_A),
            item("x1", camera="cam-C", ts="2026-01-01T12:00:00+00:00", phash=H_HALF_B),
        ]
        splits = [DatasetSplit("train", ("t1",)), DatasetSplit("val", ("v1",)), DatasetSplit("test", ("x1",))]
        assert report_for(items, splits, policy()).passed

    def test_no_time_order_declared_skips_only_the_order_rule(self) -> None:
        items = clean_items()
        items[2] = item("v1", camera="cam-B", ts="2025-12-01T10:00:00", phash=H_HALF_A)
        assert report_for(items, clean_splits(), policy(time_order=None)).passed
        # ...but segment straddling is still caught
        items[2] = item("v1", segment="seg-t1", camera="cam-B", phash=H_HALF_A)
        assert codes(report_for(items, clean_splits(), policy(time_order=None)), "temporal") == {
            "segment_straddles_splits"
        }


class TestCameraLeakage:
    def test_camera_in_two_splits_fails_when_goal_is_new_cameras(self) -> None:
        items = clean_items()
        items[2] = item("v1", camera="cam-A", ts="2026-02-01T10:00:00", phash=H_HALF_A)
        with pytest.raises(LeakageError) as exc:
            make_manifest(items=items)
        f = exc.value.report.result("camera").findings[0]
        assert f.code == "camera_straddles_splits"
        assert "cam-A" in f.detail and f.item_ids == ("t1", "t2", "v1")

    def test_same_cameras_goal_is_explicitly_not_applicable(self) -> None:
        items = clean_items()
        items[2] = item("v1", camera="cam-A", ts="2026-02-01T10:00:00", phash=H_HALF_A)
        rep = report_for(items, clean_splits(), policy(camera_goal="same_cameras"))
        assert rep.result("camera").status == "not_applicable"
        assert rep.passed


class TestSubjectLeakage:
    def test_subject_in_two_splits_fails_when_isolation_required(self) -> None:
        items = clean_items()
        items[0] = item("t1", subjects=("p1",), phash=H_ZERO)
        items[2] = item("v1", camera="cam-B", ts="2026-02-01T10:00:00", subjects=("p1", "p2"), phash=H_HALF_A)
        with pytest.raises(LeakageError) as exc:
            make_manifest(items=items, split_policy=policy(subject_isolation=True))
        f = exc.value.report.result("subject").findings[0]
        assert f.code == "subject_straddles_splits" and f.item_ids == ("t1", "v1")

    def test_subject_overlap_ignored_when_isolation_not_required(self) -> None:
        items = clean_items()
        items[0] = item("t1", subjects=("p1",), phash=H_ZERO)
        items[2] = item("v1", camera="cam-B", ts="2026-02-01T10:00:00", subjects=("p1",), phash=H_HALF_A)
        assert report_for(items, clean_splits(), policy()).passed

    def test_unknown_subjects_fail_closed_when_isolation_required(self) -> None:
        items = clean_items()
        items[0] = item("t1", subjects=None, phash=H_ZERO)
        rep = report_for(items, clean_splits(), policy(subject_isolation=True))
        assert codes(rep, "subject") == {"missing_subject_ids"}

    def test_declared_empty_subjects_are_fine(self) -> None:
        assert report_for(clean_items(), clean_splits(), policy(subject_isolation=True)).passed


class TestAnnotationRoundLeakage:
    def _mixed(self) -> list[DatasetItem]:
        items = clean_items()
        items[2] = item("v1", camera="cam-B", ts="2026-02-01T10:00:00", round_id="r2", phash=H_HALF_A)
        return items

    def test_mixed_guidelines_fail_unless_explicitly_allowed(self) -> None:
        with pytest.raises(LeakageError) as exc:
            make_manifest(items=self._mixed(), annotation_rounds=ROUNDS)
        f = exc.value.report.result("annotation_round").findings[0]
        assert f.code == "mixed_annotation_guidelines"
        assert "guideline-v1" in f.detail and "guideline-v2" in f.detail

    def test_explicitly_allowed_mixing_passes_and_is_recorded_in_the_policy(self) -> None:
        m = make_manifest(
            items=self._mixed(), annotation_rounds=ROUNDS,
            split_policy=policy(allow_mixed_annotation_guidelines=True),
        )
        assert m.split_policy.allow_mixed_annotation_guidelines is True
        assert m.leakage_report.passed

    def test_two_rounds_sharing_one_guideline_is_not_mixing(self) -> None:
        rounds = (AnnotationRound("r1", "g"), AnnotationRound("r2", "g"))
        assert report_for(self._mixed(), clean_splits(), policy(), rounds).passed

    def test_undeclared_round_fails_closed_in_a_direct_check(self) -> None:
        items = clean_items()
        items[0] = item("t1", round_id="ghost", phash=H_ZERO)
        assert codes(report_for(items, clean_splits(), policy()), "annotation_round") == {
            "undeclared_annotation_round"
        }


class TestNearDuplicateLeakage:
    def test_identical_supplied_hash_across_splits_fails(self) -> None:
        items = clean_items()
        items[2] = item("v1", camera="cam-B", ts="2026-02-01T10:00:00", phash=H_ZERO)  # == t1
        with pytest.raises(LeakageError) as exc:
            make_manifest(items=items)
        f = exc.value.report.result("near_duplicate").findings[0]
        assert f.code == "near_duplicate_across_splits" and f.item_ids == ("t1", "v1")

    def test_same_hash_inside_one_split_is_not_leakage(self) -> None:
        items = clean_items()
        items[1] = item("t2", ts="2026-01-02T10:00:00", phash=H_ZERO)  # == t1, same split
        assert report_for(items, clean_splits(), policy()).passed

    def test_hamming_threshold_is_explicit_and_defaults_to_exact(self) -> None:
        items = clean_items()
        near = "0000000000000001"  # 1 bit from H_ZERO
        items[2] = item("v1", camera="cam-B", ts="2026-02-01T10:00:00", phash=near)
        assert report_for(items, clean_splits(), policy()).passed  # default 0 = exact only
        rep = report_for(items, clean_splits(), policy(max_hamming_distance=1))
        assert codes(rep, "near_duplicate") == {"near_duplicate_across_splits"}
        assert "distance 1" in rep.result("near_duplicate").findings[0].detail

    def test_hash_comparison_is_case_insensitive(self) -> None:
        items = clean_items()
        items[0] = item("t1", phash="ABCDEF0123456789")
        items[2] = item("v1", camera="cam-B", ts="2026-02-01T10:00:00", phash="abcdef0123456789")
        assert codes(report_for(items, clean_splits(), policy()), "near_duplicate") == {
            "near_duplicate_across_splits"
        }

    def test_missing_hash_fails_closed(self) -> None:
        items = clean_items()
        items[3] = item("x1", camera="cam-C", ts="2026-03-01T10:00:00", phash=None)
        assert codes(report_for(items, clean_splits(), policy()), "near_duplicate") == {
            "missing_perceptual_hash"
        }

    def test_hashes_of_different_widths_fail_closed(self) -> None:
        items = clean_items()
        items[3] = item("x1", camera="cam-C", ts="2026-03-01T10:00:00", phash="ff")
        assert codes(report_for(items, clean_splits(), policy()), "near_duplicate") == {
            "hash_length_mismatch"
        }


class TestLeakageDeterminism:
    def _leaky(self) -> tuple[list[DatasetItem], list[DatasetSplit]]:
        items = [
            item("t1", segment="s", camera="cam-A", ts="2026-01-01T10:00:00", subjects=("p",), phash=H_ZERO),
            item("t2", camera="cam-A", ts="2026-03-01T10:00:00", subjects=("p",), phash=H_ONES),
            item("v1", segment="s", camera="cam-A", ts="2026-02-01T10:00:00", subjects=("p",), phash=H_ZERO),
            item("x1", camera="cam-A", ts="2026-01-15T10:00:00", subjects=("p",), phash=H_ZERO, round_id="r2"),
        ]
        return items, clean_splits()

    def test_every_check_fires_on_a_maximally_leaky_fixture(self) -> None:
        items, splits = self._leaky()
        rep = report_for(items, splits, policy(subject_isolation=True), ROUNDS)
        assert {r.check for r in rep.results if r.status == "failed"} == {
            "temporal", "camera", "subject", "annotation_round", "near_duplicate",
        }
        assert not rep.passed

    def test_report_is_independent_of_input_order(self) -> None:
        items, splits = self._leaky()
        base = report_for(items, splits, policy(subject_isolation=True), ROUNDS)
        for seed in range(5):
            rnd = random.Random(seed)
            shuffled_items = items[:]
            rnd.shuffle(shuffled_items)
            shuffled_splits = [DatasetSplit(s.name, tuple(rnd.sample(s.item_ids, len(s.item_ids)))) for s in splits]
            rnd.shuffle(shuffled_splits)
            assert report_for(shuffled_items, shuffled_splits, policy(subject_isolation=True), ROUNDS) == base

    def test_same_input_gives_identical_reports(self) -> None:
        items, splits = self._leaky()
        pol = policy(subject_isolation=True)
        assert report_for(items, splits, pol, ROUNDS) == report_for(items, splits, pol, ROUNDS)

    def test_direct_check_reports_failure_without_raising(self) -> None:
        items, splits = self._leaky()
        assert not report_for(items, splits, policy(), ROUNDS).passed

    def test_direct_check_rejects_inconsistent_splits(self) -> None:
        with pytest.raises(ValueError, match="not assigned"):
            report_for(clean_items(), [DatasetSplit("train", ("t1",))], policy(time_order=None))
        with pytest.raises(ValueError, match="unknown item"):
            report_for(clean_items(), clean_splits() + [DatasetSplit("x", ("ghost",))], policy())

    def test_leakage_error_is_a_value_error_carrying_the_failed_report(self) -> None:
        items, _ = self._leaky()
        with pytest.raises(ValueError) as exc:
            make_manifest(items=items, annotation_rounds=ROUNDS)
        assert isinstance(exc.value, LeakageError)
        assert exc.value.report.findings


# ---------------------------------------------------------------------------
# Store protocol + in-memory reference implementation
# ---------------------------------------------------------------------------


class TestDatasetStore:
    def test_in_memory_store_satisfies_the_protocol(self) -> None:
        store: DatasetStore = InMemoryDatasetStore()
        assert store.list_versions("nothing") == ()

    def test_round_trip_returns_an_equal_manifest(self) -> None:
        store = InMemoryDatasetStore()
        m = make_manifest()
        store.put_manifest(m)
        got = store.get_manifest("prison-yard", "v1")
        assert got == m and got is not None and got.leakage_report.passed

    def test_get_missing_returns_none_not_an_error(self) -> None:
        store = InMemoryDatasetStore()
        assert store.get_manifest("x", "v1") is None
        store.put_manifest(make_manifest())
        assert store.get_manifest("prison-yard", "v9") is None
        assert store.get_manifest("other", "v1") is None

    def test_list_versions_is_in_registration_order_and_scoped_to_the_dataset(self) -> None:
        store = InMemoryDatasetStore()
        store.put_manifest(make_manifest(version="v1"))
        store.put_manifest(make_manifest(version="v10", lineage=Lineage("v1", "relabel")))
        store.put_manifest(make_manifest(version="v2", lineage=Lineage("v10", "relabel")))
        store.put_manifest(make_manifest(dataset_id="other", version="a"))
        assert store.list_versions("prison-yard") == ("v1", "v10", "v2")
        assert store.list_versions("other") == ("a",)

    def test_lineage_parent_must_already_be_stored_in_the_same_dataset(self) -> None:
        store = InMemoryDatasetStore()
        child = make_manifest(version="v2", lineage=Lineage("v1", "relabel"))
        with pytest.raises(DatasetStoreError, match="parent"):
            store.put_manifest(child)
        store.put_manifest(make_manifest(dataset_id="other", version="v1"))
        with pytest.raises(DatasetStoreError, match="parent"):
            store.put_manifest(child)  # v1 exists only under another dataset_id
        store.put_manifest(make_manifest(version="v1"))
        store.put_manifest(child)
        assert store.get_manifest("prison-yard", "v2") is child

    def test_failed_put_leaves_the_store_unchanged(self) -> None:
        store = InMemoryDatasetStore()
        store.put_manifest(make_manifest())
        with pytest.raises(DatasetStoreError):
            store.put_manifest(make_manifest())
        with pytest.raises(DatasetStoreError):
            store.put_manifest(make_manifest(version="v2", lineage=Lineage("missing", "x")))
        assert store.list_versions("prison-yard") == ("v1",)

    def test_only_manifests_can_be_stored(self) -> None:
        store = InMemoryDatasetStore()
        with pytest.raises(DatasetStoreError, match="DatasetManifest"):
            store.put_manifest({"dataset_id": "x"})  # type: ignore[arg-type]

    def test_stores_share_no_hidden_global_state(self) -> None:
        a, b = InMemoryDatasetStore(), InMemoryDatasetStore()
        a.put_manifest(make_manifest())
        assert b.get_manifest("prison-yard", "v1") is None
        assert InMemoryDatasetStore().list_versions("prison-yard") == ()

    def test_store_error_is_a_plain_exception_not_a_value_error(self) -> None:
        assert issubclass(DatasetStoreError, Exception)
        assert not issubclass(DatasetStoreError, ValueError)


# ---------------------------------------------------------------------------
# Package boundary (ADR-0012 §3/§7)
# ---------------------------------------------------------------------------


class TestArchitectureBoundary:
    _FORBIDDEN_PREFIXES = (
        "cv_agent.execution", "cv_agent.skills", "cv_agent.graph", "cv_agent.tools",
        "cv_agent.llm", "cv_agent.experiments", "cv_agent.memory", "cv_agent.knowledge",
        "cv_agent.runtime", "cv_agent.requirements", "cv_agent.capabilities",
    )

    def _files(self) -> list[Path]:
        root = Path(__file__).resolve().parent.parent / "cv_agent" / "datasets"
        files = sorted(root.glob("*.py"))
        assert files, "expected cv_agent/datasets/*.py to exist"
        return files

    def _imports(self, path: Path) -> list[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.append(node.module)
        return names

    def test_imports_nothing_from_other_cv_agent_layers(self) -> None:
        for path in self._files():
            for name in self._imports(path):
                for forbidden in self._FORBIDDEN_PREFIXES:
                    assert not name.startswith(forbidden), f"{path} imports {name!r}"

    def test_only_standard_library_and_own_package_are_imported(self) -> None:
        # No third-party (and so no image-processing) dependency, ADR-0012 §3.
        for path in self._files():
            for name in self._imports(path):
                top = name.split(".")[0]
                assert top in sys.stdlib_module_names or name.startswith("cv_agent.datasets"), (
                    f"{path} imports non-stdlib {name!r}"
                )

    def test_no_backend_or_pixel_processing_references(self) -> None:
        banned = ("dvc", "git_lfs", "boto3", "PIL", "cv2", "numpy", "imagehash", "sqlite3")
        for path in self._files():
            for name in self._imports(path):
                assert name.split(".")[0] not in banned, f"{path} imports {name!r}"

    def test_importing_the_package_has_no_side_effects(self) -> None:
        import importlib

        import cv_agent.datasets as pkg

        importlib.reload(pkg)
        assert InMemoryDatasetStore().list_versions("x") == ()
