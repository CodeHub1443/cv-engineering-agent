# CV Engineering Agent — Architectural Principles

**Version:** V1.0  
**Status:** Foundational specification

1. **Specification first.** Foundational behavior and contracts are defined before implementation.
2. **Evidence over popularity.** Model and tooling choices are justified by requirements, evidence, and measured trade-offs.
3. **Current knowledge when needed.** Use live research for changing libraries, releases, compatibility, benchmarks, hardware/software behavior, and recent techniques.
4. **Provenance is mandatory for important knowledge.** Preserve source, claim, evidence, authority, confidence, freshness, and applicability.
5. **Explicit state.** Task context, execution state, decisions, approvals, artifacts, and lineage are first-class state.
6. **Agents propose; tools execute.** Agents select capabilities and request actions; controlled tools perform them.
7. **Policy is enforced outside the model.** Permissions, budgets, approval gates, and destructive-action controls are runtime/tool responsibilities.
8. **Human approval for consequential actions.** Expensive compute, destructive actions, production changes, deployment, and publication require approval according to policy.
9. **Reproducibility.** Data, code, configuration, environment, hardware, seed, model, metrics, artifacts, and experiment lineage are recorded for material experiments.
10. **Baseline before optimization.** Establish a reproducible baseline and identify the bottleneck before performance optimization.
11. **Uncertainty is explicit.** Distinguish verified facts, estimates, hypotheses, recommendations, and unresolved questions.
12. **No invented requirements or results.** Never fabricate requirements, benchmarks, experiment outcomes, citations, tool execution, or source claims.
13. **Small interfaces.** Domain contracts remain project-owned; vendor/framework integrations sit behind adapters.
14. **Provider neutrality.** LLM and coding-worker choices are replaceable through stable interfaces.
15. **Capability-driven execution.** Select capabilities first, then resolve skills, tools, workers, and knowledge sources.
16. **Architecture is iterative.** Research, formulation, data, architecture, evaluation, and optimization may loop when evidence changes the decision.
17. **Avoid framework soup.** LangGraph is the orchestration foundation; LangChain is optional for useful adapters/integrations; new frameworks require explicit justification.
18. **One feature at a time.** Repository development uses short-lived branches and controlled integration through dev-munna.
