"""
cv_agent.__main__ — CLI entrypoint.

Usage:
    python -m cv_agent                     health check (default)
    python -m cv_agent skills              show actually discovered skills
    python -m cv_agent capabilities        show declared capabilities + status
    python -m cv_agent resolve "<task>"    deterministic task -> capability -> skill
    python -m cv_agent analyze "<request>" requirements analysis + task decomposition
    python -m cv_agent executions          show execution bindings/runtimes + what's executable
    python -m cv_agent execute <skill_id>  run a verified skill through the real execution path
    python -m cv_agent workflow "<task>"   requirements clarification / approval /
                                            execution-input recovery, with real answers
                                            (--answer, --input, --approve/--reject, or
                                            interactive stdin — never a fabricated one)
    cv-agent ...                           (when installed via pip)
"""

from __future__ import annotations

import sys
import uuid
from argparse import ArgumentParser
from typing import Any, Callable


def _health_check() -> int:
    from cv_agent.runtime.agent import CVAgent

    try:
        agent = CVAgent()
        health = agent.health_check()
    except Exception as exc:  # noqa: BLE001
        print(f"CV Engineering Agent — STARTUP FAILURE\n  {exc}", file=sys.stderr)
        return 2

    lg_label = (
        f"available (v{health['langgraph_version']})"
        if health["langgraph_available"]
        else "UNAVAILABLE"
    )

    print("CV Engineering Agent — Health Check")
    print(f"  Runtime status  : {health['status'].upper()}")
    print(f"  Provider        : {health['provider']}")
    print(f"  Model           : {health['model']}")
    print(f"  Capabilities    : {health['capability_count']} registered")
    print(f"  LangGraph       : {lg_label}")

    return 0 if health["status"] == "ok" else 1


def _cmd_skills() -> int:
    from cv_agent.runtime.agent import CVAgent

    agent = CVAgent()
    discovered = agent.skills.list()
    roots = [str(root) for source in agent.skills.sources for root in getattr(source, "roots", ())]

    print(f"Discovered skills: {len(discovered)}")
    if not discovered:
        print("  (none found — scanned roots:)")
        for root in roots:
            print(f"    - {root}")
    for skill in discovered:
        print(f"  - {skill.skill_id:<32} {skill.name}")
        print(f"      source={skill.source}  discovered=True  executable={skill.executable}")
        print(f"      location: {skill.location}")
        if skill.tags:
            print(f"      tags: {', '.join(skill.tags)}")
    return 0


def _cmd_capabilities() -> int:
    from cv_agent.runtime.agent import CVAgent

    agent = CVAgent()
    caps = agent.registry.list()

    print(f"Declared capabilities: {len(caps)}")
    for cap in caps:
        executable = "executable" if cap.is_available else "not executable"
        print(f"  - {cap.id:<32} status={cap.status:<12} ({executable})")
    return 0


def _cmd_resolve(task: str) -> int:
    from cv_agent.runtime.agent import CVAgent

    agent = CVAgent()
    result = agent.resolve(task)

    print(f'Task: "{result.task}"')
    print()
    print(f"Matched capabilities ({len(result.matched_capabilities)}):")
    for cap in result.matched_capabilities:
        print(
            f"  - {cap.capability_id:<32} score={cap.score:g}  "
            f"status={cap.status}  matched={list(cap.matched_terms)}"
        )

    print()
    print(f"Matched skills ({len(result.matched_skills)}):")
    for skill in result.matched_skills:
        via = "declared" if skill.declared else "keyword"
        print(
            f"  - {skill.skill_id:<32} score={skill.score:g}  via={via}  "
            f"discovered=True  executable={skill.executable}"
        )

    if result.missing_skills:
        print()
        print(f"Declared-but-not-discovered skills ({len(result.missing_skills)}):")
        for skill_id in result.missing_skills:
            print(f"  - {skill_id}  (available=false)")

    if result.evidence:
        print()
        print("Evidence:")
        for line in result.evidence:
            print(f"  - {line}")

    if result.warnings:
        print()
        print("Warnings:")
        for line in result.warnings:
            print(f"  - {line}")

    return 0


