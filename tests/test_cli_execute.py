"""
Tests for the `cv_agent execute` CLI command (cv_agent.__main__) — the
application-layer path that closes requirements -> resolution -> execution
for one individually-verified skill (ADR-0009 §8/§10).

Three kinds of test, deliberately kept separate:

1. TestParseInputKv / TestConfirmApproval — pure unit tests of this
   command's own small helper functions, using fakes/mocks. These never
   touch a real skill, a subprocess, or even argparse — they test the
   command's plumbing, especially the approval-confirmation logic (which
   the real trt-perf-analysis binding's "allowed" policy never exercises,
   so it can only be verified against a fake "approval_required" binding).
2. TestExecuteCLIFixture — full CLI-as-subprocess tests against an
   isolated tmp_path skill root (never the real machine's skills) —
   covers the "unsupported/undiscovered skill is rejected" paths, which
   need no real binding at all.
3. TestExecuteCLIRealSkill — genuine CLI-as-subprocess invocation of the
   real, installed trt-perf-analysis skill's real script. Skipped (never
   faked) when the skill isn't discoverable in this environment, mirroring
   tests/test_execution_trt_perf_analysis.py's own convention.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cv_agent.__main__ import _confirm_approval, _parse_input_kv
from cv_agent.execution.binding import ExecutionBinding
from cv_agent.skills.local import LocalSkillSource

_SKILL_ID = "trt-perf-analysis"


def _discover_real_skill() -> bool:
    return any(s.skill_id == _SKILL_ID for s in LocalSkillSource().discover())


requires_real_skill = pytest.mark.skipif(
    not _discover_real_skill(),
    reason="trt-perf-analysis is not installed under ~/.claude/skills or "
    "~/.agents/skills on this machine — real CLI execution tests are "
    "skipped, not faked.",
)


def _binding(approval_policy: str) -> ExecutionBinding:
    return ExecutionBinding(
        skill_id=_SKILL_ID,
        binding_id="fixture-binding",
        runtime_id="fixture-runtime",
        approval_policy=approval_policy,  # type: ignore[arg-type]
        verified=True,
    )


class TestParseInputKv:
    def test_parses_simple_pairs(self) -> None:
        assert _parse_input_kv(["a=1", "b=2"]) == {"a": "1", "b": "2"}

    def test_empty_list_produces_empty_dict(self) -> None:
        assert _parse_input_kv([]) == {}

    def test_value_may_itself_contain_equals(self) -> None:
        assert _parse_input_kv(["path=C:/x=y"]) == {"path": "C:/x=y"}

    def test_missing_equals_raises(self) -> None:
        with pytest.raises(ValueError, match="KEY=VALUE"):
            _parse_input_kv(["not-a-pair"])

    def test_empty_key_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty key"):
            _parse_input_kv(["=value"])


class TestConfirmApproval:
    """Item 8/9/10 of the task's required CLI test coverage — exercised
    against a fake approval_required binding, since the shipped
    trt-perf-analysis binding's own policy is 'allowed' and can never
    exercise this path itself."""

    def test_allowed_policy_needs_no_confirmation(self) -> None:
        binding = _binding("allowed")
        called = False

        def _prompt(msg: str) -> str:
            nonlocal called
            called = True
            return "yes"

        assert _confirm_approval(binding, approve_flag=False, prompt=_prompt) is True
        assert called is False  # never prompted — nothing to confirm

    def test_approval_required_without_approve_flag_and_no_answer_is_not_approved(
        self,
    ) -> None:
        """Item 8: cannot execute without explicit approval — a blank/'no'
        answer at the live prompt must not approve."""
        binding = _binding("approval_required")
        assert (
            _confirm_approval(binding, approve_flag=False, prompt=lambda msg: "") is False
        )
        assert (
            _confirm_approval(binding, approve_flag=False, prompt=lambda msg: "no")
            is False
        )

    def test_approval_required_with_explicit_approve_flag_is_approved(self) -> None:
        """Item 9: explicit --approve grants approval without needing a
        live prompt at all."""
        binding = _binding("approval_required")

        def _fail_if_prompted(msg: str) -> str:
            raise AssertionError("must not prompt when --approve was already given")

        assert (
            _confirm_approval(binding, approve_flag=True, prompt=_fail_if_prompted) is True
        )

    def test_approval_required_with_live_yes_answer_is_approved(self) -> None:
        """Item 9 (interactive path): a real 'yes'/'y' answer at the prompt
        also grants approval."""
        binding = _binding("approval_required")
        assert _confirm_approval(binding, approve_flag=False, prompt=lambda msg: "yes") is True
        assert _confirm_approval(binding, approve_flag=False, prompt=lambda msg: "y") is True
        assert _confirm_approval(binding, approve_flag=False, prompt=lambda msg: "Y") is True

    def test_no_auto_approval_ever_occurs_by_default(self) -> None:
        """Item 10: constructing the request with no flag and no answer
        (EOF — the exact condition a non-interactive/piped invocation with
        no --approve hits) must never silently approve."""
        binding = _binding("approval_required")

        def _eof(msg: str) -> str:
            raise EOFError

        assert _confirm_approval(binding, approve_flag=False, prompt=_eof) is False

    def test_rejected_policy_is_unaffected_by_this_function(self) -> None:
        """SkillExecutor itself unconditionally rejects a 'rejected'
        binding regardless of `approved` — this function's return value is
        never consulted for that policy, so it should not attempt to
        prompt for it either."""
        binding = _binding("rejected")
        called = False

        def _prompt(msg: str) -> str:
            nonlocal called
            called = True
            return "yes"

        _confirm_approval(binding, approve_flag=False, prompt=_prompt)
        assert called is False


class TestExecuteCLIFixture:
    """Subprocess CLI tests against an isolated, fake skill root — never
    the real machine's skills. Covers the paths that need no real binding."""

    def _run(self, args: list[str], skill_root: Path) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["CV_AGENT_SKILL_PATHS"] = str(skill_root)
        return subprocess.run(
            [sys.executable, "-m", "cv_agent", *args],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            cwd=str(skill_root),
        )

    def _write_skill(self, root: Path, skill_id: str) -> None:
        skill_dir = root / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {skill_id}\ndescription: fixture skill.\n---\nbody\n",
            encoding="utf-8",
        )

    def test_unsupported_skill_id_is_rejected_without_attempting_execution(
        self, tmp_path: Path
    ) -> None:
        """Item 7: an unknown/non-executable skill is rejected — covers a
        skill this CLI simply does not support (no dispatch table exists
        for it at all), which is also true of any skill this environment
        never discovered."""
        result = self._run(["execute", "not-a-real-skill", "--path", str(tmp_path)], tmp_path)
        assert result.returncode == 2
        assert "no supported real execution path" in result.stderr.lower()

    def test_trt_perf_analysis_not_discovered_in_isolated_fixture_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """Even for the one supported skill_id, an isolated environment
        that never discovered it must refuse, not fabricate a result."""
        result = self._run(["execute", _SKILL_ID, "--path", str(tmp_path)], tmp_path)
        assert result.returncode == 2
        assert "not discovered" in result.stderr.lower()

    def test_execute_does_not_touch_the_fixture_skill_root(self, tmp_path: Path) -> None:
        self._write_skill(tmp_path, "some-other-skill")
        before = sorted(p.name for p in tmp_path.rglob("*"))
        self._run(["execute", "some-other-skill", "--path", str(tmp_path)], tmp_path)
        after = sorted(p.name for p in tmp_path.rglob("*"))
        assert before == after


