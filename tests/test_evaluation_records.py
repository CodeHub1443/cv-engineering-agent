"""
tests/test_evaluation_records.py — verify a measured yolo val run and record it (ADR-0017).

Every run here is synthetic: a two-image COCO-like dataset, a full-curve predictions file, a
val.log in the ultralytics format, and a run.json. No GPU, no network, no real .cv_agent/.
Each fail-closed test breaks exactly one thing and expects a refusal that names it.
"""

from __future__ import annotations

import importlib.util
import json
import struct
import sys
import time
from pathlib import Path

import pytest

from cv_agent.experiments.evaluation_records import (
    RUN_SCHEMA,
    DatasetExpectation,
    RecordError,
    build_record,
    preflight_new_ids,
    run_paths,
    sha256_file,
    verify_run,
    write_records,
)
from cv_agent.experiments.models import ExperimentRecord
from cv_agent.experiments.store import ExperimentLedgerError, open_ledger

HEAD = "c" * 40
OTHER = "d" * 40
EXPECT = DatasetExpectation(images=2, gt_persons=2)
STEM_A = "000000000001"
STEM_B = "000000000002"


def _jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 2 + 8) + b"\x00" * 8
    sof0 = b"\xff\xc0" + struct.pack(">H", 8) + b"\x08" + struct.pack(">HH", height, width) + b"\x01"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def _coco(root: Path, *, small_gt: bool = True) -> Path:
    """Two 100x100 images. A has one small person (4x4 px) unless small_gt is False. B has one large."""
    (root / "images" / "val2017").mkdir(parents=True)
    (root / "labels" / "val2017").mkdir(parents=True)
    for stem in (STEM_A, STEM_B):
        (root / "images" / "val2017" / f"{stem}.jpg").write_bytes(_jpeg(100, 100))
    a_size = 0.04 if small_gt else 0.5  # normalized width/height: 0.04 -> 4x4 px (small)
    (root / "labels" / "val2017" / f"{STEM_A}.txt").write_text(f"0 0.5 0.5 {a_size} {a_size}\n")
    (root / "labels" / "val2017" / f"{STEM_B}.txt").write_text("0 0.5 0.5 0.5 0.5\n")
    (root / "val2017.txt").write_text("images/val2017/a.jpg\n")
    return root


def _predictions() -> list[dict]:
    return [
        {"image_id": 1, "file_name": f"{STEM_A}.jpg", "category_id": 1, "bbox": [48, 48, 4, 4], "score": 0.9},
        {"image_id": 1, "file_name": f"{STEM_A}.jpg", "category_id": 1, "bbox": [0, 0, 4, 4], "score": 0.001},
        {"image_id": 2, "file_name": f"{STEM_B}.jpg", "category_id": 1, "bbox": [25, 25, 50, 50], "score": 0.8},
    ]


VAL_LOG = """Ultralytics 8.4.138 Python-3.10.12 torch-2.5.1+cu121 CUDA:0 (NVIDIA GeForce RTX 3060, 12042MiB)
YOLO11n summary (fused): 100 layers, 2,616,248 parameters, 0 gradients, 6.5 GFLOPs
                 Class     Images  Instances      Box(P          R      mAP50  mAP50-95)
                   all          2          2      0.800      0.500      0.600      0.450
Speed: 0.4ms preprocess, 5.3ms inference, 0.0ms loss, 0.7ms postprocess per image
"""