def _cmd_analyze(request: str) -> int:
    from cv_agent.runtime.agent import CVAgent

    agent = CVAgent()
    analysis = agent.analyze_requirements(request)

    print(analysis.problem_statement)
    print()

    print(f"Known fields ({len(analysis.known_field_names)}):")
    for f in analysis.fields:
        if f.status == "known":
            print(f"  - {f.name:<24} {f.value}")

    print()
    print(f"Unknown fields ({len(analysis.unknown_field_names)}):")
    for f in analysis.fields:
        if f.status == "unknown":
            print(f"  - {f.name}")

    if analysis.assumed_field_names:
        print()
        print(f"Assumed fields ({len(analysis.assumed_field_names)}):")
        for f in analysis.fields:
            if f.status == "assumed":
                print(f"  - {f.name:<24} {f.value}  (caller-supplied assumption)")

    print()
    print(f"Candidate CV task components ({len(analysis.candidate_tasks)}):")
    for t in analysis.candidate_tasks:
        print(f"  - {t.task_component:<24} confidence={t.confidence:g}")
        print(f"      rationale: {t.rationale}")

    print()
    print(f"Capability links ({len(analysis.capability_links)}):")
    for link in analysis.capability_links:
        print(
            f"  - {link.task_component:<24} -> {link.capability_id:<28} "
            f"status={link.status}"
        )

    print()
    print(f"Matched skills ({len(analysis.skill_links)}):")
    for skill_link in analysis.skill_links:
        via = "declared" if skill_link.declared else "keyword"
        print(
            f"  - {skill_link.task_component:<24} -> {skill_link.skill_id:<28} "
            f"via={via}  executable={skill_link.executable}"
        )

    if analysis.clarification_questions:
        print()
        print(f"Clarification questions ({len(analysis.clarification_questions)}):")
        for q in analysis.clarification_questions:
            print(f"  - {q.question}")
            print(f"      why it matters: {q.why_it_matters}")

    if analysis.constraints:
        print()
        print("Constraints:")
        for c in analysis.constraints:
            print(f"  - {c}")

    if analysis.risks:
        print()
        print("Risks:")
        for r in analysis.risks:
            print(f"  - {r}")

    if analysis.narrative_summary:
        print()
        print(f"Narrative summary (llm_provider={analysis.llm_provider}):")
        print(f"  {analysis.narrative_summary}")

    return 0


def _cmd_executions() -> int:
    from cv_agent.runtime.agent import CVAgent

    agent = CVAgent()
    discovered = agent.skills.list()
    bindings = {b.skill_id: b for b in agent.execution_bindings.list_bindings()}
    runtimes = agent.execution_bindings.list_runtimes()

    print(f"Discovered skills: {len(discovered)}")
    print(f"Registered runtimes: {len(runtimes)}")
    for rt in runtimes:
        print(f"  - {rt.runtime_id}")

    print()
    executable_count = 0
    for skill in discovered:
        binding = bindings.get(skill.skill_id)
        if binding is None:
            print(f"  - {skill.skill_id:<32} executable=False  (no binding)")
            continue
        can_run = agent.can_execute(skill.skill_id)
        if can_run:
            executable_count += 1
        print(
            f"  - {skill.skill_id:<32} executable={can_run}  "
            f"binding={binding.binding_id}  runtime={binding.runtime_id}  "
            f"verified={binding.verified}  approval={binding.approval_policy}"
        )

    print()
    print(f"Executable: {executable_count}/{len(discovered)}")
    return 0


# ── execute: the real application-layer execution path (closes the
# requirements -> resolution -> execution loop for one individually-
# verified skill; see ADR-0009 §8/§10) ──────────────────────────────────

_SUPPORTED_EXECUTE_SKILL_ID = "trt-perf-analysis"
"""The only skill this CLI command supports today. Deliberately a single
constant, not a dispatch table keyed by skill_id — adding a second entry
here without an individually-verified ExecutionRuntime for it would be
exactly the "hardcode a large collection of bindings" shortcut ADR-0009
rejected (see cv_agent/execution/runtimes/__init__.py's own docstring)."""


def _parse_input_kv(pairs: list[str]) -> dict[str, str]:
    """Parse repeated `--input KEY=VALUE` flags into a plain dict — the
    generic escape hatch alongside the `--path`/`--model-name` convenience
    flags, so this command stays usable for a future skill's differently-
    shaped inputs without inventing a new CLI mechanism per skill."""
    inputs: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"expected KEY=VALUE, got {pair!r}")
        key, _, value = pair.partition("=")
        key = key.strip()
        if not key:
            raise ValueError(f"expected KEY=VALUE with a non-empty key, got {pair!r}")
        inputs[key] = value
    return inputs


