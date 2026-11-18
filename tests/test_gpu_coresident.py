"""Explicit co-resident GPU process opt-in (ADR-0018 amendment 2026-11-18, D-128, issue #184).

No GPU is used: nvidia-smi and the `yolo val` child are faked. The wrapper imports `resource`
(POSIX only), so a stub is installed here when the module is missing, which lets these tests run
on Windows too.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

if "resource" not in sys.modules:
    try:
        import resource  # noqa: F401
    except ImportError:
        _stub = types.ModuleType("resource")
        _stub.RUSAGE_CHILDREN = -1  # type: ignore[attr-defined]
        _stub.getrusage = lambda _who: types.SimpleNamespace(ru_maxrss=900_000)  # type: ignore[attr-defined]
        sys.modules["resource"] = _stub

from cv_agent.experiments.evaluation_records import (  # noqa: E402
    build_record,
    foreign_process_seen,
    run_paths,
)
from tests.test_evaluation_records import (  # noqa: E402
    FOREIGN_PROC,
    HEAD,
    OWN_PID,
    OWN_PROC,
    _clean_gpu_snapshots,
    _ds_args,
    _fake_nvidia_smi,
    _load_wrapper,
    _problems,
    _snaps,
    _verify,
    make_run,
)

RUSTDESK = "/usr/share/rustdesk/rustdesk"
RUSTDESK_PROC = {"pid": 2001, "name": RUSTDESK, "used_mib": 140}
COCARD = {"pid": 2001, "process_name": RUSTDESK, "used_mib": 140}
CAVEAT = "GPU shared with co-resident process(es); latency/FPS/VRAM not comparable with clean-GPU runs."
RUSTDESK_SMI = f"2001, {RUSTDESK}, 140\n"


def _coresident_run(tmp_path: Path, **over: object):
    snaps = _snaps(
        start={"at": "t", "processes": [RUSTDESK_PROC]},
        during=[{"at": "t", "processes": [OWN_PROC, RUSTDESK_PROC]}],
        end={"at": "t", "processes": [RUSTDESK_PROC]},
    )
    overrides = {"gpu_process_snapshots": snaps, "foreign_process_seen": False, "gpu_coresident": [COCARD], **over}
    return make_run(tmp_path, run_overrides=overrides)


def _notes(run_dir: Path, coco: Path) -> dict:
    run = _verify(run_dir, coco)
    return json.loads(build_record(run, exp_id="EXP-20261004-01", baseline_id="SELF", approval_ref="APPROVAL-TEST").notes)


# ── snapshot parsing: the 3-column query and the old 2-column text ────────────────────


def test_parse_compute_apps_reads_used_memory_and_still_reads_two_columns() -> None:
    wrapper = _load_wrapper()
    assert wrapper.parse_compute_apps(RUSTDESK_SMI) == [{"pid": 2001, "name": RUSTDESK, "used_mib": 140}]
    assert wrapper.parse_compute_apps("2001, /x/y, [N/A]\n") == [{"pid": 2001, "name": "/x/y", "used_mib": None}]
    assert wrapper.parse_compute_apps("308159, .venv/bin/python\n") == [{"pid": 308159, "name": ".venv/bin/python"}]


def test_compute_apps_query_asks_for_used_memory() -> None:
    assert "pid,process_name,used_memory" in " ".join(_load_wrapper().COMPUTE_APPS_ARGV)


# ── the flag ──────────────────────────────────────────────────────────────────────────


def test_unnamed_process_still_refuses_when_another_is_allowed(tmp_path: Path, monkeypatch, capsys) -> None:
    wrapper = _load_wrapper()
    make_run(tmp_path / "other", imgsz=960)
    monkeypatch.setattr(wrapper, "repository_state_root", lambda: tmp_path / "other" / "state")
    monkeypatch.setattr(wrapper, "require_clean_worktree", lambda _r: HEAD)
    monkeypatch.setattr(wrapper.subprocess, "run", _fake_nvidia_smi(f"{RUSTDESK_SMI}308159, .venv/bin/python, 500\n"))
    monkeypatch.setattr(wrapper.subprocess, "Popen", lambda *a, **k: pytest.fail("no run with an unnamed process"))
    argv = ["--imgsz", "640", "--approval-ref", "A", "--allow-gpu-process", RUSTDESK, *_ds_args(tmp_path / "other")]
    assert wrapper.main(argv) == 2
    assert "compute process" in capsys.readouterr().err


def test_relative_or_empty_allow_path_is_refused(tmp_path: Path, monkeypatch, capsys) -> None:
    wrapper = _load_wrapper()
    monkeypatch.setattr(wrapper.subprocess, "Popen", lambda *a, **k: pytest.fail("no run"))
    for bad in ("rustdesk", "./rustdesk", "bin/rustdesk", ""):
        argv = ["--imgsz", "640", "--approval-ref", "A", "--allow-gpu-process", bad, *_ds_args(tmp_path / "x")]
        assert wrapper.main(argv) == 2
        assert "absolute" in capsys.readouterr().err


class _FakePopen:
    def __init__(self, *_a: object, **_k: object) -> None:
        self.pid = OWN_PID
        self.stdout = iter(["fake yolo output\n"])

    def wait(self) -> int:
        return 0


def _run_wrapper(tmp_path: Path, monkeypatch, smi: str, *allow: str) -> dict:
    wrapper = _load_wrapper()
    make_run(tmp_path / "other", imgsz=960)
    state = tmp_path / "other" / "state"
    monkeypatch.setattr(wrapper, "repository_state_root", lambda: state)
    monkeypatch.setattr(wrapper, "require_clean_worktree", lambda _r: HEAD)
    monkeypatch.setattr(wrapper, "environment_fingerprint", lambda: {k: "x" for k in wrapper.ENVIRONMENT_KEYS})
    monkeypatch.setattr(wrapper.subprocess, "run", _fake_nvidia_smi(smi))
    monkeypatch.setattr(wrapper.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(wrapper, "VRAM_POLL_SECONDS", 0.01)
    flags = [arg for path in allow for arg in ("--allow-gpu-process", path)]
    argv = ["--imgsz", "640", "--approval-ref", "A", *flags, *_ds_args(tmp_path / "other")]
    assert wrapper.main(argv) == 0
    [run_json] = (state / "evaluations").glob("*imgsz640*.run.json")
    return json.loads(run_json.read_text(encoding="utf-8"))


def test_named_process_passes_the_idle_check_and_is_recorded(tmp_path: Path, monkeypatch) -> None:
    run = _run_wrapper(tmp_path, monkeypatch, RUSTDESK_SMI, RUSTDESK)
    assert run["gpu_coresident"] == [COCARD]
    assert run["foreign_process_seen"] is False


def test_allowed_but_absent_process_records_an_empty_list(tmp_path: Path, monkeypatch) -> None:
    run = _run_wrapper(tmp_path, monkeypatch, "", RUSTDESK)
    assert run["gpu_coresident"] == []


def test_without_the_flag_nothing_is_allowed_and_the_field_is_empty(tmp_path: Path, monkeypatch) -> None:
    assert _run_wrapper(tmp_path, monkeypatch, "")["gpu_coresident"] == []


def test_allow_flag_is_repeatable_and_matches_exactly(tmp_path: Path, monkeypatch, capsys) -> None:
    other = "/opt/other/app"
    run = _run_wrapper(tmp_path, monkeypatch, f"{RUSTDESK_SMI}2002, {other}, 10\n", RUSTDESK, other)
    assert {p["process_name"] for p in run["gpu_coresident"]} == {RUSTDESK, other}


def test_a_lookalike_path_is_not_allowed(tmp_path: Path, monkeypatch, capsys) -> None:
    wrapper = _load_wrapper()
    make_run(tmp_path / "other", imgsz=960)
    monkeypatch.setattr(wrapper, "repository_state_root", lambda: tmp_path / "other" / "state")
    monkeypatch.setattr(wrapper, "require_clean_worktree", lambda _r: HEAD)
    monkeypatch.setattr(wrapper.subprocess, "run", _fake_nvidia_smi("2001, /tmp/usr/share/rustdesk/rustdesk, 140\n"))
    monkeypatch.setattr(wrapper.subprocess, "Popen", lambda *a, **k: pytest.fail("no run"))
    argv = ["--imgsz", "640", "--approval-ref", "A", "--allow-gpu-process", RUSTDESK, *_ds_args(tmp_path / "other")]
    assert wrapper.main(argv) == 2


# ── the writer ────────────────────────────────────────────────────────────────────────


def test_writer_accepts_a_recorded_co_resident_process_at_every_point(tmp_path: Path) -> None:
    run_dir, coco = _coresident_run(tmp_path)
    assert _verify(run_dir, coco).gpu_coresident == (COCARD,)


def test_writer_still_refuses_an_unrecorded_process_next_to_a_co_resident_one(tmp_path: Path) -> None:
    snaps = _snaps(during=[{"at": "t", "processes": [OWN_PROC, RUSTDESK_PROC, FOREIGN_PROC]}])
    run_dir, coco = _coresident_run(tmp_path, gpu_process_snapshots=snaps, foreign_process_seen=True)
    assert "foreign GPU process during the run" in _problems(run_dir, coco)


def test_writer_refuses_a_process_that_was_not_recorded_as_co_resident(tmp_path: Path) -> None:
    run_dir, coco = _coresident_run(tmp_path, gpu_coresident=[], foreign_process_seen=True)
    assert "before the run started" in _problems(run_dir, coco)


@pytest.mark.parametrize(
    "bad",
    ["rustdesk", [RUSTDESK], [{"pid": "x", "process_name": RUSTDESK, "used_mib": 1}], [{"pid": 1, "process_name": 5}]],
)
def test_writer_refuses_a_malformed_gpu_coresident(tmp_path: Path, bad: object) -> None:
    run_dir, coco = _coresident_run(tmp_path, gpu_coresident=bad)
    assert "gpu_coresident" in _problems(run_dir, coco)


def test_foreign_process_seen_honours_the_allowed_names() -> None:
    snaps = _snaps(during=[{"at": "t", "processes": [OWN_PROC, RUSTDESK_PROC]}])
    assert foreign_process_seen(snaps, OWN_PID) is True
    assert foreign_process_seen(snaps, OWN_PID, allowed=frozenset({RUSTDESK})) is False


# ── notes and the caveat ──────────────────────────────────────────────────────────────


def test_co_resident_process_reaches_the_notes_with_the_caveat(tmp_path: Path) -> None:
    run_dir, coco = _coresident_run(tmp_path)
    notes = _notes(run_dir, coco)
    assert notes["gpu_coresident"] == [COCARD]
    assert notes["gpu_coresident_caveat"] == CAVEAT


def test_empty_or_absent_co_resident_adds_neither_key(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path / "a", run_overrides={"gpu_coresident": []})
    assert "gpu_coresident" not in _notes(run_dir, coco)
    run_dir, coco = make_run(tmp_path / "b")
    assert "gpu_coresident_caveat" not in _notes(run_dir, coco)


def test_old_run_json_with_two_column_snapshots_and_no_field_still_parses(tmp_path: Path) -> None:
    run_dir, coco = make_run(tmp_path)  # snapshots hold only {pid, name}; no gpu_coresident, no used_mib
    run_json, _, _ = run_paths(run_dir)
    assert "gpu_coresident" not in json.loads(run_json.read_text())
    assert "used_mib" not in json.dumps(_clean_gpu_snapshots())
    assert _verify(run_dir, coco).gpu_coresident == ()
