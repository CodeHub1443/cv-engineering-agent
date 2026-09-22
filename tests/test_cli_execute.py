"""
Tests for the `cv_agent execute` CLI command (cv_agent.__main__) — the
application-layer path that closes requirements -> resolution -> execution
for one individually-verified skill (ADR-0009 §8/§10).

Four kinds of test, deliberately kept separate. Every class except (4) needs
no real skill installed and runs in any environment:

1. TestParseInputKv / TestConfirmApproval / TestApprovalPromptContext — pure
   unit tests of this command's own small helper functions, using
   fakes/mocks. These never touch a real skill, a subprocess, or even
   argparse — they test the command's plumbing, especially the
   approval-confirmation logic (which the real trt-perf-analysis binding's
   "allowed" policy never exercises, so it can only be verified against a
   fake "approval_required" binding).
2. TestExecuteCLIFixture — full CLI-as-subprocess tests against an
   isolated tmp_path skill root (never the real machine's skills) —
   covers the "unsupported/undiscovered skill is rejected" paths, which
   need no real binding at all.
3. TestExecuteCLIApprovalPath (issue #48) — `_cmd_execute`'s
   approval-required and unpinnable-binding branches, run in-process
   (never a subprocess — see the class's own docstring for why) against an
   isolated tmp_path skill root with a monkeypatched, approval_required
   fixture binding. No approval_required binding is ever registered for
   the real trt-perf-analysis skill.
4. TestExecuteCLIRealSkill — genuine CLI-as-subprocess invocation of the
   real, installed trt-perf-analysis skill's real script. Skipped (never
   faked) when the skill isn't discoverable in this environment, mirroring
   tests/test_execution_trt_perf_analysis.py's own convention. Its binding
   is always "allowed" (trt_perf_analysis.build_binding()'s documented
   default), so it never exercises (3)'s branches — that is exactly why
   (3) exists.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import cv_agent.execution.runtimes.trt_perf_analysis as trt_perf_analysis
from cv_agent.__main__ import _authorize_and_execute, _cmd_execute, _confirm_approval, _parse_input_kv
from cv_agent.execution.binding import ExecutionBinding, ExecutionBindingRegistry, InputField
from cv_agent.execution.models import RuntimeOutcome
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


class TestApprovalPromptContext:
    """Issue #47: the `execute` command's approval prompt shows the binding's
    runtime and description (the things the pinned approval is compared on),
    taken from the binding captured for that approval - never re-read."""

    @staticmethod
    def _described(description: str, runtime_id: str = "fixture-runtime") -> ExecutionBinding:
        return ExecutionBinding(
            skill_id=_SKILL_ID,
            binding_id="fixture-binding",
            runtime_id=runtime_id,
            approval_policy="approval_required",
            verified=True,
            description=description,
        )

    @staticmethod
    def _ask(binding: ExecutionBinding) -> str:
        seen: list[str] = []

        def prompt(msg: str) -> str:
            seen.append(msg)
            return "n"

        _confirm_approval(binding, approve_flag=False, prompt=prompt)
        assert len(seen) == 1  # asked exactly once
        return seen[0]

    def test_prompt_shows_skill_binding_runtime_policy_and_description(self) -> None:
        msg = self._ask(self._described("Layer-by-layer TensorRT timing analysis"))
        assert msg == (
            "Approval required for skill 'trt-perf-analysis' via binding 'fixture-binding' "
            "(runtime='fixture-runtime', policy=approval_required, "
            "description='Layer-by-layer TensorRT timing analysis'). "
            "Approve execution? [y/N]: "
        )

    @pytest.mark.parametrize("empty", ["", "   ", "\n\t "])
    def test_empty_or_blank_description_renders_as_no_description(self, empty: str) -> None:
        msg = self._ask(self._described(empty))
        assert msg == (
            "Approval required for skill 'trt-perf-analysis' via binding 'fixture-binding' "
            "(runtime='fixture-runtime', policy=approval_required, "
            "description=(no description)). Approve execution? [y/N]: "
        )
        assert "None" not in msg and "''" not in msg

    def test_multiline_description_stays_on_one_line(self) -> None:
        msg = self._ask(self._described("First line.\n  Second   line.\n"))
        assert "\n" not in msg
        assert "description='First line. Second line.'" in msg

    def test_approve_flag_still_never_prompts(self) -> None:
        def _fail_if_prompted(msg: str) -> str:
            raise AssertionError("--approve must not prompt")

        binding = self._described("anything")
        assert _confirm_approval(binding, approve_flag=True, prompt=_fail_if_prompted) is True

    def test_context_comes_from_the_captured_binding_not_a_second_registry_read(self) -> None:
        """`_authorize_and_execute` is handed the binding it shows; the registry
        holds a DIFFERENT description/runtime. The prompt must show the captured
        binding's values, and the display path must not call the registry's
        lookup accessors at all."""
        shown = self._described("the description that was captured", runtime_id="captured-rt")

        class _NoLookupRegistry(ExecutionBindingRegistry):
            def get_binding(self, skill_id: str):  # type: ignore[override]
                raise AssertionError("second registry read: get_binding")

            def get_runtime(self, runtime_id: str):  # type: ignore[override]
                raise AssertionError("second registry read: get_runtime")

            def get_runtime_registration(self, runtime_id: str):  # type: ignore[override]
                raise AssertionError("second registry read: get_runtime_registration")

        registry = _NoLookupRegistry()
        registry.register_binding(
            ExecutionBinding(
                skill_id=_SKILL_ID,
                binding_id="fixture-binding",
                runtime_id="registry-rt",
                approval_policy="approval_required",
                verified=True,
                description="a different description held by the registry",
            )
        )

        class _Agent:
            execution_bindings = registry

            def execute(self, skill: object, request: object) -> str:
                return "executed"

        prompts: list[str] = []

        def prompt(msg: str) -> str:
            prompts.append(msg)
            return "y"

        from cv_agent.skills.models import Skill

        skill = Skill(
            skill_id=_SKILL_ID, name=_SKILL_ID, description="d", source="fixture",
            location="/fixtures/trt-perf-analysis/SKILL.md",
        )
        result = _authorize_and_execute(
            _Agent(), skill, shown, inputs={}, task=None, approve_flag=False, prompt=prompt
        )

        assert result == "executed"
        assert len(prompts) == 1
        assert "runtime='captured-rt'" in prompts[0]
        assert "description='the description that was captured'" in prompts[0]
        assert "registry-rt" not in prompts[0] and "different description" not in prompts[0]


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


class _FakeRuntime:
    """Minimal fake ExecutionRuntime for TestExecuteCLIApprovalPath — never
    touches a real subprocess, records every invocation."""

    def __init__(self, runtime_id: str = "fixture-runtime") -> None:
        self.runtime_id = runtime_id
        self.calls: list[str] = []
        self.outcome = RuntimeOutcome(success=True, output={"ok": True})

    def invoke(self, skill: Any, request: Any) -> RuntimeOutcome:
        self.calls.append(skill.skill_id)
        return self.outcome


class TestExecuteCLIApprovalPath:
    """
    Issue #48: `_cmd_execute`'s approval-required and unpinnable-binding
    branches. Neither TestExecuteCLIFixture (never registers an
    approval_required binding) nor TestExecuteCLIRealSkill (the real
    trt-perf-analysis binding's policy is "allowed" — see
    trt_perf_analysis.build_binding()'s own docstring) can reach them.

    Runs `_cmd_execute` directly, in-process — never as a subprocess.
    `_cmd_execute` always resolves `trt_perf_analysis.register` via a lazy
    import evaluated at CALL time, so only an in-process monkeypatch can
    substitute an approval_required binding; a subprocess would re-import
    the real, unpatched module and always get the real "allowed" binding.
    Prompt answers are supplied through `_cmd_execute`'s injectable `prompt`
    parameter (issue #48) — `_authorize_and_execute`'s own `prompt` default
    is bound to the real `input` builtin once, at import time, so it cannot
    be overridden by monkeypatching `builtins.input` after the fact.

    No approval_required binding is ever registered for the REAL
    trt-perf-analysis skill; skill discovery here is confined to an
    isolated `tmp_path` root via `CV_AGENT_SKILL_PATHS`, never the real
    machine's skills — these tests need no real skill installed.
    """

    @staticmethod
    def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CV_AGENT_SKILL_PATHS", str(tmp_path))
        skill_dir = tmp_path / _SKILL_ID
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {_SKILL_ID}\ndescription: fixture approval skill.\n---\nbody\n",
            encoding="utf-8",
        )

    @staticmethod
    def _register(
        monkeypatch: pytest.MonkeyPatch, *, unpinnable: bool = False
    ) -> tuple[_FakeRuntime, dict[str, ExecutionBindingRegistry]]:
        """Monkeypatches `trt_perf_analysis.register` (the name `_cmd_execute`
        lazily imports) to install an `approval_required` fixture binding
        instead of the real, `"allowed"`-policy one. `box["registry"]` lets a
        test reach the exact `ExecutionBindingRegistry` instance `_cmd_execute`
        built internally, e.g. to mutate it from inside a prompt callback —
        populated before `_cmd_execute` ever prompts, since registration
        happens first."""
        runtime = _FakeRuntime()
        box: dict[str, ExecutionBindingRegistry] = {}
        schema = (
            (InputField(name="x", required=False, description="", default=float("nan")),)
            if unpinnable
            else ()
        )

        def fake_register(registry: ExecutionBindingRegistry) -> None:
            box["registry"] = registry
            registry.register_runtime(runtime)
            registry.register_binding(
                ExecutionBinding(
                    skill_id=_SKILL_ID,
                    binding_id="fixture-approval-binding",
                    runtime_id=runtime.runtime_id,
                    approval_policy="approval_required",
                    verified=True,
                    description="fixture approval-required binding for issue #48",
                    input_schema=schema,
                )
            )

        monkeypatch.setattr(trt_perf_analysis, "register", fake_register)
        return runtime, box

    @staticmethod
    def _fail_if_prompted(msg: str) -> str:
        raise AssertionError("must not prompt")

    @staticmethod
    def _run(tmp_path: Path, *, approve: bool, prompt: Any) -> int:
        return _cmd_execute(
            _SKILL_ID,
            path=str(tmp_path),
            input_kv=[],
            model_name=None,
            task=None,
            approve=approve,
            prompt=prompt,
        )

    def test_declined_live_answer_never_runs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._env(monkeypatch, tmp_path)
        runtime, _box = self._register(monkeypatch)

        code = self._run(tmp_path, approve=False, prompt=lambda msg: "n")

        assert code == 3
        assert capsys.readouterr().err.strip() == (
            "Execution not approved — aborting. Nothing was run."
        )
        assert runtime.calls == []

    def test_declined_via_eof_never_runs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._env(monkeypatch, tmp_path)
        runtime, _box = self._register(monkeypatch)

        def eof_prompt(msg: str) -> str:
            raise EOFError

        code = self._run(tmp_path, approve=False, prompt=eof_prompt)

        assert code == 3
        assert runtime.calls == []

    def test_approved_live_answer_runs_once(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._env(monkeypatch, tmp_path)
        runtime, _box = self._register(monkeypatch)

        code = self._run(tmp_path, approve=False, prompt=lambda msg: "y")

        assert code == 0
        assert "Status: completed" in capsys.readouterr().out
        assert runtime.calls == [_SKILL_ID]

    def test_approve_flag_never_prompts_and_runs_once(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._env(monkeypatch, tmp_path)
        runtime, _box = self._register(monkeypatch)

        code = self._run(tmp_path, approve=True, prompt=self._fail_if_prompted)

        assert code == 0
        assert "Status: completed" in capsys.readouterr().out
        assert runtime.calls == [_SKILL_ID]

    def test_registry_mutation_during_the_prompt_fails_closed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Mirrors tests/test_approval_integrity.py's T18, but through
        `_cmd_execute` itself, not `_authorize_and_execute` directly."""
        self._env(monkeypatch, tmp_path)
        runtime, box = self._register(monkeypatch)
        replacement = _FakeRuntime(runtime_id="replacement-runtime")

        def mutate_then_approve(msg: str) -> str:
            registry = box["registry"]
            registry.register_runtime(replacement)
            registry.register_binding(
                ExecutionBinding(
                    skill_id=_SKILL_ID,
                    binding_id="fixture-approval-binding",
                    runtime_id=replacement.runtime_id,
                    approval_policy="approval_required",
                    verified=True,
                    description="fixture approval-required binding for issue #48",
                )
            )
            return "y"

        code = self._run(tmp_path, approve=False, prompt=mutate_then_approve)

        assert code == 1
        err = capsys.readouterr().err
        assert "binding_mismatch" in err
        assert "binding.runtime_id" in err
        assert runtime.calls == [] and replacement.calls == []

    def test_unpinnable_binding_fails_before_any_prompt(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._env(monkeypatch, tmp_path)
        runtime, _box = self._register(monkeypatch, unpinnable=True)

        code = self._run(tmp_path, approve=False, prompt=self._fail_if_prompted)

        assert code == 2
        err = capsys.readouterr().err
        assert err.startswith("Binding 'fixture-approval-binding' cannot be pinned:")
        assert runtime.calls == []


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