def _confirm_approval(
    binding: Any, *, approve_flag: bool, prompt: Callable[[str], str] = input
) -> bool:
    """
    Decide whether this execution attempt carries real, explicit approval.
    Never auto-approves — see docs/APPROVALS.md, [P§24].

    - A binding whose policy is not "approval_required" ("allowed" or
      "rejected") needs no confirmation from this function at all: SkillExecutor
      itself is what actually enforces "rejected" regardless of this
      return value, and "allowed" needs no gate per CLAUDE.md §3 rule 10 —
      returning True here is a no-op either way, never a bypass.
    - `--approve` on the command line counts as approval because the user
      explicitly, personally typed it as part of invoking *this* command
      for *this* skill — it is never set automatically or by a default.
    - Absent `--approve`, this asks once, clearly, and stops (per
      APPROVALS.md's own "Agent behavior at a gate" rule 3) via `prompt` —
      `input()` by default, injectable for tests. Only a live "y"/"yes"
      answer counts; anything else, or a non-interactive/EOF prompt (no
      TTY, no `--approve`), is treated as rejection — never as silent
      approval, and never a crash.
    """
    if binding.approval_policy != "approval_required":
        return True
    if approve_flag:
        return True
    try:
        answer = prompt(
            f"Approval required for skill '{binding.skill_id}' via binding "
            f"'{binding.binding_id}' (policy=approval_required). "
            "Approve execution? [y/N]: "
        )
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def _cmd_execute(
    skill_id: str,
    *,
    path: str | None,
    input_kv: list[str],
    model_name: str | None,
    task: str | None,
    approve: bool,
) -> int:
    """
    The real execution path: CVAgent -> SkillExecutor -> ExecutionBindingRegistry
    -> ExecutionRuntime — never bypassed, never duplicated here (ADR-0009).

    Steps, matching the task's own required contract: identify the
    requested skill, verify it is executable, construct the execution
    request, invoke the existing CVAgent/SkillExecutor path, return the
    real result, surface errors clearly.
    """
    import json

    from cv_agent.execution.models import SkillExecutionRequest
    from cv_agent.runtime.agent import CVAgent

    if skill_id != _SUPPORTED_EXECUTE_SKILL_ID:
        print(
            f"Skill '{skill_id}' has no supported real execution path in this "
            f"CLI yet — only {_SUPPORTED_EXECUTE_SKILL_ID!r} is individually "
            "verified and wired in today (ADR-0009 §8 fires per skill, not in "
            "bulk).",
            file=sys.stderr,
        )
        return 2

    agent = CVAgent()
    skill = agent.skills.get(skill_id)
    if skill is None:
        print(
            f"Skill '{skill_id}' was not discovered in this environment "
            "(not found under the scanned skill roots) — nothing to execute.",
            file=sys.stderr,
        )
        return 2

    # Explicit, controlled registration — this command is the one caller
    # that has actually identified this specific skill and deliberately
    # opts its one verified binding in; CVAgent.__init__ never does this
    # automatically (ADR-0009 §5), and no other skill_id reaches this line.
    from cv_agent.execution.runtimes.trt_perf_analysis import (
        register as _register_trt_perf_analysis,
    )

    _register_trt_perf_analysis(agent.execution_bindings)

    if not agent.can_execute(skill_id):
        print(
            f"Skill '{skill_id}' is discovered but not executable "
            "(no verified execution binding) — nothing to execute.",
            file=sys.stderr,
        )
        return 2

    try:
        inputs: dict[str, Any] = dict(_parse_input_kv(input_kv))
    except ValueError as exc:
        print(f"Invalid --input value: {exc}", file=sys.stderr)
        return 2
    if path is not None:
        inputs["path"] = path
    if model_name is not None:
        inputs["model_name"] = model_name

    binding = agent.execution_bindings.get_binding(skill_id)
    assert binding is not None  # can_execute() above already confirmed this

    approved = _confirm_approval(binding, approve_flag=approve)
    if binding.approval_policy == "approval_required" and not approved:
        print(
            "Execution not approved — aborting. Nothing was run.",
            file=sys.stderr,
        )
        return 3

    request = SkillExecutionRequest(
        inputs=inputs, task=task, requested_by="cli", approved=approved
    )
    result = agent.execute(skill, request)

    print(f"Skill: {result.skill_id}")
    print(f"Status: {result.status}")
    print(
        f"Binding: {result.evidence.binding_id}  Runtime: {result.evidence.runtime_id}  "
        f"started={result.evidence.started_at}  completed={result.evidence.completed_at}"
    )

    if result.ok:
        print("Result:")
        print(json.dumps(result.output, indent=2, sort_keys=True))
        return 0

    assert result.error is not None
    print(f"Error [{result.error.category}]: {result.error.message}", file=sys.stderr)
    return 1


