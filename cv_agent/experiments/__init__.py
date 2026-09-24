"""
cv_agent.experiments — the Experiment Ledger (ADR-0011, OPEN_QUESTIONS.md Q16).

Owns the typed, fail-closed representation of one experiment run (the schema
docs/state/EXPERIMENTS.md and [P§25] already define) and its SQLite-backed
persistence, following the exact architectural pattern cv_agent/memory/
established for project memory (ADR-0004, Q8/D-017): a technology-neutral
Protocol (ExperimentLedger) plus one concrete backend (SqliteExperimentLedger)
that no other module imports directly.

This package records experiments; it does not run them. It has no dependency
on cv_agent.execution, cv_agent.graph, cv_agent.tools, cv_agent.llm, or
cv_agent.knowledge, and none of those layers know it exists yet — nothing is
wired into CVAgent or the CLI in this change, mirroring how ADR-0004's
interface and its CVAgent wiring were two separate, later-connected steps.
"""
