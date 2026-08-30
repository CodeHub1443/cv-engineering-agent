"""CLI smoke tests for cv_agent.__main__."""

from __future__ import annotations

import subprocess
import sys


class TestCLISmoke:
    """Run the CLI as a subprocess to validate the end-to-end entrypoint."""

    def _run_cli(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "cv_agent"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_cli_exits_with_zero_or_one(self) -> None:
        """Exit code 0 = healthy, 1 = degraded but runnable, 2 = startup failure."""
        result = self._run_cli()
        assert result.returncode in (0, 1), (
            f"Unexpected exit code {result.returncode}.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    def test_cli_prints_health_header(self) -> None:
        result = self._run_cli()
        assert "CV Engineering Agent" in result.stdout

    def test_cli_prints_runtime_status(self) -> None:
        result = self._run_cli()
        assert "Runtime status" in result.stdout

    def test_cli_prints_provider(self) -> None:
        result = self._run_cli()
        assert "Provider" in result.stdout

    def test_cli_prints_model(self) -> None:
        result = self._run_cli()
        assert "Model" in result.stdout

    def test_cli_prints_capabilities(self) -> None:
        result = self._run_cli()
        assert "Capabilities" in result.stdout

    def test_cli_prints_langgraph(self) -> None:
        result = self._run_cli()
        assert "LangGraph" in result.stdout

    def test_cli_no_stderr_on_success(self) -> None:
        result = self._run_cli()
        if result.returncode == 0:
            # No errors should appear on stdout for a healthy run
            assert "STARTUP FAILURE" not in result.stdout

    def test_step_two_command_name_is_rejected_until_implemented(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "cv_agent", "skills"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 2
        assert "unrecognized arguments: skills" in result.stderr