def make_run(
    tmp: Path,
    *,
    imgsz: int = 640,
    head: str = HEAD,
    small_gt: bool = True,
    val_log: str = VAL_LOG,
    predictions: str | None = None,
    run_overrides: dict | None = None,
) -> tuple[Path, Path]:
    """Build <tmp>/state/evaluations/<name>/ plus .val.log and .run.json. Returns (run_dir, coco_root)."""
    state = tmp / "state"
    evals = state / "evaluations"
    models = state / "models"
    evals.mkdir(parents=True, exist_ok=True)
    models.mkdir(parents=True, exist_ok=True)
    coco = _coco(tmp / "coco", small_gt=small_gt)
    weights = models / "yolo11n.pt"
    weights.write_bytes(b"weights-bytes")
    data_yaml = evals / "coco-person-val.yaml"
    data_yaml.write_text(f"path: {coco}\ntrain: val2017.txt\nval: val2017.txt\nnames:\n  0: person\n")
    name = f"e1-yolo11n-coco-val2017-imgsz{imgsz}-conf0001"
    run_dir = evals / name
    run_dir.mkdir()
    (run_dir / "predictions.json").write_text(
        predictions if predictions is not None else json.dumps(_predictions())
    )
    run_json, val_log_path, _ = run_paths(run_dir)
    val_log_path.write_text(val_log)
    run = {
        "schema": RUN_SCHEMA,
        "series": "EXP-20261004-01",
        "imgsz": imgsz,
        "conf": 0.001,
        "batch": 1,
        "device": "0",
        "classes": [0],
        "quantize": 16,
        "precision_requested": "FP16 requested (quantize=16); actual inference precision is not logged",
        "approval_ref": "APPROVAL-TEST",
        "vram_baseline_mib": 360,
        "vram_peak_mib": 600,
        "ram_peak_mib": 900.5,
        "model": "yolo11n.pt",
        "model_path": str(weights),
        "data_yaml": str(data_yaml),
        "val_txt": str(coco / "val2017.txt"),
        "model_sha256": sha256_file(weights),
        "data_yaml_sha256": sha256_file(data_yaml),
        "val_txt_sha256": sha256_file(coco / "val2017.txt"),
        "run_dir": str(run_dir),
        "command": ["yolo", "val"],
        "exit_code": 0,
        "started_at": "2026-10-04T10:00:00+00:00",
        "ended_at": "2026-10-04T10:00:03+00:00",
        "wall_seconds": 3.0,
        "commit": head,
        "gpu_name": "NVIDIA GeForce RTX 3060",
        "gpu_memory_mib": 12042,
        "driver_version": "535.309.01",
    }
    run.update(run_overrides or {})
    run_json.write_text(json.dumps(run), encoding="utf-8")
    return run_dir, coco


def _verify(run_dir: Path, coco: Path, *, imgsz: int = 640, head: str = HEAD, expect=EXPECT):
    return verify_run(run_dir, imgsz=imgsz, coco_root=coco, head_commit=head, dataset=expect)


def _problems(run_dir: Path, coco: Path, **kwargs) -> str:
    with pytest.raises(RecordError) as info:
        _verify(run_dir, coco, **kwargs)
    return " | ".join(info.value.problems)


# ── successful recording ─────────────────────────────────────────────────────────


def test_verified_run_builds_a_complete_record(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path)
    run = _verify(run_dir, coco)
    record = build_record(run, exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="APPROVAL-TEST")

    assert isinstance(record, ExperimentRecord)
    assert record.status == "completed"
    assert record.commit == HEAD
    assert record.baseline_id == "SELF"
    assert record.approval_ref == "APPROVAL-TEST"
    assert record.input_resolution == "640x640"
    assert record.batch_size == 1
    assert (record.precision or "").startswith("FP16")
    assert record.params == 2616248
    assert record.created_at == "2026-10-04T10:00:00+00:00"
    assert record.completed_at == "2026-10-04T10:00:03+00:00"
    assert record.hardware is not None and "RTX 3060" in record.hardware.target
    # Latency is derived from the Speed line; fps from the measured wall time (2 images / 3 s).
    assert record.latency is not None
    assert record.latency.end_to_end == pytest.approx(0.4 + 5.3 + 0.7)
    assert record.latency.inference_only == pytest.approx(5.3)
    assert record.fps == pytest.approx(2 / 3.0)
    # System metrics are measured: peak VRAM and peak RAM (MiB), not invented.
    assert record.memory is not None
    assert record.memory.vram == pytest.approx(600.0)
    assert record.memory.ram == pytest.approx(900.5)
    # gpu_hours is derived from the measured wall time (one device), not a separate meter.
    assert record.gpu_hours == pytest.approx(3.0 / 3600.0)
    # Still not measured, so not fabricated.
    assert record.train_time is None
    assert record.power is None
    assert record.flops is None


