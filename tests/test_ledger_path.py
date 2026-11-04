"""
tests/test_ledger_path.py — the experiment ledger resolves deterministically to the repository's
state root, regardless of the working directory or whether the caller is a linked worktree.

Regression for the relative-path defect: the default used Path.cwd(), so a run from a worktree
silently created an empty ledger there. Uses temporary git repositories only; the real ledger
in the user's checkout is never opened.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import cv_agent.experiments.provenance as provenance
from cv_agent.experiments.models import ExperimentRecord
from cv_agent.experiments.sqlite_store import SqliteExperimentLedger
from cv_agent.experiments.store import (
    ExperimentLedgerError,
    default_db_path,
    open_ledger,
)

_REAL_STATE_ROOT = provenance.repository_state_root


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture
def main_and_worktree(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    (main / ".gitignore").write_text("/.cv_agent/\n")
    (main / "x.txt").write_text("x\n")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "initial")
    worktree = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", "feature/test-wt", str(worktree))
    return main, worktree


def _record() -> ExperimentRecord:
    return ExperimentRecord(
        exp_id="EXP-20260101-01",
        status="proposed",
        hypothesis="h",
        success_criteria="s",
        baseline_id="SELF",
        created_at="2026-01-01T00:00:00+00:00",
    )


def test_worktree_maps_to_main_checkout_state_root(main_and_worktree) -> None:
    main, worktree = main_and_worktree
    assert _REAL_STATE_ROOT(start=worktree) == (main / ".cv_agent").resolve()


def test_state_root_does_not_depend_on_current_directory(main_and_worktree, tmp_path, monkeypatch) -> None:
    main, worktree = main_and_worktree
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # not a repository at all
    assert _REAL_STATE_ROOT(start=worktree) == (main / ".cv_agent").resolve()


def test_default_path_ignores_current_directory(tmp_path, monkeypatch) -> None:
    fake_root = tmp_path / "fake-main" / ".cv_agent"
    monkeypatch.setattr(provenance, "repository_state_root", lambda start=None: fake_root)
    monkeypatch.chdir(tmp_path)
    assert default_db_path() == fake_root / "experiments.sqlite"


def test_explicit_workspace_root_is_unchanged(tmp_path) -> None:
    assert default_db_path(workspace_root=tmp_path) == tmp_path / ".cv_agent" / "experiments.sqlite"


def test_open_ledger_refuses_to_create_a_missing_default_ledger(tmp_path, monkeypatch) -> None:
    state_root = tmp_path / "main" / ".cv_agent"
    monkeypatch.setattr(provenance, "repository_state_root", lambda start=None: state_root)
    with pytest.raises(ExperimentLedgerError, match="refusing to create an empty one"):
        open_ledger()
    assert not state_root.exists(), "no directory or empty ledger may be created silently"


def test_run_from_worktree_reads_main_ledger_and_creates_nothing_in_worktree(
    main_and_worktree, monkeypatch
) -> None:
    main, worktree = main_and_worktree
    main_db = main / ".cv_agent" / "experiments.sqlite"
    seed = SqliteExperimentLedger(main_db)  # the real ledger lives in main (created here, tmp only)
    try:
        seed.record_experiment(_record())
    finally:
        seed.close()

    # Simulate a run whose code lives in the worktree.
    monkeypatch.setattr(
        provenance,
        "repository_state_root",
        lambda start=None: _REAL_STATE_ROOT(start=worktree),
    )
    ledger = open_ledger()
    try:
        assert ledger.get_experiment("EXP-20260101-01") is not None
    finally:
        ledger.close()  # type: ignore[attr-defined]
    assert not (worktree / ".cv_agent").exists(), "a worktree must not get its own ledger"


def test_outside_a_repository_resolution_fails_closed(tmp_path, monkeypatch) -> None:
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    monkeypatch.setattr(
        provenance,
        "repository_state_root",
        lambda start=None: _REAL_STATE_ROOT(start=not_a_repo),
    )
    with pytest.raises(ExperimentLedgerError, match="cannot resolve"):
        default_db_path()