_MAX_INTERRUPT_ROUNDS = 8
"""Generous upper bound over the graph's own documented maximum of four
interrupt kinds per run — clarify, choose_candidate (ADR-0010 §16),
provide_execution_inputs, approval_gate, each at most once (ADR-0010 §13's own topology). Originally added as a
CLI-only safety net for a real, pre-existing gap (`_route_after_analysis`
routing on `clarification_answers` truthiness instead of "was clarify
already attempted"): declining every clarification question re-paused at
the same `clarify` interrupt indefinitely. That gap is now fixed at its
source (`AgentState["clarification_attempted"]`, ADR-0003 §9, Q21) — the
graph itself is bounded to at most three interrupts per run, deterministically.
This constant stays as defense-in-depth only: cheap, already written and
tested, and a reasonable safety net against any future regression of that
bound, not a workaround for a known bug anymore."""


class WorkflowStuckError(RuntimeError):
    """Raised by `_run_workflow_interactive` when a workflow run re-raises
    more interrupts than `_MAX_INTERRUPT_ROUNDS` allows for — see that
    constant's own docstring for why this can happen at all."""


def _resume_value_for_interrupt(
    payload: dict[str, Any],
    *,
    answers: dict[str, str],
    inputs: dict[str, str],
    approve: bool,
    reject: bool,
    prompt: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
) -> Any:
    """
    Compute the real `Command(resume=...)` value for one paused interrupt —
    never a fabricated placeholder. Dispatches on the interrupt's own
    `payload["type"]` (ADR-0003 `clarify`/`approval`, ADR-0010 §13
    `provide_execution_inputs`) — this function itself never talks to
    LangGraph; `resume_workflow()` is generic across all three kinds
    (see its own docstring), so this is the one place a caller's answer
    is actually decided.

    `answers`/`inputs` are the caller's pre-supplied `--answer`/`--input`
    KEY=VALUE flags — reused verbatim for whichever field they name,
    across however many rounds of that field's own interrupt kind occur
    (at most one clarify round, at most one provide_execution_inputs
    round, per ADR-0003/ADR-0010 §13). A field neither flag covers falls
    back to a single live `prompt()` call — same "ask once, stop, never
    silently approve" posture `_confirm_approval` already uses for
    approval_gate, `docs/APPROVALS.md`, `[P§24]`.

    A blank/EOF answer to a clarification question is simply omitted (an
    empty-that-field, not a whole-interrupt cancel) — `_node_clarify`
    already treats a missing field as "no answer for it", never
    fabricating one (ADR-0003). If *every* field ends up blank/EOF, the
    resume value for both `clarification` and `provide_execution_inputs`
    is `""` (a non-dict falsy value) rather than `{}` — `resume_workflow()`'s
    own docstring documents that a literal empty dict is not reliably
    delivered by the installed LangGraph for either interrupt kind (ADR-0003
    §9, Q21), so `""` is the correct way to signal "declined to supply
    anything"; for clarification this reaches `_node_clarify` and produces
    an empty `clarification_answers` with `clarification_attempted=True`
    (the run proceeds, unknowns stay unknown — never a second `clarify`
    interrupt), for provide_execution_inputs it is classified "cancelled".
    """
    kind = payload.get("type")

    if kind == "clarification":
        collected: dict[str, str] = {}
        for question in payload["questions"]:
            field = question["relates_to_field"]
            if field in answers:
                out(f"  - {field} -> {answers[field]!r} (from --answer)")
                collected[field] = answers[field]
                continue
            try:
                value = prompt(
                    f"  {question['question']} (why: {question['why_it_matters']})\n  > "
                )
            except EOFError:
                value = ""
            if value.strip():
                collected[field] = value
        # ADR-0003 §9 (Q21 fix): a literal `{}` is not reliably delivered by
        # the installed LangGraph's Command(resume=...) — the graph would
        # silently re-pause at the same clarify interrupt instead of
        # resuming (confirmed empirically). `""` is delivered correctly and
        # is what _node_clarify treats as "no answers supplied" — same
        # convention already used below for provide_execution_inputs.
        return collected if collected else ""

    if kind == "provide_execution_inputs":
        collected = {}
        for field in payload["missing_inputs"]:
            name = field["name"]
            if name in inputs:
                out(f"  - {name} -> {inputs[name]!r} (from --input)")
                collected[name] = inputs[name]
                continue
            try:
                value = prompt(f"  {name} ({field['description']})\n  > ")
            except EOFError:
                value = ""
            if value.strip():
                collected[name] = value
        return collected if collected else ""

    if kind == "choose_candidate":
        # ADR-0010 §16 (Q18): the owner chose an interrupt, not a CLI
        # --skill override, so there is deliberately no flag for this — the
        # human is always asked, and a blank/EOF answer is "" (a non-
        # matching string the graph classifies "cancelled"), never a
        # default candidate.
        candidates = payload.get("candidates") or []
        lines = "\n".join(f"    {c['skill_id']}: {c['description']}" for c in candidates)
        try:
            answer = prompt(
                "Multiple executable skills match. Type the skill_id to use:\n"
                f"{lines}\n  > "
            )
        except EOFError:
            return ""
        return answer.strip()

    if kind == "approval":
        if approve:
            return "approved"
        if reject:
            return "rejected"
        try:
            answer = prompt(
                f"Approval required for skill '{payload['skill_id']}' via binding "
                f"'{payload['binding_id']}' (policy=approval_required). "
                "Approve execution? [y/N]: "
            )
        except EOFError:
            return "rejected"
        return "approved" if answer.strip().lower() in ("y", "yes") else "rejected"

    raise ValueError(f"unrecognized interrupt type: {kind!r}")