def test_standard_and_reference_metrics_are_kept_apart(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path)
    record = build_record(_verify(run_dir, coco), exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="APPROVAL-TEST")
    metrics = record.val_metrics or {}
    standard = {k for k in metrics if not k.startswith("fixed_thr@")}
    reference = {k for k in metrics if k.startswith("fixed_thr@0.25/")}
    assert {"mAP@0.5", "mAP@0.5:0.95", "AP@0.5/small", "AP@0.5/large"} <= standard
    assert "fixed_thr@0.25/precision" in reference and "fixed_thr@0.25/recall" in reference
    assert "AP@0.5/small" in standard and "fixed_thr@0.25/recall_small" in reference
    # The ultralytics max-F1 P/R from the log is deliberately not recorded as anything.
    assert "precision" not in metrics and "recall" not in metrics
    assert metrics["mAP@0.5:0.95"] == pytest.approx(0.45)


def test_notes_carry_protocol_artifacts_and_hashes(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path)
    record = build_record(_verify(run_dir, coco), exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="APPROVAL-TEST")
    notes = json.loads(record.notes or "{}")
    assert "REFERENCE ONLY" in notes["confidence_protocol"]
    assert notes["imgsz"] == 640
    for key in ("val_log", "predictions_json", "run_json", "weights", "data_yaml", "val_txt"):
        assert len(notes["artifacts"][key]["sha256"]) == 64
    assert notes["artifacts"]["weights"]["sha256"] == sha256_file(tmp_path / "state" / "models" / "yolo11n.pt")
    assert "gpu_hours" in notes["derived"] and "wall_seconds / 3600" in notes["derived"]["gpu_hours"]
    assert "power" in notes["not_measured"]


