"""
cv_agent.__main__ — CLI entrypoint.

Usage:
    python -m cv_agent                     health check (default)
    python -m cv_agent skills              show actually discovered skills
    python -m cv_agent capabilities        show declared capabilities + status
    python -m cv_agent resolve "<task>"    deterministic task -> capability -> skill
    python -m cv_agent analyze "<request>" requirements analysis + task decomposition
    python -m cv_agent executions          show execution bindings/runtimes + what's executable
    python -m cv_agent workflow "<task>"   demo: clarification interrupt -> answer -> resume
    cv-agent ...                           (when installed via pip)
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser


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


def _cmd_workflow_demo(task: str) -> int:
    """
    Single-process smoke demo: request -> clarification interrupt -> answer
    -> resume. Necessarily single-process — the default checkpointer
    (MemorySaver) does not persist across process restarts, so a two-CLI-
    invocation demo could not actually resume anything (see ADR-0003 §7).
    Answers here are synthetic placeholders, clearly labeled as such; this
    proves the interrupt/resume mechanics, not real requirements gathering.
    """
    from cv_agent.runtime.agent import CVAgent

    agent = CVAgent()
    print(f'CV Agent workflow demo — task: "{task}"')
    print()

    started = agent.start_workflow(task, session_id="cli-demo")

    if "__interrupt__" not in started:
        print("No clarification needed — request was already fully specified.")
        print(f"Status: {started['status']}")
        return 0

    payload = started["__interrupt__"][0].value
    questions = payload["questions"]
    print(f"[INTERRUPT] Clarification needed ({len(questions)} question(s)):")
    for q in questions:
        print(f"  - {q['question']}")
        print(f"      why it matters: {q['why_it_matters']}")

    print()
    print("[DEMO] Auto-supplying synthetic placeholder answers (non-interactive):")
    answers = {}
    for q in questions:
        placeholder = f"[demo answer for {q['relates_to_field']}]"
        answers[q["relates_to_field"]] = placeholder
        print(f"  - {q['relates_to_field']} -> {placeholder!r}")

    print()
    print("[RESUME] Resuming the same paused run with these answers...")
    resumed = agent.resume_workflow("cli-demo", answers)

    print()
    print(f"Status after resume: {resumed['status']}")
    print(f"Steps taken: {[s['node'] for s in resumed['steps']]}")
    fields = resumed["requirements_analysis"]["fields"]
    known = [f["name"] for f in fields if f["status"] == "known"]
    assumed = [f["name"] for f in fields if f["status"] == "assumed"]
    print(f"Known fields (from the original request text): {known}")
    print(f"Assumed fields (from the resume answers just supplied): {assumed}")
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
    workflow_parser = subparsers.add_parser(
        "workflow",
        help="Demo: request -> clarification interrupt -> synthetic answer -> resume.",
    )
    workflow_parser.add_argument("task", help="Natural-language CV problem description.")

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
    if args.command == "workflow":
        return _cmd_workflow_demo(args.task)

    parser.error(f"unrecognized command: {args.command}")  # pragma: no cover
    return 2


if __name__ == "__main__":
    sys.exit(main())
