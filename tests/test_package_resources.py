"""Tests that default runtime resources travel with the package."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def test_copied_package_loads_default_resources_outside_repository(
    tmp_path: Path,
) -> None:
    """Removing sibling repo directories must not degrade the default runtime."""
    source_package = Path(__file__).parent.parent / "cv_agent"
    target_package = tmp_path / "cv_agent"
    shutil.copytree(source_package, target_package, ignore=shutil.ignore_patterns("__pycache__"))

    result = subprocess.run(
        [sys.executable, "-m", "cv_agent"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Runtime status  : OK" in result.stdout
    assert "Capabilities    : 9 registered" in result.stdout
