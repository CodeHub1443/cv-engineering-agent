"""
cv_agent.experiments.provenance — which committed code produced an evidence-bearing run.

Responsibility: answer "which commit did this run execute from?" and refuse to produce
evidence from an uncommitted working tree. Read-only: it calls `git` and writes nothing.

Boundary (CLAUDE.md §3 rule 6): provenance is a property of an ExperimentRecord, so it
belongs to the experiments layer. Execution runs jobs but does not record what produced
them; scripts and the graph consume this module instead of calling git themselves.

Exception policy: there is **no** exception flag. A dirty worktree is refused. A run from
uncommitted code cannot be reproduced from its record (EXPERIMENTS.md rule 4). If an
exception is ever needed it requires an owner decision recorded in docs/state/DECISIONS.md
first, and this module changes at that point.

Never fabricates a SHA: when git is unavailable or the tree is not a repository, the
function raises ProvenanceError rather than returning a placeholder.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHOW_LIMIT = 10


class ProvenanceError(RuntimeError):
    """Raised when the run's code state cannot be established or is not reproducible."""


def _git(repo_root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ProvenanceError(
            "git is not available; cannot establish run provenance"
        ) from exc
    if proc.returncode != 0:
        raise ProvenanceError(
            f"git {' '.join(args)} failed in {repo_root}: {proc.stderr.strip() or 'no output'}"
        )
    return proc.stdout


def current_commit(repo_root: Path) -> str:
    """Return the full 40-character SHA of HEAD in ``repo_root``."""
    sha = _git(repo_root, "rev-parse", "--verify", "HEAD").strip()
    if not _SHA_RE.match(sha):
        raise ProvenanceError(f"git returned a non-SHA for HEAD: {sha!r}")
    return sha


def dirty_entries(repo_root: Path) -> tuple[str, ...]:
    """Porcelain status lines for tracked changes and untracked, non-ignored files."""
    out = _git(repo_root, "status", "--porcelain", "--untracked-files=normal")
    return tuple(line for line in out.splitlines() if line.strip())


def require_clean_worktree(repo_root: Path) -> str:
    """Return HEAD's SHA if the worktree is clean; otherwise raise ProvenanceError.

    Gitignored state (for example ``.cv_agent/``, ``*.pt``) is not a change and is not counted.
    """
    entries = dirty_entries(repo_root)
    if entries:
        shown = "; ".join(entries[:_SHOW_LIMIT])
        more = (
            f" (+{len(entries) - _SHOW_LIMIT} more)"
            if len(entries) > _SHOW_LIMIT
            else ""
        )
        raise ProvenanceError(
            "refusing to produce evidence from a dirty worktree: commit or stash first "
            f"({len(entries)} entries: {shown}{more})"
        )
    return current_commit(repo_root)


STATE_DIRNAME = ".cv_agent"


def repository_state_root(start: Path | None = None) -> Path:
    """The main checkout's ``.cv_agent/`` directory, shared by every worktree of the repository.

    Resolved from ``start`` (default: the directory containing this package), never from the
    current working directory. ``git rev-parse --git-common-dir`` points at the main checkout's
    ``.git`` even when called from a linked worktree, so every worktree maps to one state root.
    Raises ProvenanceError when the package is not inside a git repository (fail closed).
    """
    anchor = (start or Path(__file__).resolve().parent).resolve()
    common = _git(anchor, "rev-parse", "--git-common-dir").strip()
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = anchor / common_path
    common_path = common_path.resolve()
    if common_path.name != ".git":
        raise ProvenanceError(
            f"unexpected git common directory {common_path}; refusing to guess the state root"
        )
    return common_path.parent / STATE_DIRNAME
