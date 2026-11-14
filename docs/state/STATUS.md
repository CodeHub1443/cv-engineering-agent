# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-11-14 · **Phase:** 5e/6 — LLM gateway v2 complete; ADR-0023 S1 to S4 merged, S5 next; Q58 resolved (`research --live` merged, #138); ADR-0024 K1a in review.
**Health:** Linux CI is authoritative (last measured run, G5: ruff clean, mypy ok, pytest 1893 passed / 26 skipped). Windows local (D-103): the known failures by file are `test_evaluation_records.py`, `test_linux_nvidia_runtime.py`, `test_yolo_eval_binding.py`, `test_yolo_inference_binding.py`, plus one Windows-only mypy `SIGKILL` error. Measured on the K1a branch after merging origin/main (b5141c0): 26 failed / 2423 passed / 10 skipped, all in those four files. Any other failure is a defect.

## Where we are

Baseline origin/main = b5141c0 (includes `research --live`, D-102, and ADR-0024 accepted, D-101). In flight: **ADR-0024 K1a** (issue #141, PR open, not merged): the SQLite store lifecycle. K1 is split K1a/K1b/K1c (D-104); K1b then K1c follow after K1a is merged.
**Ledger:** 10 records, unchanged (sha256 `9251eb0c…8fef8fa`, full value in JOURNAL).
**LLM gateway:** ADR-0020 and ADR-0021 Accepted; ADR-0020 amended 2026-11-13 (per-invocation CLI route override). ADR-0023 Accepted (D-095), amended by D-097. Every task class routes to `offline` in the repo and the packaged default stays all-offline. **D-098 is applied per invocation (D-102):** `cv-agent research --live` sends EXTRACTION to `fast` (Haiku) for that run only; the route and credential resolve before the fetch. It needs `CV_AGENT_ANTHROPIC_API_KEY` and an initialised call log (`cv-agent llm-log init`). Hosted tiers run only on the owner's Windows PC (D-091, D-092).
**Done earlier:** EXP-20261004-01..04 (measurement only); failure analysis (#75); annotation-label review, see `docs/experiments/`; ADR-0019 foundation (D-079, D-081, D-084; fake runtimes only).

## Decisions in force

- **D-077:** precision floor 0.75 at conf 0.25 (fixed threshold, never mAP). **D-078:** both APs must improve; +0.010 / +0.020 are provisional. **D-082:** baseline is FP16-requested EXP-20261004-01.
- **D-080 / D-087:** standing grant for local tools and GPU runs. Each run records a cost estimate and an approval reference bound to one experiment and one cost ceiling; ADR-0018 §6 checks still apply.
- **D-084:** ADR-0019 Accepted. **D-085 / D-090:** merge commits once CI is green (no squash, no rebase, no `--admin`).
- **D-088 to D-093:** LLM gateway v2 (ADR-0020, ADR-0021). **D-094 / D-095:** ADR-0023 (Q40: `PROJECT_DATA` stays blocked). **D-096:** parallel worktree batches. **D-097:** ADR-0023 amendment.
- **D-101:** ADR-0024 accepted (durable KnowledgeStore). **D-102:** Q58 option (b), `research --live`. **D-103:** four known Windows-only failing files. **D-104:** K1 split into K1a/K1b/K1c.

## Open (owner)

1. **ADR-0020** open questions Q38–Q41, Q46–Q49 (safe defaults recorded). **Q41** is done (#118).
2. **Q39:** NARRATIVE tier. ADR-0023 recommends the deterministic template as the default narrative, so no hosted narrative route exists yet.
3. **Q54:** durable KnowledgeStore backend (ADR-0024 accepted; K1a in review, K1b to K4 not started; stays open until K3). **Q55–Q57:** research polish (staleness horizons, README commands; Q57 addressed for `--live` only). (Q53 fixed; Q58 answered, D-102.)
4. **Q32** (a) variance, (c) delta rationale, (d) meaning of "improve"; **Q27**, **Q31**, **Q33** (typed identities); annotation labels for ranks 011, 013, 027.

## Next actions

1. Owner review and merge of the K1a PR under D-090 (CI green first).
2. ADR-0023 **S5** (remaining acceptance tests, including the AST backstop noted in D-097).
3. ADR-0024 K1b, K1c, then K2 to K4; the owner's first real `cv-agent research --live` run (needs a key and `llm-log init`).

## Do not start yet

All persisted routes stay `offline`; `research --live` is the only way to reach a hosted tier, and only for EXTRACTION. `selection` and `narrative` send `PROJECT_DATA` and stay refused (Q40). Any GPU run without a cost estimate and an approval reference bound to one experiment and cost ceiling. A real training runtime (needs its own issue). Model swaps (Q25). NMS or crowd experiments. TensorRT, DeepStream, Model Optimizer. Stopping another project's processes. Any local LLM tier or GPU contact by the gateway (D-091).