def _run_workflow_interactive(
    agent: Any,
    task: str,
    session_id: str,
    *,
    answers: dict[str, str],
    inputs: dict[str, str],
    approve: bool,
    reject: bool,
    prompt: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
) -> dict[str, Any]:
    """
    Drive one workflow run to completion, resolving every interrupt it
    actually raises (zero to four: `clarify`, `choose_candidate`, `provide_execution_inputs`,
    `approval_gate` — ADR-0010 §13's own topology diagram) with a real
    answer from `_resume_value_for_interrupt`, never a synthetic one.

    `agent` is duck-typed to `CVAgent.start_workflow()`/`.resume_workflow()`
    (ADR-0003/ADR-0010) — this function never imports `CVAgent` itself, so
    a test can pass any object with that shape (e.g. one built directly
    from `build_requirements_workflow_graph()`, the same construction
    `tests/test_workflow.py` already uses for a fixture binding) without
    needing real skill discovery or a registered `ExecutionRuntime`.

    `inputs` doubles as the pre-supplied `execution_inputs` channel
    (ADR-0010 §12) for this run's `start_workflow()` call — a caller who
    already knows a required value before the run starts never has to
    wait for a `provide_execution_inputs` interrupt to supply it.
    """
    state = agent.start_workflow(task, session_id=session_id, execution_inputs=inputs or None)
    rounds = 0
    while "__interrupt__" in state:
        rounds += 1
        if rounds > _MAX_INTERRUPT_ROUNDS:
            raise WorkflowStuckError(
                f"workflow raised more than {_MAX_INTERRUPT_ROUNDS} interrupts without "
                "finishing — most likely every clarification question was left "
                "unanswered (see _MAX_INTERRUPT_ROUNDS's own docstring); supply at "
                "least one real --answer and try again."
            )
        payload = state["__interrupt__"][0].value
        kind = payload.get("type")
        out(f"[INTERRUPT] {kind}")
        if kind == "clarification":
            for question in payload["questions"]:
                out(f"  - {question['question']} (why: {question['why_it_matters']})")
        elif kind == "provide_execution_inputs":
            out(f"  skill={payload['skill_id']} binding={payload['binding_id']}")
            for field in payload["missing_inputs"]:
                out(f"  - missing: {field['name']} ({field['description']})")
        elif kind == "choose_candidate":
            for candidate in payload["candidates"]:
                out(f"  - candidate: {candidate['skill_id']} ({candidate['description']})")
        elif kind == "approval":
            out(
                f"  skill={payload['skill_id']} binding={payload['binding_id']} "
                f"inputs={payload['inputs']}"
            )

        resume_value = _resume_value_for_interrupt(
            payload,
            answers=answers,
            inputs=inputs,
            approve=approve,
            reject=reject,
            prompt=prompt,
            out=out,
        )
        out(f"[RESUME] {kind} -> {resume_value!r}")
        state = agent.resume_workflow(session_id, resume_value)
    return state


