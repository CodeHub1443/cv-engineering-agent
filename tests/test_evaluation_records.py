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
        "half": True,
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
    # Not measured, so not fabricated.
    assert record.memory is None
    assert record.gpu_hours is None
    assert record.train_time is None
    assert record.power is None
    assert record.flops is None


def test_standard_and_reference_metrics_are_kept_apart(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path)
    record = build_record(_verify(run_dir, coco), exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="A")
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
    record = build_record(_verify(run_dir, coco), exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="A")
    notes = json.loads(record.notes or "{}")
    assert "REFERENCE ONLY" in notes["confidence_protocol"]
    assert notes["imgsz"] == 640
    for key in ("val_log", "predictions_json", "run_json", "weights", "data_yaml", "val_txt"):
        assert len(notes["artifacts"][key]["sha256"]) == 64
    assert notes["artifacts"]["weights"]["sha256"] == sha256_file(tmp_path / "state" / "models" / "yolo11n.pt")
    assert "not_measured" in notes and "memory (VRAM/RAM not sampled)" in notes["not_measured"]


def test_three_series_records_write_and_leave_history_untouched(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.sqlite"
    historical = build_record(
        _verify(*make_run(tmp_path / "old")), exp_id="EXP-20260929-01", baseline_id="SELF", approval_ref="old"
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
    record = build_record(_verify(run_dir, coco), exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="A")
    assert "AP@0.5/small" not in (record.val_metrics or {})
    notes = json.loads(record.notes or "{}")
    assert "AP@0.5/small" in notes["omitted_metrics"]


# ── preflight and ledger refusals ────────────────────────────────────────────────


def test_existing_exp_id_refuses_the_whole_batch(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path)
    record = build_record(_verify(run_dir, coco), exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="A")
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
            '[{"image_id": 1, "file_name": "a.jpg", "category_id": 1, "bbox": [0,0,0,4], "score": 0.5}]',
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
    [{"conf": 0.25}, {"half": False}, {"batch": 2}, {"device": "cpu"}, {"classes": [0, 2]}, {"model": "yolo11s.pt"}],
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
    assert "no class summary row" in _problems(run_dir, coco)


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
    for token in ("conf=0.001", "imgsz=960", "batch=1", "device=0", "classes=[0]", "half=True", "exist_ok=True"):
        assert token in argv
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
    assert wrapper.main(["--imgsz", "640"]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_wrapper_rejects_unapproved_image_size() -> None:
    wrapper = _load_wrapper()
    with pytest.raises(SystemExit):
        wrapper.main(["--imgsz", "800"])
