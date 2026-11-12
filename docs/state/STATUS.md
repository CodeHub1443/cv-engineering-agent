# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-11-12 · **Phase:** 5e/6 — LLM gateway v2 complete (G1 to G7 merged); ADR-0023 S1 and S2 merged; S3 in flight in a parallel batch.
**Health:** Linux CI is authoritative (last measured run, G5: ruff clean, mypy ok, pytest 1893 passed / 26 skipped). Windows local: the known failures by file (D-096: `test_evaluation_records.py`, `test_linux_nvidia_runtime.py`, `test_baseline_wiring.py`, `test_yolo_eval_binding.py`, `test_yolo_inference_binding.py`) and one Windows-only mypy `SIGKILL` error. Any other failure is a defect.

## Where we are

Baseline origin/main = 3628289 (#114). Merged since the last STATUS: gateway v2 #84–#102 (G1 to G7 done; research extraction on the fast tier, #101/#102); ADR-0023 S1a/b/c (#112 to #114) and S2 schema v3 (#108). Owner confirmed `cv-agent llm-log migrate` ran on the Windows PC.
**Ledger:** 10 records, unchanged (sha256 `9251eb0c…8fef8fa`, full value in JOURNAL).
**LLM gateway:** ADR-0020 and ADR-0021 Accepted. ADR-0023 Accepted (D-095), amended by D-097. Every task class routes to `offline`; the repo makes no hosted call. Hosted tiers run only on the owner's Windows PC (D-091, D-092).
**Parallel batch 3 (other sessions, in flight):** ADR-0023 S3 (`wt\a23s3`; owns `cv_agent/requirements/*` and `cv_agent/llm/governed.py`); Q41 research CLI (`wt\q41`; owns the `research` subcommand in `cv_agent/__main__.py`). This session edits docs only.
**M4 wording:** ADR-0017 note added in this PR. `docs/experiments/EXP-20261004-01-proposal.md` stays historical.
**Done earlier:** EXP-20261004-01..04 (measurement only); failure analysis (#75); annotation-label review, see `docs/experiments/`; ADR-0019 foundation (D-079, D-081, D-084; fake runtimes only).

## Decisions in force

- **D-077:** precision floor 0.75 at conf 0.25 (fixed threshold, never mAP). **D-078:** both APs must improve; +0.010 / +0.020 are provisional. **D-082:** baseline is FP16-requested EXP-20261004-01.
- **D-080 / D-087:** standing grant for local tools and GPU runs. Each run records a cost estimate and an approval reference bound to one experiment and one cost ceiling; ADR-0018 §6 checks still apply.
- **D-084:** ADR-0019 Accepted. **D-085 / D-090:** merge commits once CI is green (no squash, no rebase, no `--admin`).
- **D-088 to D-093:** LLM gateway v2 (ADR-0020, ADR-0021). **D-094 / D-095:** ADR-0023 (Q40: `PROJECT_DATA` stays blocked). **D-096:** parallel worktree batches. **D-097:** ADR-0023 amendment.

## Open (owner)

1. **ADR-0020** open questions Q38–Q41, Q46–Q49 (safe defaults recorded). **Q41** (research entry point) is in flight in batch 3.
2. **Q39:** NARRATIVE tier. ADR-0023 recommends the deterministic template as the default narrative, so no hosted narrative route exists yet.
3. **Q53:** Windows `test_baseline_wiring` PermissionError. **Q54:** durable KnowledgeStore backend (ADR-0006 §8).
4. **Q32** (a) variance, (c) delta rationale, (d) meaning of "improve"; **Q27**, **Q31**, **Q33** (typed identities); annotation labels for ranks 011, 013, 027.

## Next actions

1. ADR-0023 **S3** (requirements) and **Q41** (research CLI), both in batch 3. CI green, then merge under D-090.
2. ADR-0023 **S4** together with a durable KnowledgeStore design (**Q54**): S4 sets `ingest = WEB_FETCH` at the writer, adds `select_claims` and the payload size guard. The store design goes in a separate DESIGN-ONLY ADR.
3. ADR-0023 **S5** (remaining acceptance tests, including the AST backstop noted in D-097).

## Do not start yet

All routes default to `offline`. Only `[llm.routing]` `extraction` may usefully move to `fast`, and only with a D-entry; that switch is an owner decision (D-089, D-092). `selection` and `narrative` send `PROJECT_DATA` and stay refused (Q40). Any GPU run without a cost estimate and an approval reference bound to one experiment and cost ceiling. A real training runtime (needs its own issue). Model swaps (Q25). NMS or crowd experiments. TensorRT, DeepStream, Model Optimizer. Stopping another project's processes. Any local LLM tier or GPU contact by the gateway (D-091).
