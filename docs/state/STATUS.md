# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-11-15 · **Phase:** 5e/6 — first optimisation candidate proposed (EXP-20261115-01, D-115, #157); Issue C (#161) merged; Issue B1 (#162) merged; B2 (PR #163, recorder) in review; LLM gateway v2 complete; ADR-0023 S1 to S5 merged (ADR-0023 complete); Q58 resolved (`research --live`, #138); ADR-0024 K1 (#142, #147, #148), K2 (#150) and K3 (#152) merged; K4 (#155) merged; research HTML-to-text fix merged (#144, #145).
**Health:** Linux CI is authoritative. Windows local (D-103), measured on the Issue B2 tree merged with origin/main (82d28fe): ruff clean; mypy only the Windows `SIGKILL` error; pytest 35 failed, 2647 passed, 10 skipped, all failures in `test_evaluation_records.py` (27; the 9 new wrapper tests import `resource`), `test_linux_nvidia_runtime.py` (5), `test_yolo_eval_binding.py` (1), `test_yolo_inference_binding.py` (2). Any other failure is a defect.

## Where we are

Baseline origin/main includes K1 (store), K2 (`cv-agent knowledge`) and K3 (`research` persists by default). Merged: **ADR-0024 K4** (#153, PR #155): `model_selection/stored_evidence.py` merges fresh stored items, keyed by candidate id, into the reference comparison (`evidence` + `as_of`; stale excluded; D-111). No production caller yet (K4b); the SELECTION route stays offline.
**First candidate (proposed, not run):** `EXP-20261115-01`, yolo11n.pt at imgsz 768, inference-only, one run, baseline EXP-20261004-01; success = D-077 floor plus D-113 gains (+0.010 / +0.020, provisional); ceiling 0.05 GPU-hours; approval reference `EXP-20261115-01-OWNER-20261115`. Proposal: `docs/experiments/EXP-20261115-01-proposal.md`. Hardware figures are RTX 3060 proxies; the deployment GPU is unnamed (Q25 note). **Issue B** is split for size: **B1** (#162, merged; D-117, ADR-0017 amendment) gave the wrapper `--exp-id` and the shared candidate rule; **B2** (PR #163) adds the recorder `--candidate` and closes #159. The run waits for B2 to merge.
**Ledger:** 10 records, unchanged (sha256 `9251eb0c…8fef8fa`, full value in JOURNAL).
**LLM gateway:** ADR-0020 and ADR-0021 Accepted; ADR-0020 amended 2026-11-13 (per-invocation CLI route override). ADR-0023 Accepted (D-095), amended by D-097. Every task class routes to `offline` in the repo and the packaged default stays all-offline. **D-098 is applied per invocation (D-102):** `cv-agent research --live` sends EXTRACTION to `fast` (Haiku) for that run only; it needs `CV_AGENT_ANTHROPIC_API_KEY` and an initialised call log (`cv-agent llm-log init`). Hosted tiers run only on the owner's Windows PC (D-091, D-092).
**Done earlier:** EXP-20261004-01..04 (measurement only); failure analysis (#75); annotation-label review, see `docs/experiments/`; ADR-0019 foundation (D-079, D-081, D-084; fake runtimes only).

## Decisions in force

- **D-077:** precision floor 0.75 at conf 0.25 (fixed threshold, never mAP). **D-078:** both APs must improve; +0.010 / +0.020 are provisional. **D-082:** baseline is FP16-requested EXP-20261004-01.
- **D-080 / D-087:** standing grant for local tools and GPU runs. Each run records a cost estimate and an approval reference bound to one experiment and one cost ceiling; ADR-0018 §6 checks still apply.
- **D-084:** ADR-0019 Accepted. **D-085 / D-090:** merge commits once CI is green (no squash, no rebase, no `--admin`).
- **D-088 to D-093:** LLM gateway v2 (ADR-0020, ADR-0021). **D-094 / D-095:** ADR-0023 (Q40: `PROJECT_DATA` stays blocked). **D-096:** parallel worktree batches. **D-097:** ADR-0023 amendment.
- **D-101:** ADR-0024 accepted. **D-102:** `research --live`. **D-103:** four known Windows-only failing files. **D-104:** K1 split into K1a/K1b/K1c. **D-105:** local history rewriting only on never-pushed commits, and reported; never after a push. **D-106:** research prepares visible text and a claim-term window before the 8,000-character cut (fetcher unchanged). **D-107:** K1b implementation choices (second-precision `recorded_at`, naive clock refused, un-normalised stored key is a bad row, `query` order). **D-108:** K1c choices (optional `writer`/`recorded_at`; `model_names` any-of, empty = no filter). **D-109:** K2 CLI flags (no `--json`; `--fresh-only`; `show` unknown = exit 1). **D-110:** K3 research persists by default; store, then credential, then fetch. **D-111:** K4 stored evidence joins by exact normalised candidate id, fresh only, curated first. **D-112:** EXP-20261004-01 is a deterministic `.pt` evaluation (spread below 0.001, no repeats); engine-build and seed variance are measured with the first candidate on those paths. **D-113:** improve = overall AP gain ≥ max(+0.010, 2×spread), small-person AP@0.5 gain ≥ max(+0.020, 2×spread), D-077 floor holds; provisional. **D-114:** `scripts/run_baseline.py` is historical (last working `2478588`; broken since `a0aba1c`; #154 closed by this PR). **D-115:** EXP-20261115-01 is one run at 768, not a sweep; any further imgsz needs owner approval. **D-116:** model swaps blocked until the owner lifts it.

## Open (owner)

1. **ADR-0020** open questions Q38–Q41, Q46–Q49 (safe defaults recorded). **Q41** is done (#118).
2. **Q39:** NARRATIVE tier. ADR-0023 recommends the deterministic template as the default narrative, so no hosted narrative route exists yet.
3. **Q54** is answered (durable store; K3). **Q55–Q57:** research polish. **Q67:** curated evidence is never staleness-filtered. **Q65–Q66:** fetcher redirects; `truncated` flag ignored (Q63–Q64 reserved for K1).
4. **Q59 to Q62** (safe defaults recorded): water-fill fairness for the §7.3 comparison; reference `task_support` always empty; rationale E-ordinals not mapped to item IDs; selection builder uses the 24,000 default, not the configured `max_input_chars`.
5. **Q32** (a) variance for engine builds and training seeds only (c and d answered, D-113); **Q27**, **Q31**, **Q33** (typed identities); annotation labels for ranks 011, 013, 027.

## Next actions

0. **Issue B** (B1 #162 merged; B2 #163 merging), then the EXP-20261115-01 verdict via `scripts/compare_candidate.py` (**Issue C**, #160, D-118, merged). The run on the Linux PC after the proposal's preflight.
1. The owner's re-run of `research --live` on the YOLO11 page (the HTML-to-text fix has merged).
2. **K4b** (a production caller of `select_candidate`, fail-closed on a missing store; owner to brief).
3. ADR-0023 §7.3: the SELECTION route switch still needs a production caller of `select_candidate` and a recorded comparison against the deterministic ranker.
4. The owner's first real `cv-agent research --live` run (needs a key, `llm-log init` and `knowledge init`).

## Do not start yet

All persisted routes stay `offline`; `research --live` is the only way to reach a hosted tier, and only for EXTRACTION. `selection` and `narrative` send `PROJECT_DATA` and stay refused (Q40). Any GPU run without a cost estimate and an approval reference bound to one experiment and cost ceiling. A real training runtime (needs its own issue). Model swaps: blocked until the owner lifts it. Any further imgsz beyond 768 (a sweep). NMS or crowd experiments. TensorRT, DeepStream, Model Optimizer. Stopping another project's processes. Any local LLM tier or GPU contact by the gateway (D-091).
