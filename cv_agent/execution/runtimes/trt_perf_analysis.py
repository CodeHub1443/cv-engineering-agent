"""
cv_agent.execution.runtimes.trt_perf_analysis — ExecutionRuntime adapter for
the real, installed `trt-perf-analysis` skill (ADR-0009 §8 revisit trigger).

Why this skill, verified by direct inspection of the real installed skill
directory (`~/.agents/skills/trt-perf-analysis` / `~/.claude/skills/
trt-perf-analysis`) — not assumed from ADR-0009's own prior mention of it:

- `scripts/analyze_trt_perf.py`'s own module docstring states it
  "intentionally uses only Python built-in modules so it can run in minimal
  benchmark environments" — confirmed by reading it: no third-party imports,
  no network access, no GPU, no subprocess of its own, no writes unless the
  caller passes `--output` (this adapter never does).
- It has a stable, machine-readable CLI contract (`argparse`: a positional
  `path`, or repeated `--data LAYER [PROFILE]`, optional `--model-name`) —
  not prose a human/LLM has to interpret to know what to run.
- Exit-code/stdout contract verified empirically against the real script,
  not assumed from reading alone: `0` with one structured JSON object on
  stdout when it can produce structured data at all — including when a
  backend's *own* data fails validation, which the script itself treats as
  a valid, informative outcome, not a crash; `2` with a one-line
  `error: ...` message on stderr when it cannot process the input at all
  (e.g. no `layers_*.json`/`profile_*.json` present, unreadable JSON).
- It is read-only and side-effect-free by construction as this adapter
  drives it (never passing `--output`; the result is always read from
  stdout) — no destructive, expensive, or irreversible action, so it needs
  no approval gate per `docs/APPROVALS.md` / `CLAUDE.md` §3 rule 10.

What this adapter does NOT claim:
- It does not make any other skill executable — `verified=True` is set for
  exactly this one `ExecutionBinding` (ADR-0009 §8: "for one skill, not all
  of them at once").
- It does not implement `docs/APPROVALS.md`'s actual approval workflow —
  irrelevant here, since this runtime's default binding never requires it.
- It never modifies, moves, or copies anything under the skill's installed
  directory — it only reads whatever files the caller names in
  `SkillExecutionRequest.inputs` and runs the skill's own, unmodified
  script as a subprocess.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from cv_agent.execution.binding import (
    ExecutionBinding,
    ExecutionBindingRegistry,
    InputField,
    RequiredFieldGroup,
)
from cv_agent.execution.models import ApprovalPolicy, RuntimeOutcome, SkillExecutionRequest
from cv_agent.skills.models import Skill

RUNTIME_ID = "trt-perf-analysis-local-subprocess"
BINDING_ID = "trt-perf-analysis-local-subprocess-v1"
DEFAULT_SKILL_ID = "trt-perf-analysis"
DEFAULT_TIMEOUT_SECONDS = 30.0

_SCRIPT_RELATIVE_PATH = Path("scripts") / "analyze_trt_perf.py"


class TrtPerfAnalysisRuntime:
    """
    Runs the real, installed trt-perf-analysis skill's
    `scripts/analyze_trt_perf.py` as a subprocess against whichever skill
    instance is passed to `invoke()` — the script location is derived from
    `Skill.location` (the real, discovered `SKILL.md` path), never a
    hard-coded filesystem path, so this adapter follows wherever the real
    environment actually installed the skill.

    Invokes the script directly with this process's own interpreter
    (`sys.executable`, or the `SKILL_PYTHON` environment variable if set —
    the same override the skill's own `scripts/run.sh`/`run.cmd` wrappers
    honor per their own source) rather than shelling through those wrapper
    scripts: this process already knows which Python it is running under,
    so the wrappers' PATH-based discovery (built for a human/agent
    following SKILL.md's prose from a raw shell) is unnecessary here. The
    script file that actually runs is byte-identical to what the wrapper
    would have invoked — this is the real skill script, not a copy.
    """

    runtime_id: str = RUNTIME_ID

    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    def invoke(self, skill: Skill, request: SkillExecutionRequest) -> RuntimeOutcome:
        script_path = self._resolve_script_path(skill)
        if script_path is None:
            return RuntimeOutcome(
                success=False,
                error_message=(
                    f"scripts/analyze_trt_perf.py not found next to {skill.location} "
                    "— the installed skill does not match the expected layout."
                ),
            )

        try:
            argv = self._build_argv(script_path, request.inputs)
        except ValueError as exc:
            return RuntimeOutcome(success=False, error_message=str(exc))

        python = os.environ.get("SKILL_PYTHON") or sys.executable
        try:
            result = subprocess.run(
                [python, *argv],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self._timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return RuntimeOutcome(
                success=False,
                error_message=f"trt-perf-analysis timed out after {self._timeout_seconds}s.",
            )
        except OSError as exc:
            return RuntimeOutcome(success=False, error_message=f"Unable to launch Python: {exc}")

        if result.returncode != 0:
            message = (result.stderr or "").strip() or f"exit code {result.returncode}"
            return RuntimeOutcome(success=False, error_message=message)

        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return RuntimeOutcome(
                success=False,
                error_message=f"trt-perf-analysis produced non-JSON stdout: {exc}",
            )

        if not isinstance(output, dict):
            return RuntimeOutcome(
                success=False,
                error_message="trt-perf-analysis produced a JSON value that is not an object.",
            )

        return RuntimeOutcome(success=True, output=output)

    @staticmethod
    def _resolve_script_path(skill: Skill) -> Path | None:
        skill_root = Path(skill.location).parent
        script_path = skill_root / _SCRIPT_RELATIVE_PATH
        return script_path if script_path.is_file() else None

    @staticmethod
    def _build_argv(script_path: Path, inputs: dict[str, Any]) -> list[str]:
        """
        Translates `SkillExecutionRequest.inputs` into
        `analyze_trt_perf.py`'s real argv contract (verified against
        `scripts/analyze_trt_perf.py::parse_args`). Exactly one of
        `"path"`/`"data"` is required:

            {"path": "<folder containing layers_*.json/profile_*.json>"}
            {"data": [["<layers.json>"], ["<layers.json>", "<profile.json>"]]}

        Optional: `{"model_name": "<str>"}` -> `--model-name`. `--output` is
        never forwarded — this adapter always reads the result from stdout,
        so invocation stays read-only regardless of caller input. All file
        paths are resolved to absolute paths here (not left to the
        subprocess's inherited cwd), so the same `inputs` dict behaves
        identically regardless of where this process happens to be running
        from — part of keeping the contract deterministic.
        """
        path = inputs.get("path")
        data_specs = inputs.get("data")
        if path is not None and data_specs is not None:
            raise ValueError("Provide exactly one of 'path' or 'data' inputs, not both.")
        if path is None and data_specs is None:
            raise ValueError(
                "trt-perf-analysis requires either an inputs['path'] folder or "
                "an inputs['data'] list of [layer_json, profile_json?] specs."
            )

        argv: list[str] = [str(script_path)]
        if path is not None:
            argv.append(str(Path(path).resolve()))
        else:
            if not isinstance(data_specs, list) or not data_specs:
                raise ValueError("inputs['data'] must be a non-empty list of path lists.")
            for spec in data_specs:
                if not isinstance(spec, (list, tuple)) or not spec:
                    raise ValueError(
                        "Each inputs['data'] entry must be a non-empty list of paths."
                    )
                argv.append("--data")
                argv.extend(str(Path(p).resolve()) for p in spec)

        model_name = inputs.get("model_name")
        if model_name is not None:
            argv.extend(["--model-name", str(model_name)])

        return argv


def build_binding(
    skill_id: str = DEFAULT_SKILL_ID,
    *,
    approval_policy: ApprovalPolicy = "allowed",
) -> ExecutionBinding:
    """
    The one real ExecutionBinding this module ships (ADR-0009 §8). Read-only,
    local, deterministic, Python-stdlib-only analysis needs no approval gate
    per `CLAUDE.md` §3 rule 10 — `"allowed"` is the honest default here, not
    a shortcut around the approval mechanism. A caller that wants to
    exercise the approval-gate path against this same runtime may pass
    `approval_policy="approval_required"` explicitly (see
    `tests/test_execution_trt_perf_analysis.py`) without that changing this
    module's own recommended default.

    `input_schema`/`input_field_groups` (ADR-0009 §11/§12, resolving
    `docs/state/OPEN_QUESTIONS.md` Q20) declare the real contract verified
    directly against `_build_argv()`: `path`/`data` are each `required=False`
    individually (neither is unconditionally required) but grouped as
    `"exactly_one"` — a flat `required=True` on either would have
    misrepresented the contract, and this is the first binding to actually
    populate this field (ADR-0009 §11 left it `()` pending this decision).
    `model_name` is genuinely optional, no group. Presence of `path` or
    `data` (not both) is all `plan_execution()` checks (ADR-0010 §3/§14) —
    `_build_argv()` itself remains the authoritative enforcement that
    exactly one, not both, was actually given.
    """
    return ExecutionBinding(
        skill_id=skill_id,
        binding_id=BINDING_ID,
        runtime_id=RUNTIME_ID,
        approval_policy=approval_policy,
        verified=True,
        description=(
            "Real subprocess invocation of the installed trt-perf-analysis "
            "skill's scripts/analyze_trt_perf.py — validates and analyzes "
            "TensorRT layer/profile JSON, Python-stdlib only, read-only, "
            "local, deterministic. See ADR-0009 §8."
        ),
        input_schema=(
            InputField(
                name="path",
                required=False,
                description="Folder containing layers_*.json/profile_*.json files to analyze.",
            ),
            InputField(
                name="data",
                required=False,
                description=(
                    "List of [layer_json_path, profile_json_path?] path lists, "
                    "one per backend."
                ),
            ),
            InputField(
                name="model_name",
                required=False,
                description="Optional model name label, forwarded as --model-name.",
            ),
        ),
        input_field_groups=(
            RequiredFieldGroup(
                kind="exactly_one",
                field_names=("path", "data"),
                description=(
                    "Exactly one of path/data is required — see "
                    "TrtPerfAnalysisRuntime._build_argv()."
                ),
            ),
        ),
    )


def register(
    registry: ExecutionBindingRegistry,
    *,
    skill_id: str = DEFAULT_SKILL_ID,
    approval_policy: ApprovalPolicy = "allowed",
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """
    Explicit, opt-in wiring — never called automatically by
    `CVAgent.__init__`. ADR-0009 §3's "no binding registered anywhere in
    this codebase by default" stays true for a fresh `CVAgent`; a caller
    that has actually discovered this skill in *its own* environment
    registers it deliberately:

        from cv_agent.execution.runtimes.trt_perf_analysis import register
        register(agent.execution_bindings)

    before calling `agent.execute(...)` — mirroring exactly how ADR-0009 §6
    describes a future, individually-verified adapter plugging in: "it just
    calls register_binding() + register_runtime()," nothing more.
    """
    registry.register_runtime(TrtPerfAnalysisRuntime(timeout_seconds=timeout_seconds))
    registry.register_binding(build_binding(skill_id, approval_policy=approval_policy))
