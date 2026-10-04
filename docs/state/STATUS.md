# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-10-04 · **Phase:** 5d — evaluation infrastructure made trustworthy; no GPU
experiment run · **Health:** green on repository tests; amber on experiment readiness (see Blockers)

## Where we are

Branch `feature/claude/experiment-provenance-recovery` (worktree `/home/dev/cv-engineering-agent-sweep`).
It holds the sweep work (based on `feature/claude/conf-threshold-sweep` @ `1531344`, which
includes unmerged PR #69 commits), the provenance and ledger work (ADR-0016), and the ADR-0015
diagnosis erratum merged from `feature/claude/diagnosis-baseline` (PR #71). **Committed, not pushed,
not merged.**

**Done:**
- **Ledger recovered (Q29, executed):** restored into `/home/dev/cv-engineering-agent/.cv_agent/`,
  sha256 `d7ff167e…4c19`, identical to the Trash copy (untouched). Six records verified. Gitignored.
- **Ledger path fixed:** the default ledger and all `.cv_agent/` paths resolve to the main checkout
  through git's common directory. A worktree cannot create an empty ledger. Missing ledger = error.
- **Provenance (ADR-0016, accepted):** evidence-producing scripts refuse a dirty tree before any GPU
  work and record the HEAD SHA. A non-`proposed` record needs a valid `commit_sha`. Historical NULL rows stay NULL.
- **Real-skill tests:** fixed against the installed skill's contract (schema `1.2`, layers + profile pair).
  Not skipped or weakened. The repo does not pin a skill version (Q31 open).
- **Protocol (Q28, D-067):** standard mAP at `conf=0.001`. Inference default 0.25 unchanged (Q30 open).

**Validation:** full pytest **1620 passed, 4 skipped, 0 failed**. `ruff check .` clean. `mypy cv_agent`
clean (76 files). New files mypy clean.

## Next 3 actions (owner)

1. **Review and push or merge** the feature branch. Nothing has been pushed or merged. It includes PR #69 commits, so #69 should be reviewed first.
2. **Decide D-069 / EXP-20261004-01 criteria**, if the run is to inform a decision. Current state: measurement-only, no criteria.
3. **Decide Q31** (repository versus skill ownership of the trt-perf-analysis contract) and **Q30** (operating point, when there is a target).

## Blockers

- EXP-20261004-01 needs a **record-writing script** through the execute path before its results are
  ledger evidence. The prediction files alone are not records. Not built (proposal §10).
- Six historical ledger rows have NULL `commit_sha`. They are documented; no SHA was fabricated.
- Q30 OPEN, Q31 OPEN, D-069 OPEN, Q27 OPEN.

## Do not start yet

EXP-20261004-01 execution, until the record-writing path exists and the owner approves the run.
Training (option A). Model swaps (option B; Q25). NMS or crowd experiments. Any precision floor,
recall target, or operating point (Q30). TensorRT, DeepStream, Model Optimizer. Pushing or merging
this branch without owner review. `[P§34]`