def _print_workflow_summary(state: dict[str, Any], *, out: Callable[[str], None] = print) -> None:
    """Report what actually happened — including a terminal recovery
    failure's real reason (ADR-0010 §13), never silently folded into
    ordinary completion."""
    out(f"Final status: {state.get('status')}")
    out(f"Steps: {[s['node'] for s in state.get('steps', [])]}")

    analysis = state.get("requirements_analysis")
    if analysis:
        fields = analysis.get("fields", [])
        known = [f["name"] for f in fields if f["status"] == "known"]
        assumed = [f["name"] for f in fields if f["status"] == "assumed"]
        out(f"Known fields: {known}")
        out(f"Assumed fields: {assumed}")

    planning = state.get("planning_result")
    if planning:
        out(f"Planning status: {planning.get('status')}")

    candidate_selection = state.get("candidate_selection")
    if candidate_selection is not None:
        out(
            f"Candidate selection: outcome={candidate_selection.get('outcome')} "
            f"terminal={candidate_selection.get('terminal')} "
            f"chosen={candidate_selection.get('chosen_skill_id')}"
        )

    recovery = state.get("execution_input_recovery")
    if recovery is not None:
        line = f"Execution-input recovery: outcome={recovery.get('outcome')} "
        line += f"terminal={recovery.get('terminal')}"
        if recovery.get("mismatch_detail"):
            line += f" detail={recovery['mismatch_detail']}"
        out(line)

    if state.get("pending_execution") is not None:
        out(f"Approval decision: {state.get('approval_decision')}")

    result = state.get("execution_result")
    if result is not None:
        out(f"Execution result status: {result.get('status')}")


