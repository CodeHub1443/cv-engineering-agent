# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-10-14 · **Phase:** 5d — measurement series persisted (10-record ledger); failure-analysis report
and code committed (#75); annotation-label review in progress (47 of 63 labelled).
**Health:** Last recorded full suite: 1755 passed, 4 skipped (JOURNAL, 2026-10-04). Not re-run this session. The #75
code (failure_analysis, annotation_review) has no recorded run in JOURNAL.

## Where we are

Branch `feature/claude/experiment-provenance-recovery` (worktree `/home/dev/cv-engineering-agent-sweep`).
Local HEAD was 2028ab1 when written; the origin tracking ref matched it as of a fetch on 2026-10-12 18:15 (+0600).
The remote was not re-checked after that fetch. Not merged. The report, JOURNAL and this file change in the commit
that follows 2028ab1 and were not pushed when written.

**Ledger: 10 records, unchanged** (sha256 `9251eb0c…8fef8fa`, full value in JOURNAL; integrity ok). No #75 row.

**Done:**
- **EXP-20261004-01..04** persisted (measurement only): `-01` (640, SELF), `-02` (960), `-03` (1280), `-04` (FP32 640
  control, baseline `-01`, mAP@0.5:0.95 0.518, FPS 81.9). Details: EXPERIMENTS.md.
  - **Approval deviation:** the `-04` approval record was documented **after** the GPU run. The gate was not
    satisfied before execution, and nothing claims otherwise.
  - A contaminated FP32 attempt is quarantined and **not ledger-eligible, permanently.** ADR-0018 accepted (D-075),
    NoMachine exemption D-076. Issue #74 was open as of 2026-10-04; its current state is not verified.
- **Failure analysis** (ADR-0015 §9, #75): report and code committed; read-only, descriptive, no GPU run; issue
  status not verified. Report: `docs/experiments/FAILURE-ANALYSIS-EXP-20261004.md`.
- **Annotation-label review** of 63 primary-sample candidates (50 high_conf_fp, 2 near_dup_gt_pair, 11
  degenerate_gt). Report: `docs/experiments/ANNOTATION-REVIEW-EXP-20261004-01.md`, reconciled to the CSV 2026-10-13.
  - **Labels:** valid_annotation 34, annotation_error 5, ambiguous 8, not_reviewable 0, crowd_region_unresolved 0,
    **unlabelled 16**. Single reviewer (Tanvir).
  - Ranks 001–050 were reviewed 2026-10-13. Ranks **011, 013, 027** have observation notes but **no assigned label**.
  - Ranks **025** (`annotation_error`, mapped from the owner's `invalid_annotation`) and **041** (`ambiguous`) were
    resolved by explicit owner confirmation.
  - Ranks **051–063** remain unreviewed and unlabelled.
  - Crowd status is `q27_unresolved` for all 63. The sample is **not representative** (fixed rules, seeded draw);
    no error rate is claimed. It contains no missed GT box, so it does not test the small-box bottleneck.

## Open (owner)

1. **D-069** — whether any AP change should drive a decision. Answered for the FP32 control only
   (measurement-only). Stays OPEN generally.
2. **Q30** — precision floor and operating point. "Not yet." Stays OPEN. Needed before any production choice.
3. **Q27** — official size-stratified mAP and crowd status need `instances_val2017.json`. Stays OPEN.
4. **Q31** — repository versus skill ownership of the trt-perf-analysis contract. Stays OPEN.

**Blockers:** none for the repository. Any production or precision decision waits on Q30 and D-069.

## Next actions

1. Owner: review the uncommitted report, journal and STATUS edits; approve a commit and push.
2. Owner: decide labels (or leave unlabelled) for ranks 011, 013, 027; decide whether to review ranks 051–063.
3. Owner: decide on issue #74 and any further GPU series (fresh approval reference, clean GPU check, ADR-0018 §6).

## Do not start yet

Any GPU job without a fresh owner approval reference. Training. Model swaps (Q25). NMS or crowd experiments.
TensorRT, DeepStream, Model Optimizer. Stopping or controlling another project's processes.
Pushing or merging this branch without owner review.
