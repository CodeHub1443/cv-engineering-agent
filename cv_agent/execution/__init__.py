"""
cv_agent.execution — Skill execution & invocation boundary.

See ADR-0009. This package answers the question DISCOVERED skills (Step 2,
`cv_agent.skills`) leave open: given a skill the agent knows is installed,
how — if at all — can it actually be run? The answer this package encodes is
"only through a registered, verified ExecutionBinding" — discovery alone
never implies executability.
"""
