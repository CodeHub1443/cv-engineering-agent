# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-11-14 · **Phase:** 5e/6 — LLM gateway v2 complete; ADR-0023 S1 to S5 merged (ADR-0023 complete); Q58 resolved (`research --live`, #138); ADR-0024 K1a merged (PR #142); research HTML-to-text fix in review (#144, #145).
**Health:** Linux CI is authoritative. Windows local (D-103), measured on the research-html-text branch (origin/main f5633e4 merged): ruff clean; mypy only the Windows `SIGKILL` error; pytest 26 failed, 2496 passed, 10 skipped, all failures in `test_evaluation_records.py` (18), `test_linux_nvidia_runtime.py` (5), `test_yolo_eval_binding.py` (1), `test_yolo_inference_binding.py` (2). Any other failure is a defect.

## Where we are

Baseline origin/main = a191390 (ADR-0023 S5 merged, ADR-0024 accepted, `research --live`). Merged: **ADR-0024 K1a** (issue #141, PR #142): the SQLite store lifecycle (schema v1, `initialise`, `migrate`, fail-closed open). K1 is split K1a/K1b/K1c (D-104); K1b then K1c follow, one PR each.
**Ledger:** 10 records, unchanged (sha256 `9251eb0c…8fef8fa`, full value in JOURNAL).
**LLM gateway:** ADR-0020 and ADR-0021 Accepted; ADR-0020 amended 2026-11-13 (per-invocation CLI route override). ADR-0023 Accepted (D-095), amended by D-097. Every task class routes to `offline` in the repo and the packaged default stays all-offline. **D-098 is applied per invocation (D-102):** `cv-agent research --live` sends EXTRACTION to `fast` (Haiku) for that run only; it needs `CV_AGENT_ANTHROPIC_API_KEY` and an initialised call log (`cv-agent llm-log init`). Hosted tiers run only on the owner's Windows PC (D-091, D-092).
**Done earlier:** EXP-20261004-01..04 (measurement only); failure analysis (#75); annotation-label review, see `docs/experiments/`; ADR-0019 foundation (D-079, D-081, D-084; fake runtimes only).

## Decisions in force

- **D-077:** precision floor 0.75 at conf 0.25 (fixed threshold, never mAP). **D-078:** both APs must improve; +0.010 / +0.020 are provisional. **D-082:** baseline is FP16-requested EXP-20261004-01.
- **D-080 / D-087:** standing grant for local tools and GPU runs. Each run records a cost estimate and an approval reference bound to one experiment and one cost ceiling; ADR-0018 §6 checks still apply.
- **D-084:** ADR-0019 Accepted. **D-085 / D-090:** merge commits once CI is green (no squash, no rebase, no `--admin`).
- **D-088 to D-093:** LLM gateway v2 (ADR-0020, ADR-0021). **D-094 / D-095:** ADR-0023 (Q40: `PROJECT_DATA` stays blocked). **D-096:** parallel worktree batches. **D-097:** ADR-0023 amendment.
- **D-101:** ADR-0024 accepted. **D-102:** `research --live`. **D-103:** four known Windows-only failing files. **D-104:** K1 split into K1a/K1b/K1c. **D-105:** local history rewriting only on never-pushed commits, and reported; never after a push. **D-106:** research prepares visible text and a claim-term window before the 8,000-character cut (fetcher unchanged); **D-107** is reserved for K1b.

## Open (owner)

1. **ADR-0020** open questions Q38–Q41, Q46–Q49 (safe defaults recorded). **Q41** is done (#118).
2. **Q39:** NARRATIVE tier. ADR-0023 recommends the deterministic template as the default narrative, so no hosted narrative route exists yet.
3. **Q54:** durable KnowledgeStore backend (ADR-0024; K1a merged, K1b to K4 not started; stays open until K3). **Q55–Q57:** research polish. **Q65–Q66:** fetcher redirects; `truncated` flag ignored (Q63–Q64 reserved for K1).
4. **Q59 to Q62** (safe defaults recorded): water-fill fairness for the §7.3 comparison; reference `task_support` always empty; rationale E-ordinals not mapped to item IDs; selection builder uses the 24,000 default, not the configured `max_input_chars`.
5. **Q32** (a) variance, (c) delta rationale, (d) meaning of "improve"; **Q27**, **Q31**, **Q33** (typed identities); annotation labels for ranks 011, 013, 027.

## Next actions

0. Review the research HTML-to-text PR (#144, #145), then the owner's re-run of `research --live` on the YOLO11 page.
1. ADR-0024 **K1b** (retrieval keys, record/put/get/list/query/history, content hash, row rebuild, staleness from a passed `as_of`), then K1c, then K2 to K4.
2. ADR-0023 §7.3: the SELECTION route switch still needs a production caller of `select_candidate` and a recorded comparison against the deterministic ranker.
3. The owner's first real `cv-agent research --live` run (needs a key and `llm-log init`).

## Do not start yet

All persisted routes stay `offline`; `research --live` is the only way to reach a hosted tier, and only for EXTRACTION. `selection` and `narrative` send `PROJECT_DATA` and stay refused (Q40). Any GPU run without a cost estimate and an approval reference bound to one experiment and cost ceiling. A real training runtime (needs its own issue). Model swaps (Q25). NMS or crowd experiments. TensorRT, DeepStream, Model Optimizer. Stopping another project's processes. Any local LLM tier or GPU contact by the gateway (D-091).