def test_three_series_records_write_and_leave_history_untouched(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.sqlite"
    historical = build_record(
        _verify(*make_run(tmp_path / "old")), exp_id="EXP-20260929-01", baseline_id="SELF", approval_ref="APPROVAL-TEST"
    )
    ledger = open_ledger(db_path=ledger_path, create=True)
    try:
        ledger.record_experiment(historical)
        before = ledger.get_experiment("EXP-20260929-01")

        records = []
        plan = {640: ("EXP-20261004-01", "SELF"), 960: ("EXP-20261004-02", "EXP-20261004-01"),
                1280: ("EXP-20261004-03", "EXP-20261004-01")}
        for size, (exp_id, baseline) in plan.items():
            run_dir, coco = make_run(tmp_path / f"run{size}", imgsz=size)
            run = _verify(run_dir, coco, imgsz=size)
            records.append(build_record(run, exp_id=exp_id, baseline_id=baseline, approval_ref="APPROVAL-TEST"))
        preflight_new_ids(ledger, [r.exp_id for r in records])
        assert write_records(ledger, records) == ["EXP-20261004-01", "EXP-20261004-02", "EXP-20261004-03"]
        assert ledger.get_experiment("EXP-20261004-02").baseline_id == "EXP-20261004-01"  # type: ignore[union-attr]
        assert ledger.get_experiment("EXP-20260929-01") == before
    finally:
        ledger.close()  # type: ignore[attr-defined]


def test_missing_stratum_is_omitted_and_noted_not_invented(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path, small_gt=False)  # no small ground truth at all
    record = build_record(_verify(run_dir, coco), exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="APPROVAL-TEST")
    assert "AP@0.5/small" not in (record.val_metrics or {})
    notes = json.loads(record.notes or "{}")
    assert "AP@0.5/small" in notes["omitted_metrics"]


# ── preflight and ledger refusals ────────────────────────────────────────────────


def test_existing_exp_id_refuses_the_whole_batch(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path)
    record = build_record(_verify(run_dir, coco), exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="APPROVAL-TEST")
    ledger = open_ledger(db_path=tmp_path / "l.sqlite", create=True)
    try:
        ledger.record_experiment(record)
        with pytest.raises(RecordError, match="already exists"):
            preflight_new_ids(ledger, ["EXP-20261004-01", "EXP-20261004-02"])
        assert len(ledger.list_experiments()) == 1
    finally:
        ledger.close()  # type: ignore[attr-defined]


def test_missing_ledger_is_not_created(tmp_path: Path) -> None:
    missing = tmp_path / "nowhere" / "experiments.sqlite"
    with pytest.raises(ExperimentLedgerError, match="refusing to create"):
        open_ledger(db_path=missing)
    assert not missing.exists()


# ── fail-closed verification ─────────────────────────────────────────────────────


def test_truncated_predictions_are_refused(tmp_path: Path) -> None:
    truncated = [dict(p, score=0.25 + 0.1 * i) for i, p in enumerate(_predictions())]
    run_dir, coco = make_run(tmp_path, predictions=json.dumps(truncated))
    assert "TRUNCATED" in _problems(run_dir, coco)


@pytest.mark.parametrize(
    ("predictions", "expected"),
    [
        ("{not json", "invalid JSON"),
        ("[]", "non-empty"),
        ('[{"image_id": 1, "file_name": "a.jpg", "category_id": 1, "score": 0.5}]', "malformed bbox"),
        (
            '[{"image_id": 1, "file_name": "a.jpg", "category_id": 1, "bbox": [0,0,4,4], "score": NaN}]',
            "non-finite or out-of-range score",
        ),
        (
            '[{"image_id": 1, "file_name": "a.jpg", "category_id": 1, "bbox": [0,0,-1,4], "score": 0.5}]',
            "malformed bbox",
        ),
        (
            '[{"image_id": 1, "file_name": "a.jpg", "category_id": 1, "bbox": [0,0,4,-2], "score": 0.5}]',
            "malformed bbox",
        ),
        (
            '[{"image_id": 1, "file_name": "a.jpg", "category_id": 1, "bbox": [NaN,0,4,4], "score": 0.5}]',
            "malformed bbox",
        ),
        (
            '[{"image_id": 1, "file_name": "a.jpg", "category_id": 1, "bbox": [0,0,4], "score": 0.5}]',
            "malformed bbox",
        ),
    ],
)
def test_malformed_predictions_are_refused(tmp_path: Path, predictions: str, expected: str) -> None:
    run_dir, coco = make_run(tmp_path, predictions=predictions)
    assert expected in _problems(run_dir, coco)


@pytest.mark.parametrize("missing", ["run.json", "val.log", "predictions.json"])
def test_missing_artifact_is_refused(tmp_path: Path, missing: str) -> None:
    run_dir, coco = make_run(tmp_path)
    run_json, val_log, predictions = run_paths(run_dir)
    {"run.json": run_json, "val.log": val_log, "predictions.json": predictions}[missing].unlink()
    assert f"{missing} is missing" in _problems(run_dir, coco)


def test_nonzero_exit_is_refused(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path, run_overrides={"exit_code": 1})
    assert "exit_code=1" in _problems(run_dir, coco)


@pytest.mark.parametrize(
    "override",
    [{"conf": 0.25}, {"quantize": None}, {"batch": 2}, {"device": "cpu"}, {"classes": [0, 2]}, {"model": "yolo11s.pt"}],
)
def test_off_protocol_run_is_refused(tmp_path: Path, override: dict) -> None:
    run_dir, coco = make_run(tmp_path, run_overrides=override)
    assert next(iter(override)) in _problems(run_dir, coco)


def test_run_from_a_different_commit_is_refused(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path, head=OTHER)
    assert "code that ran must be the code being recorded" in _problems(run_dir, coco, head=HEAD)


def test_weights_changed_since_the_run_are_refused(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path)
    (tmp_path / "state" / "models" / "yolo11n.pt").write_bytes(b"different-weights")
    assert "changed since the run" in _problems(run_dir, coco)


def test_val_log_without_summary_row_is_refused(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path, val_log=VAL_LOG.replace("                   all", "                   xxx"))
    assert "'all' aggregate row" in _problems(run_dir, coco)


def test_val_log_without_speed_line_is_refused(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path, val_log=VAL_LOG.replace("Speed:", "Pace:"))
    assert "no 'Speed:' line" in _problems(run_dir, coco)


def test_traceback_in_log_is_refused(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path, val_log=VAL_LOG + "Traceback (most recent call last):\n")
    assert "Traceback" in _problems(run_dir, coco)


def test_dataset_count_mismatch_is_refused(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path)
    assert "dataset expects 3/2" in _problems(run_dir, coco, expect=DatasetExpectation(images=3, gt_persons=2))


def test_missing_gpu_identity_is_refused(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path, run_overrides={"gpu_name": None})
    assert "no GPU identity" in _problems(run_dir, coco)


def test_run_schema_mismatch_is_refused(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path, run_overrides={"schema": "something-else"})
    with pytest.raises(RecordError, match="schema"):
        _verify(run_dir, coco)


def test_sha256_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "f"
    path.write_bytes(b"abc")
    assert sha256_file(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


# ── the run wrapper (no GPU: argv and the refusal path only) ───────────────────────


def _load_wrapper():
    path = Path(__file__).resolve().parent.parent / "scripts" / "run_yolo_val_measured.py"
    spec = importlib.util.spec_from_file_location("run_yolo_val_measured", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_wrapper_argv_fixes_the_protocol_and_only_varies_imgsz(tmp_path: Path) -> None:
    wrapper = _load_wrapper()
    argv = wrapper.build_argv(960, state_root=tmp_path, executable="yolo")
    assert argv[:2] == ["yolo", "val"]
    for token in ("conf=0.001", "imgsz=960", "batch=1", "device=0", "classes=[0]", "quantize=16", "exist_ok=True"):
        assert token in argv
    assert not any(a.startswith("half") for a in argv)  # half is deprecated in ultralytics 8.4
    assert any(a.endswith("e1-yolo11n-coco-val2017-imgsz960-conf0001") for a in argv)
    other = wrapper.build_argv(640, state_root=tmp_path, executable="yolo")
    # Same tokens except the image size and the run name.
    assert [a for a in argv if not a.startswith(("imgsz=", "name="))] == [
        a for a in other if not a.startswith(("imgsz=", "name="))
    ]


def test_wrapper_refuses_a_dirty_tree_before_running_anything(monkeypatch, capsys) -> None:
    wrapper = _load_wrapper()

    def dirty(_root):
        raise wrapper.ProvenanceError("dirty for test")

    def must_not_run(*_a, **_k):
        pytest.fail("yolo must not start on a dirty tree")

    monkeypatch.setattr(wrapper, "require_clean_worktree", dirty)
    monkeypatch.setattr(wrapper.subprocess, "Popen", must_not_run)
    assert wrapper.main(["--imgsz", "640", "--approval-ref", "APPROVAL-TEST"]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_wrapper_rejects_unapproved_image_size() -> None:
    wrapper = _load_wrapper()
    with pytest.raises(SystemExit):
        wrapper.main(["--imgsz", "800"])


# ── Review changes (ADR-0017 §3.2–§3.8): precision label, approval, system metrics ───────

REQUESTED_LABEL = "FP16 requested (quantize=16); actual inference precision is not logged"


def test_precision_is_the_requested_label_not_a_measurement(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path)
    record = build_record(_verify(run_dir, coco), exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="APPROVAL-TEST")
    assert record.precision == REQUESTED_LABEL
    assert "measured" not in (record.precision or "").replace("not logged", "")


def test_run_without_the_exact_precision_label_is_refused(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path, run_overrides={"precision_requested": "FP16"})
    assert "exact requested-precision label" in _problems(run_dir, coco)


def test_control_record_names_the_legacy_fp32_reference(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path)
    record = build_record(_verify(run_dir, coco), exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="APPROVAL-TEST")
    legacy = json.loads(record.notes or "{}")["legacy_reference"]
    assert "EXP-20260930-01" in legacy and "FP32" in legacy and "NOT like-for-like" in legacy


def test_series_follower_has_no_legacy_note(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path, imgsz=960)
    record = build_record(_verify(run_dir, coco, imgsz=960), exp_id="EXP-20261004-02", baseline_id="EXP-20261004-01", approval_ref="APPROVAL-TEST")
    assert "legacy_reference" not in json.loads(record.notes or "{}")


@pytest.mark.parametrize("approval", [None, "", "   "])
def test_run_without_an_approval_reference_is_refused(tmp_path: Path, approval) -> None:
    run_dir, coco = make_run(tmp_path, run_overrides={"approval_ref": approval})
    assert "no approval_ref" in _problems(run_dir, coco)


def test_build_refuses_a_run_approved_under_a_different_reference(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path)
    with pytest.raises(RecordError, match="every run in a series must carry the same approval"):
        build_record(_verify(run_dir, coco), exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="OTHER")


@pytest.mark.parametrize("override", [{"vram_peak_mib": None}, {"vram_peak_mib": 0}, {"vram_peak_mib": "600"}])
def test_missing_or_zero_vram_peak_is_refused(tmp_path: Path, override: dict) -> None:
    run_dir, coco = make_run(tmp_path, run_overrides=override)
    assert "vram_peak_mib is missing or not a positive integer" in _problems(run_dir, coco)


@pytest.mark.parametrize("override", [{"ram_peak_mib": None}, {"ram_peak_mib": 0.0}])
def test_missing_or_zero_ram_peak_is_refused(tmp_path: Path, override: dict) -> None:
    run_dir, coco = make_run(tmp_path, run_overrides=override)
    assert "ram_peak_mib is missing or not positive" in _problems(run_dir, coco)


def test_gpu_hours_is_derived_from_wall_time_and_labelled(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path, run_overrides={"wall_seconds": 1800.0, "ended_at": "2026-10-04T10:30:00+00:00"})
    record = build_record(_verify(run_dir, coco), exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="APPROVAL-TEST")
    assert record.gpu_hours == pytest.approx(0.5)
    assert record.fps == pytest.approx(2 / 1800.0)
    assert "wall_seconds / 3600" in json.loads(record.notes or "{}")["derived"]["gpu_hours"]


def test_partial_batch_write_is_reported_not_claimed_atomic(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path)
    record = build_record(_verify(run_dir, coco), exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="APPROVAL-TEST")
    second = build_record(_verify(run_dir, coco), exp_id="EXP-20261004-02", baseline_id="EXP-20261004-01", approval_ref="APPROVAL-TEST")

    class FailsSecond:
        def __init__(self) -> None:
            self.calls = 0

        def record_experiment(self, _record) -> None:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("disk full")

    with pytest.raises(RecordError) as info:
        write_records(FailsSecond(), [record, second])
    message = info.value.problems[0]
    assert "failed writing EXP-20261004-02" in message and "already written: ['EXP-20261004-01']" in message


def _load_writer():
    path = Path(__file__).resolve().parent.parent / "scripts" / "record_evaluation_runs.py"
    spec = importlib.util.spec_from_file_location("record_evaluation_runs", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_writer_refuses_a_series_with_mixed_approvals(tmp_path: Path, monkeypatch, capsys) -> None:
    writer = _load_writer()
    monkeypatch.setattr(writer, "require_clean_worktree", lambda _root: HEAD)
    monkeypatch.setattr(writer, "DatasetExpectation", lambda: EXPECT)  # 2 images / 2 persons fixture
    runs = []
    coco = None
    for size, approval in ((640, "APPROVAL-TEST"), (960, "APPROVAL-TEST"), (1280, "DIFFERENT")):
        run_dir, coco = make_run(tmp_path / f"s{size}", imgsz=size, run_overrides={"approval_ref": approval})
        runs += ["--run", f"{size}={run_dir}"]
    code = writer.main(["--approval-ref", "APPROVAL-TEST", *runs, "--coco-root", str(coco), "--dry-run"])
    err = capsys.readouterr().err
    assert code == 1
    assert "[1280] run approval 'DIFFERENT' != --approval-ref 'APPROVAL-TEST'" in err
    assert "nothing recorded" in err


def test_writer_refuses_a_blank_approval_reference(monkeypatch, capsys) -> None:
    writer = _load_writer()
    assert writer.main(["--approval-ref", "  ", "--run", "640=/x", "--run", "960=/x", "--run", "1280=/x"]) == 2


def test_wrapper_requires_the_approval_argument() -> None:
    wrapper = _load_wrapper()
    with pytest.raises(SystemExit):
        wrapper.main(["--imgsz", "640"])


def test_wrapper_refuses_a_blank_approval_before_any_run(monkeypatch, capsys) -> None:
    wrapper = _load_wrapper()
    monkeypatch.setattr(wrapper.subprocess, "Popen", lambda *a, **k: pytest.fail("no run on blank approval"))
    assert wrapper.main(["--imgsz", "640", "--approval-ref", "   "]) == 2
    assert "must not be blank" in capsys.readouterr().err


def test_ru_maxrss_is_converted_from_linux_kib_to_mib() -> None:
    wrapper = _load_wrapper()
    assert wrapper.ru_maxrss_to_mib(2048) == pytest.approx(2.0)
    assert wrapper.ru_maxrss_to_mib(1024 * 1536) == pytest.approx(1536.0)


@pytest.mark.parametrize(("text", "expected"), [("  1234\n", 1234), ("[N/A]\n", None), ("", None)])
def test_nvidia_smi_memory_parse(text: str, expected) -> None:
    assert _load_wrapper().parse_memory_used(text) == expected


def test_vram_sampler_keeps_baseline_and_peak_and_skips_failed_polls(monkeypatch) -> None:
    wrapper = _load_wrapper()
    values = iter([300, None, 900, 450])
    last = {"v": 450}

    def fake(_cls=None):
        try:
            last["v"] = next(values)
        except StopIteration:
            pass
        return last["v"]

    monkeypatch.setattr(wrapper.VramSampler, "sample_once", staticmethod(fake))
    sampler = wrapper.VramSampler(interval=0.001)
    sampler.start()
    for _ in range(5000):  # let the poller take its samples before stopping
        if len(sampler.samples) >= 2:
            break
        time.sleep(0.001)
    peak = sampler.stop()
    assert sampler.baseline_mib == 300
    assert peak == 900  # the poll that returned None was skipped, not invented as 0
    assert 900 in sampler.samples


def test_vram_sampler_reports_none_when_no_sample_succeeds(monkeypatch) -> None:
    wrapper = _load_wrapper()
    monkeypatch.setattr(wrapper.VramSampler, "sample_once", staticmethod(lambda: None))
    sampler = wrapper.VramSampler(interval=0.001)
    sampler.start()
    assert sampler.stop() is None


# ── Verifier fixes (EXP-20261004-01 review): aggregate row and zero-area boxes ─────

# The exact summary-table shape ultralytics printed for the completed runs: an 'all' aggregate row
# (5000 images, 10777 instances) followed by a per-class 'person' row (2693 images, same instances).
REAL_TABLE_LOG = """Ultralytics 8.4.138 Python-3.10.12 torch-2.5.1+cu121 CUDA:0 (NVIDIA GeForce RTX 3060, 12042MiB)
YOLO11n summary (fused): 100 layers, 2,616,248 parameters, 0 gradients, 6.5 GFLOPs
                 Class     Images  Instances      Box(P          R      mAP50  mAP50-95)
                   all          2          2      0.811       0.65       0.75      0.517
                person          1          2      0.811       0.65       0.75      0.517
Speed: 0.4ms preprocess, 5.7ms inference, 0.0ms loss, 0.7ms postprocess per image
"""

# Zero-area boxes observed in the real predictions files: a clipped box with w or h exactly 0.0,
# at very low scores, next to ordinary boxes. These are legitimate validator output.
REAL_ZERO_AREA_PREDICTIONS = [
    {"image_id": 1, "file_name": f"{STEM_A}.jpg", "category_id": 1, "bbox": [48, 48, 4, 4], "score": 0.9},
    {"image_id": 1, "file_name": f"{STEM_A}.jpg", "category_id": 1, "bbox": [0, 0, 4, 4], "score": 0.001},
    {"image_id": 2, "file_name": f"{STEM_B}.jpg", "category_id": 55, "bbox": [185.5, 425.0, 324.5, 0.0], "score": 0.00306},
    {"image_id": 2, "file_name": f"{STEM_B}.jpg", "category_id": 60, "bbox": [0.0, 129.704, 0.0, 17.693], "score": 0.00315},
    {"image_id": 2, "file_name": f"{STEM_B}.jpg", "category_id": 1, "bbox": [25, 25, 50, 50], "score": 0.8},
]


def test_aggregate_row_is_selected_by_name_not_by_position(tmp_path: Path) -> None:
    # 'all' is first and 'person' last. The old code took the last row (2693 images) and refused.
    run_dir, coco = make_run(tmp_path, val_log=REAL_TABLE_LOG)
    run = _verify(run_dir, coco)
    assert run.images == 2 and run.gt_persons == 2
    assert run.map50 == pytest.approx(0.75) and run.map50_95 == pytest.approx(0.517)


def test_person_row_after_all_row_does_not_change_the_counts(tmp_path: Path) -> None:
    # A person row with a different image count must not be the basis for the dataset check.
    run_dir, coco = make_run(tmp_path, val_log=REAL_TABLE_LOG.replace("person          1", "person       2693"))
    assert _verify(run_dir, coco).images == 2


def test_wrong_all_row_counts_are_still_refused(tmp_path: Path) -> None:
    # The aggregate itself must report the dataset: 'all' with 3 images is refused even though the
    # person row is fine.
    run_dir, coco = make_run(tmp_path, val_log=REAL_TABLE_LOG.replace("all          2", "all          3"))
    assert "dataset expects 2/2" in _problems(run_dir, coco)


def test_log_with_only_a_person_row_is_refused(tmp_path: Path) -> None:
    only_person = "\n".join(line for line in REAL_TABLE_LOG.splitlines() if "all" not in line.split())
    run_dir, coco = make_run(tmp_path, val_log=only_person)
    assert "exactly one 'all' aggregate row (found 0)" in _problems(run_dir, coco)


def test_log_with_two_all_rows_is_refused(tmp_path: Path) -> None:
    doubled = REAL_TABLE_LOG.replace("person          1", "all          2")
    run_dir, coco = make_run(tmp_path, val_log=doubled)
    assert "exactly one 'all' aggregate row (found 2)" in _problems(run_dir, coco)


def test_real_zero_area_boxes_are_accepted_end_to_end(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path, val_log=REAL_TABLE_LOG, predictions=json.dumps(REAL_ZERO_AREA_PREDICTIONS))
    run = _verify(run_dir, coco)
    record = build_record(run, exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="APPROVAL-TEST")
    assert record.status == "completed"


@pytest.mark.parametrize(
    "bbox",
    [[0.0, 0.0, 0.0, 0.0], [5.0, 5.0, 0.0, 3.2], [5.0, 5.0, 2.0, 0.0]],
)
def test_zero_width_height_and_zero_area_boxes_are_accepted(tmp_path: Path, bbox) -> None:
    preds = [dict(p) for p in _predictions()] + [
        {"image_id": 1, "file_name": f"{STEM_A}.jpg", "category_id": 1, "bbox": bbox, "score": 0.002}
    ]
    run_dir, coco = make_run(tmp_path, predictions=json.dumps(preds))
    assert _verify(run_dir, coco).gt_persons == 2


@pytest.mark.parametrize(
    "bbox",
    [
        [0.0, 0.0, -0.5, 4.0],  # negative width
        [0.0, 0.0, 4.0, -0.5],  # negative height
        [0.0, 0.0, float("nan"), 4.0],  # non-finite
        [0.0, 0.0, float("inf"), 4.0],  # non-finite
        [0.0, 0.0, 4.0],  # wrong length
        [0.0, 0.0, "4", 4.0],  # wrong type
        [None, 0.0, 4.0, 4.0],  # wrong type
    ],
)
def test_invalid_geometry_is_still_refused(tmp_path: Path, bbox) -> None:
    preds = [dict(p) for p in _predictions()] + [
        {"image_id": 1, "file_name": f"{STEM_A}.jpg", "category_id": 1, "bbox": bbox, "score": 0.002}
    ]
    run_dir, coco = make_run(tmp_path, predictions=json.dumps(preds))
    assert "malformed bbox" in _problems(run_dir, coco)
