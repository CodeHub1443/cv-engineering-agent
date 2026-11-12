"""Repository hygiene for secrets handling (ADR-0021, D-088; issue #85).

Owns: checks that `.env` files are git-ignored, denied to Claude Code reads, and that the
operating instructions carry the same secrets rule.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SECRETS_SENTENCE = (
    "Never read, print, log or commit `.env`, `.env.*` or any API key (ADR-0021)."
)


def _in_git_checkout() -> bool:
    if shutil.which("git") is None:
        return False
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def test_env_files_are_git_ignored() -> None:
    if not _in_git_checkout():
        pytest.skip("not inside a git checkout or git is missing")
    # `git check-ignore -q` accepts a single path only, so check each one.
    for name in (".env", ".env.local"):
        result = subprocess.run(
            ["git", "check-ignore", "-q", name],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, name


def test_claude_settings_deny_env_reads() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    deny = settings["permissions"]["deny"]
    assert "Read(./.env)" in deny
    assert "Read(./.env.*)" in deny


@pytest.mark.parametrize("name", ["CLAUDE.md", "AGENTS.md"])
def test_rule_8_carries_secrets_sentence(name: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8")
    flat = " ".join(text.split())
    assert SECRETS_SENTENCE in flat


def test_claude_md_has_no_net_growth() -> None:
    lines = (ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 153
