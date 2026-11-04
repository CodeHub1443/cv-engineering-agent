"""
tests/test_experiment_provenance.py — run provenance and write-once commit_sha.

Covers cv_agent.experiments.provenance (dirty-worktree refusal, commit resolution) against
real temporary git repositories, and the SqliteExperimentLedger upsert rule that a stored
commit_sha is never erased by a later NULL. No GPU, no network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cv_agent.experiments.models import ExperimentRecord
from cv_agent.experiments.store import ExperimentLedgerError
from cv_agent.experiments.provenance import (
    ProvenanceError,
    current_commit,
    dirty_entries,
    require_clean_worktree,
)
from cv_agent.experiments.sqlite_store import SqliteExperimentLedger

_SHA_A = "a" * 40
_SHA_B = "b" * 40


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repository with one commit, a .gitignore for .cv_agent/, and a clean tree."""
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("/.cv_agent/\n*.pt\n")
    (tmp_path / "tracked.txt").write_text("v1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    return tmp_path


def test_clean_repository_returns_head_sha(repo: Path) -> None:
    sha = require_clean_worktree(repo)
    assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)
    assert sha == _git(repo, "rev-parse", "HEAD").strip()
    assert sha == current_commit(repo)


def test_modified_tracked_file_refuses(repo: Path) -> None:
    (repo / "tracked.txt").write_text("v2\n")
    with pytest.raises(ProvenanceError, match="tracked.txt"):
        require_clean_worktree(repo)


def test_untracked_file_refuses(repo: Path) -> None:
    (repo / "new_module.py").write_text("x = 1\n")
    with pytest.raises(ProvenanceError, match="new_module.py"):
        require_clean_worktree(repo)


def test_gitignored_state_does_not_count_as_dirty(repo: Path) -> None:
    (repo / ".cv_agent").mkdir()
    (repo / ".cv_agent" / "experiments.sqlite").write_bytes(b"db")
    (repo / "yolo11n.pt").write_bytes(b"weights")
    assert dirty_entries(repo) == ()
    assert require_clean_worktree(repo) == current_commit(repo)


def test_not_a_repository_refuses_rather_than_fabricating(tmp_path: Path) -> None:
    with pytest.raises(ProvenanceError):
        require_clean_worktree(tmp_path)


def test_error_lists_at_most_ten_entries(repo: Path) -> None:
    for i in range(12):
        (repo / f"f{i:02d}.py").write_text("")
    with pytest.raises(ProvenanceError, match=r"\(\+2 more\)"):
        require_clean_worktree(repo)


# ── commit_sha is write-once in the SQLite ledger ─────────────────────────────


def _record(**overrides: object) -> ExperimentRecord:
    fields: dict[str, object] = {
        "exp_id": "EXP-20260101-01",
        "status": "proposed",
        "hypothesis": "h",
        "success_criteria": "s",
        "baseline_id": "SELF",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    fields.update(overrides)
    return ExperimentRecord(**fields)  # type: ignore[arg-type]


def _completed(**overrides: object) -> ExperimentRecord:
    return _record(
        status="completed", completed_at="2026-01-01T01:00:00+00:00", **overrides
    )


def test_evidence_record_without_commit_is_refused(tmp_path: Path) -> None:
    # ADR-0016 §3: a run that started must name the commit it ran from.
    with SqliteExperimentLedger(tmp_path / "e.sqlite") as ledger:
        with pytest.raises(ExperimentLedgerError, match="no valid commit SHA"):
            ledger.record_experiment(_completed(commit=None))
        assert ledger.get_experiment("EXP-20260101-01") is None


def test_proposed_sha_survives_later_null_write(tmp_path: Path) -> None:
    # The sweep bug: prepare wrote a SHA; a later write with no SHA must not erase it.
    with SqliteExperimentLedger(tmp_path / "e.sqlite") as ledger:
        ledger.record_experiment(_record(commit=_SHA_A))
        ledger.record_experiment(_record(commit=None))
        stored = ledger.get_experiment("EXP-20260101-01")
    assert stored is not None
    assert stored.commit == _SHA_A


def test_null_proposed_then_completed_with_sha_is_recorded(tmp_path: Path) -> None:
    with SqliteExperimentLedger(tmp_path / "e.sqlite") as ledger:
        ledger.record_experiment(_record(commit=None))
        ledger.record_experiment(_completed(commit=_SHA_B))
        stored = ledger.get_experiment("EXP-20260101-01")
    assert stored is not None
    assert stored.status == "completed"
    assert stored.commit == _SHA_B


def test_non_null_commit_from_later_write_takes_effect(tmp_path: Path) -> None:
    # Only NULL is refused; a deliberate non-null value is an explicit write.
    with SqliteExperimentLedger(tmp_path / "e.sqlite") as ledger:
        ledger.record_experiment(_record(commit=_SHA_A))
        ledger.record_experiment(_record(status="running", commit=_SHA_B))
        stored = ledger.get_experiment("EXP-20260101-01")
    assert stored is not None
    assert stored.commit == _SHA_B


# ── Execute path refuses before any GPU work ──────────────────────────────────


def _load_sweep_script():
    import importlib.util  # noqa: PLC0415
    import sys  # noqa: PLC0415

    path = Path(__file__).parent.parent / "scripts" / "run_threshold_sweep.py"
    spec = importlib.util.spec_from_file_location(
        "run_threshold_sweep_provenance", path
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_sweep_execute_refuses_dirty_tree_before_preflight(monkeypatch) -> None:
    import cv_agent.experiments.provenance as provenance  # noqa: PLC0415

    mod = _load_sweep_script()

    def dirty(_repo_root: Path) -> str:
        raise provenance.ProvenanceError("dirty for test")

    def preflight_must_not_run() -> None:
        pytest.fail("GPU preflight reached before the provenance check")

    monkeypatch.setattr(provenance, "require_clean_worktree", dirty)
    monkeypatch.setattr(mod, "_preflight", preflight_must_not_run)
    with pytest.raises(SystemExit, match="REFUSED"):
        mod._execute_mode()