class TestExecuteCLIRealSkill:
    """Genuine end-to-end CLI invocation of the real, installed
    trt-perf-analysis skill. Not faked — skipped entirely when the skill
    isn't present on the machine running the suite."""

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "cv_agent", *args],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def _write_valid_layers_fixture(self, folder: Path) -> None:
        layers = [
            {
                "Name": "conv1",
                "LayerType": "Convolution",
                "Inputs": [
                    {"Name": "input", "Dimensions": [1, 3, 224, 224], "Format/Datatype": "Float"}
                ],
                "Outputs": [
                    {
                        "Name": "conv1_out",
                        "Dimensions": [1, 64, 112, 112],
                        "Format/Datatype": "Float",
                    }
                ],
            },
            {
                "Name": "relu1",
                "LayerType": "Activation",
                "Inputs": [
                    {
                        "Name": "conv1_out",
                        "Dimensions": [1, 64, 112, 112],
                        "Format/Datatype": "Float",
                    }
                ],
                "Outputs": [
                    {
                        "Name": "relu1_out",
                        "Dimensions": [1, 64, 112, 112],
                        "Format/Datatype": "Float",
                    }
                ],
            },
            {
                "Name": "conv2",
                "LayerType": "Convolution",
                "Inputs": [
                    {
                        "Name": "relu1_out",
                        "Dimensions": [1, 64, 112, 112],
                        "Format/Datatype": "Float",
                    }
                ],
                "Outputs": [
                    {"Name": "output", "Dimensions": [1, 128, 56, 56], "Format/Datatype": "Float"}
                ],
            },
        ]
        (folder / "layers_smoke.json").write_text(json.dumps(layers), encoding="utf-8")

    @requires_real_skill
    def test_real_successful_execution_end_to_end(self, tmp_path: Path) -> None:
        """Items 1-5: skill is selected, a valid request is constructed,
        execution goes through SkillExecutor to the real binding/runtime,
        and the real result is surfaced on stdout."""
        self._write_valid_layers_fixture(tmp_path)
        result = self._run(["execute", _SKILL_ID, "--path", str(tmp_path)])

        assert result.returncode == 0, result.stderr
        assert "Status: completed" in result.stdout
        assert "Binding: trt-perf-analysis-local-subprocess-v1" in result.stdout
        assert "Runtime: trt-perf-analysis-local-subprocess" in result.stdout

        result_start = result.stdout.index("Result:") + len("Result:")
        output = json.loads(result.stdout[result_start:])
        assert output["schema_version"] == "1.0"
        assert output["validation"]["status"] == "passed"
        assert output["results"][0]["layer_count"] == 3

    @requires_real_skill
    def test_real_malformed_input_produces_a_useful_error(self, tmp_path: Path) -> None:
        """Item 6: an empty folder (no layers_*.json/profile_*.json) hits
        the real script's own documented failure path — a clear,
        non-fabricated error, not a crash or a fake success."""
        result = self._run(["execute", _SKILL_ID, "--path", str(tmp_path)])

        assert result.returncode == 1
        assert "Status: failed" in result.stdout
        assert "Error [runtime_error]" in result.stderr
        assert "layers" in result.stderr.lower()

    @requires_real_skill
    def test_real_execution_does_not_require_approval_prompt(self, tmp_path: Path) -> None:
        """trt-perf-analysis's shipped binding is approval_policy='allowed'
        — the CLI must not print an approval prompt for it."""
        self._write_valid_layers_fixture(tmp_path)
        result = self._run(["execute", _SKILL_ID, "--path", str(tmp_path)])

        assert "Approval required" not in result.stdout
        assert "Approve execution" not in result.stdout
