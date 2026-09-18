"""CLI smoke tests for cv_agent.__main__."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class TestCLISmoke:
    """Run the CLI as a subprocess to validate the end-to-end entrypoint."""

    def _run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "cv_agent", *args],
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


class TestCLISkillsCapabilitiesResolve:
    """
    Step 2 CLI commands. Every subprocess run pins CV_AGENT_SKILL_PATHS to an
    isolated tmp_path fixture so these tests never depend on whatever is
    actually installed under the real ~/.claude/skills on the machine
    running the suite.
    """

    def _run(self, args: list[str], skill_root: Path) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["CV_AGENT_SKILL_PATHS"] = str(skill_root)
        return subprocess.run(
            [sys.executable, "-m", "cv_agent", *args],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            # The `workflow` command resolves workspace_root from cwd
            # (ADR-0004 §1 item 13) — pin it to the isolated skill_root so
            # no test ever creates .cv_agent/ in the real repository.
            cwd=str(skill_root),
            # `workflow` (PR #34) falls back to a live `input()` prompt for
            # any interrupt field no --answer/--input flag covers. Pin
            # stdin closed so that fallback always sees immediate EOF and
            # this test suite never blocks waiting on a real terminal,
            # regardless of what the *parent* test-runner process's own
            # stdin happens to be connected to.
            stdin=subprocess.DEVNULL,
        )

    def _write_skill(self, root: Path, skill_id: str, description: str) -> None:
        skill_dir = root / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {skill_id}\ndescription: {description}\n---\nbody\n",
            encoding="utf-8",
        )

    def test_skills_command_reports_zero_for_empty_fixture(self, tmp_path: Path) -> None:
        result = self._run(["skills"], tmp_path)
        assert result.returncode == 0, result.stderr
        assert "Discovered skills: 0" in result.stdout

    def test_skills_command_reports_a_fixture_skill(self, tmp_path: Path) -> None:
        self._write_skill(tmp_path, "fixture-skill", "A fake test skill.")
        result = self._run(["skills"], tmp_path)
        assert result.returncode == 0, result.stderr
        assert "Discovered skills: 1" in result.stdout
        assert "fixture-skill" in result.stdout
        assert "executable=False" in result.stdout

    def test_skills_command_never_reports_a_fake_undiscovered_skill(
        self, tmp_path: Path
    ) -> None:
        """A skill that was never written to the fixture root must never
        appear as discovered — nothing is fabricated."""
        result = self._run(["skills"], tmp_path)
        assert "definitely-not-a-real-skill" not in result.stdout

    def test_capabilities_command_lists_declared_capabilities(self, tmp_path: Path) -> None:
        result = self._run(["capabilities"], tmp_path)
        assert result.returncode == 0, result.stderr
        assert "Declared capabilities:" in result.stdout
        assert "status=planned" in result.stdout
        assert "not executable" in result.stdout

    def test_resolve_command_produces_structured_output(self, tmp_path: Path) -> None:
        result = self._run(
            ["resolve", "deploy RT-DETR on Jetson using DeepStream"], tmp_path
        )
        assert result.returncode == 0, result.stderr
        assert "Matched capabilities" in result.stdout
        assert "Matched skills" in result.stdout

    def test_resolve_command_with_no_discovered_skills_still_matches_capabilities(
        self, tmp_path: Path
    ) -> None:
        result = self._run(["resolve", "optimize deployment on jetson"], tmp_path)
        assert result.returncode == 0, result.stderr
        assert "Matched capabilities (0)" not in result.stdout
        assert "Matched skills (0)" in result.stdout

    def test_resolve_command_reports_missing_declared_skills(self, tmp_path: Path) -> None:
        result = self._run(
            ["resolve", "deploy optimization on jetson tensorrt"], tmp_path
        )
        assert result.returncode == 0, result.stderr
        assert "available=false" in result.stdout

    def test_analyze_command_produces_structured_output(self, tmp_path: Path) -> None:
        result = self._run(
            ["analyze", "I need to detect garment theft in a factory"], tmp_path
        )
        assert result.returncode == 0, result.stderr
        assert "Known fields" in result.stdout
        assert "Unknown fields" in result.stdout
        assert "Candidate CV task components" in result.stdout
        assert "Clarification questions" in result.stdout

    def test_analyze_command_does_not_execute_anything(self, tmp_path: Path) -> None:
        """No skill/tool execution surface exists; the CLI must not attempt
        one, and the fixture skill root must stay untouched by analyze."""
        self._write_skill(tmp_path, "fixture-skill", "A fake test skill.")
        before = sorted(p.name for p in tmp_path.rglob("*"))
        result = self._run(
            ["analyze", "deploy RT-DETR on Jetson using DeepStream"], tmp_path
        )
        after = sorted(p.name for p in tmp_path.rglob("*"))
        assert result.returncode == 0, result.stderr
        assert before == after

    def test_analyze_command_verbatim_echoes_request(self, tmp_path: Path) -> None:
        result = self._run(["analyze", "Detect theft in the warehouse."], tmp_path)
        assert result.returncode == 0, result.stderr
        assert "Detect theft in the warehouse." in result.stdout

    def test_analyze_command_surfaces_matched_skill_and_executable_status(
        self, tmp_path: Path
    ) -> None:
        """ADR-0008 §9: `analyze` must make the capability -> matched skill
        -> executable now/not chain visible, consistent with `resolve`'s
        own 'Matched skills' section format."""
        self._write_skill(
            tmp_path,
            "trt-perf-analysis",
            "TensorRT performance benchmarking and layer analysis tool.",
        )
        result = self._run(
            [
                "analyze",
                "Detect people and evaluate deployment optimization performance "
                "benchmarking of the model.",
            ],
            tmp_path,
        )
        assert result.returncode == 0, result.stderr
        assert "Matched skills" in result.stdout
        assert "trt-perf-analysis" in result.stdout
        assert "executable=False" in result.stdout

    def test_analyze_command_never_silently_registers_or_executes_a_skill(
        self, tmp_path: Path
    ) -> None:
        """A fresh, unregistered CVAgent per CLI invocation (same honesty
        default as `skills`/`resolve`/`executions`) — `analyze` must never
        report a skill as executable=True nor print any execution-result
        language, since it never registers a binding itself."""
        self._write_skill(
            tmp_path,
            "trt-perf-analysis",
            "TensorRT performance benchmarking and layer analysis tool.",
        )
        result = self._run(
            [
                "analyze",
                "Detect people and evaluate deployment optimization performance "
                "benchmarking of the model.",
            ],
            tmp_path,
        )
        assert result.returncode == 0, result.stderr
        assert "executable=True" not in result.stdout
        assert "Status: completed" not in result.stdout
        assert "Status: failed" not in result.stdout

    def test_executions_command_reports_zero_bindings_by_default(
        self, tmp_path: Path
    ) -> None:
        """No binding is registered anywhere in this codebase (ADR-0009 §5),
        so a fresh CVAgent must report zero runtimes and zero executable
        skills even when skills are discovered."""
        self._write_skill(tmp_path, "fixture-skill", "A fake test skill.")
        result = self._run(["executions"], tmp_path)
        assert result.returncode == 0, result.stderr
        assert "Registered runtimes: 0" in result.stdout
        assert "fixture-skill" in result.stdout
        assert "executable=False" in result.stdout
        assert "Executable: 0/1" in result.stdout

    def test_executions_command_does_not_execute_anything(self, tmp_path: Path) -> None:
        self._write_skill(tmp_path, "fixture-skill", "A fake test skill.")
        before = sorted(p.name for p in tmp_path.rglob("*"))
        result = self._run(["executions"], tmp_path)
        after = sorted(p.name for p in tmp_path.rglob("*"))
        assert result.returncode == 0, result.stderr
        assert before == after

    def test_workflow_command_declining_every_clarification_question_completes_cleanly(
        self, tmp_path: Path
    ) -> None:
        """No --answer supplied and no stdin available: every question falls
        back to a live prompt, gets EOF, and is left unanswered — never a
        fabricated placeholder (the pre-PR-#34 behavior this replaces).

        ADR-0003 §9 (Q21 fix): declining every question must resume with a
        single `clarify` interrupt, not loop indefinitely — `clarify` is
        resumed with `""` (never a literal `{}}`, which is not reliably
        delivered by the installed LangGraph — confirmed empirically) and
        `AgentState["clarification_attempted"]` lets the graph's own
        routing tell "attempted, declined everything" apart from "never
        attempted", so a second `clarify` interrupt is never raised. The
        run reaches a normal, non-error completion — never
        `WorkflowStuckError`/exit 3, which is now unreachable via this
        path (the safety cap that used to catch this remains only as
        defense-in-depth, see `_MAX_INTERRUPT_ROUNDS`'s docstring)."""
        result = self._run(
            ["workflow", "I have a prison project. Escape-attempt detection."], tmp_path
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.count("[INTERRUPT] clarification") == 1
        assert "[demo answer" not in result.stdout
        assert "[RESUME] clarification -> ''" in result.stdout
        assert "Final status: done" in result.stdout

    def test_workflow_command_answers_real_clarification_questions_via_flag(
        self, tmp_path: Path
    ) -> None:
        """A real, caller-supplied --answer is used verbatim and echoed as
        such — never silently dropped, never confused with a live prompt."""
        result = self._run(
            [
                "workflow",
                "I have a prison project. Escape-attempt detection.",
                "--answer",
                "deployment_target=jetson-orin",
                "--answer",
                "accuracy_requirement=recall above 95%",
            ],
            tmp_path,
        )
        assert result.returncode == 0, result.stderr
        assert "deployment_target -> 'jetson-orin' (from --answer)" in result.stdout
        assert "'deployment_target': 'jetson-orin'" in result.stdout
        assert "Assumed fields:" in result.stdout
        assert "deployment_target" in result.stdout.split("Assumed fields:")[1].split("\n")[0]

    def test_workflow_command_skips_interrupt_for_fully_specified_request(
        self, tmp_path: Path
    ) -> None:
        result = self._run(
            [
                "workflow",
                "Detect intruders using our 8 outdoor CCTV cameras at 1080p/15fps, "
                "deploy on a Jetson Orin, need real-time response with recall above 95%, "
                "and we have 2000 labeled clips already.",
            ],
            tmp_path,
        )
        assert result.returncode == 0, result.stderr
        assert "[INTERRUPT]" not in result.stdout
        assert "Final status: done" in result.stdout

    def test_resolve_command_does_not_trigger_execution(self, tmp_path: Path) -> None:
        """The resolve command must never invoke execution — 'Executable'
        or execution-status language must not leak into its output."""
        result = self._run(
            ["resolve", "deploy RT-DETR on Jetson using DeepStream"], tmp_path
        )
        assert result.returncode == 0, result.stderr
        assert "status=completed" not in result.stdout
        assert "status=failed" not in result.stdout