def _cmd_workflow(
    task: str,
    *,
    answer_kv: list[str],
    input_kv: list[str],
    approve: bool,
    reject: bool,
) -> int:
    """
    The real requirements-clarification / execution-input-recovery /
    approval-gated workflow entrypoint — `--answer`/`--input` pre-supply
    values, `--approve`/`--reject` pre-supply an approval decision, and a
    live stdin prompt covers whatever a flag didn't (see
    `_resume_value_for_interrupt`). Never fabricates an answer.

    Single-process only — the default checkpointer (MemorySaver) does not
    persist across process restarts (ADR-0003 §7), so a resumed run only
    ever means "still within this one invocation's interrupt loop", not
    "resumed from a prior CLI call".

    This constructs a plain, unregistered `CVAgent` — same honesty default
    as `analyze`/`resolve`/`skills` (no binding is ever auto-registered,
    ADR-0009 §5) — so `plan_execution` can reach `no_executable_candidate`
    but never `planned`/`missing_required_inputs` against a real skill
    here; wiring a `pending_execution`/binding choice into this command is
    a separate, not-yet-authorized decision (see issue #34's own stated
    scope). `provide_execution_inputs`/`approval_gate` input handling is
    still fully real and generic — it is simply not reachable through this
    command against any of the 84 real installed skills today, the same
    honest limitation `analyze`/`resolve` already report for "executable".

    This is the one CLI command that touches durable Project Memory
    (ADR-0004) — start_workflow()/resume_workflow() persist a SessionRecord
    and, when produced, a ProjectUnderstandingRevision. workspace_root is
    resolved explicitly here, at the actual application entry point, per
    the workspace-root resolution contract (ADR-0004 §1 item 13, D-019):
    ProjectMemoryStore/default_db_path() never infer it themselves.
    """
    from dataclasses import replace
    from pathlib import Path

    from cv_agent.config.settings import load_config
    from cv_agent.runtime.agent import CVAgent

    try:
        answers = _parse_input_kv(answer_kv)
        inputs = _parse_input_kv(input_kv)
    except ValueError as exc:
        print(f"Invalid --answer/--input value: {exc}", file=sys.stderr)
        return 2

    config = replace(load_config(), workspace_root=Path.cwd())
    agent = CVAgent(config)
    session_id = str(uuid.uuid4())
    print(f'CV Agent workflow — task: "{task}"')
    print(f"Session: {session_id}")
    print()

    try:
        state = _run_workflow_interactive(
            agent,
            task,
            session_id,
            answers=answers,
            inputs=inputs,
            approve=approve,
            reject=reject,
        )
    except WorkflowStuckError as exc:
        print(file=sys.stderr)
        print(f"Aborted: {exc}", file=sys.stderr)
        return 3

    print()
    _print_workflow_summary(state)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(prog="cv-agent", description="CV Engineering Agent CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("skills", help="Show actually discovered skills.")
    subparsers.add_parser("capabilities", help="Show declared capabilities and status.")
    resolve_parser = subparsers.add_parser(
        "resolve", help="Deterministic task -> capability -> skill resolution."
    )
    resolve_parser.add_argument("task", help="Natural-language task description.")
    analyze_parser = subparsers.add_parser(
        "analyze", help="Requirements analysis + CV task decomposition."
    )
    analyze_parser.add_argument("request", help="Natural-language CV problem description.")
    subparsers.add_parser(
        "executions", help="Show execution bindings/runtimes and what's executable."
    )
    execute_parser = subparsers.add_parser(
        "execute",
        help="Run a verified skill through the real CVAgent -> SkillExecutor path.",
    )
    execute_parser.add_argument(
        "skill_id", help="Skill to execute (only 'trt-perf-analysis' is supported today)."
    )
    execute_parser.add_argument(
        "--path", default=None, help="Folder of layers_*.json/profile_*.json to analyze."
    )
    execute_parser.add_argument(
        "--input",
        dest="input_kv",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Additional execution input, repeatable (e.g. --input model_name=my-model).",
    )
    execute_parser.add_argument(
        "--model-name", dest="model_name", default=None, help="Optional model name to forward."
    )
    execute_parser.add_argument(
        "--task", default=None, help="Optional natural-language task label for evidence trails."
    )
    execute_parser.add_argument(
        "--approve",
        action="store_true",
        help="Explicitly approve execution up front, for a binding that requires approval "
        "(never applied automatically).",
    )
    workflow_parser = subparsers.add_parser(
        "workflow",
        help="Requirements clarification / approval / execution-input recovery, "
        "with real answers.",
    )
    workflow_parser.add_argument("task", help="Natural-language CV problem description.")
    workflow_parser.add_argument(
        "--answer",
        dest="answer_kv",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Pre-supplied clarification answer, repeatable "
        "(e.g. --answer deployment_target=jetson-orin).",
    )
    workflow_parser.add_argument(
        "--input",
        dest="input_kv",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Pre-supplied execution input, repeatable (e.g. --input path=/data/run1) — "
        "used both up front (ADR-0010 §12) and for a provide_execution_inputs recovery "
        "round (ADR-0010 §13).",
    )
    workflow_approval_group = workflow_parser.add_mutually_exclusive_group()
    workflow_approval_group.add_argument(
        "--approve",
        action="store_true",
        help="Pre-supply an 'approved' decision for an approval_gate interrupt "
        "(never applied automatically).",
    )
    workflow_approval_group.add_argument(
        "--reject",
        action="store_true",
        help="Pre-supply a 'rejected' decision for an approval_gate interrupt.",
    )

    args = parser.parse_args(argv)

    if args.command is None:
        return _health_check()
    if args.command == "skills":
        return _cmd_skills()
    if args.command == "capabilities":
        return _cmd_capabilities()
    if args.command == "resolve":
        return _cmd_resolve(args.task)
    if args.command == "analyze":
        return _cmd_analyze(args.request)
    if args.command == "executions":
        return _cmd_executions()
    if args.command == "execute":
        return _cmd_execute(
            args.skill_id,
            path=args.path,
            input_kv=args.input_kv,
            model_name=args.model_name,
            task=args.task,
            approve=args.approve,
        )
    if args.command == "workflow":
        return _cmd_workflow(
            args.task,
            answer_kv=args.answer_kv,
            input_kv=args.input_kv,
            approve=args.approve,
            reject=args.reject,
        )

    parser.error(f"unrecognized command: {args.command}")  # pragma: no cover
    return 2


if __name__ == "__main__":
    sys.exit(main())
