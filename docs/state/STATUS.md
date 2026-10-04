# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-10-04 · **Phase:** 5d — FP32 640 control persisted as `EXP-20261004-04` (measurement
only). Documentation reconciled. **Health:** green on repository tests (see JOURNAL for the last run).

## Where we are

Branch `feature/claude/experiment-provenance-recovery` (worktree `/home/dev/cv-engineering-agent-sweep`).
Committed on the branch. **Not pushed, not merged.**

**Ledger: 10 records.** SHA-256 of `experiments.sqlite` is `9251eb0c…8fef8fa` (it was `0d910b01…cfc1` before the
`EXP-20261004-04` write). Integrity check ok. Exactly one row was added on 2026-10-04.

**Done:**
- **EXP-20261004-01 series** persisted (measurement only): `-01` (640, SELF), `-02` (960), `-03` (1280), baseline
  `-01` for `-02` and `-03`. Commit `ab686f3`. Details: EXPERIMENTS.md.
- **EXP-20261004-04** persisted (FP32 640 control, measurement only). Baseline `-01`, commit `74a3cc2`, approval
  `EXP-20261004-FP32-640-RERUN-OWNER-20261004`. mAP@0.5:0.95 0.518; FPS 81.9. Details: EXPERIMENTS.md.
  - **Approval deviation:** the approval record was documented **after** the GPU run, not before it. It is recorded
    in JOURNAL as a post-execution entry. The gate was not satisfied before execution, and nothing claims otherwise.
  - **NoMachine exemption** (ADR-0018 §3.16, D-076): `/usr/NX/bin/nxnode.bin` was present during the run and exempt
    from the foreign-process rule. VRAM and timing are device-wide and include it.
- **Contaminated FP32 attempt** quarantined by rename at `/home/dev/cv-engineering-evidence/EXP-20261004-FP32-640/contaminated-concurrent-gpu/`.
  Read-only, manifest verified. **Not ledger-eligible, permanently.** Its approval reference is consumed.
- **ADR-0018:** Accepted (D-075), amended for the NoMachine exception (D-076), linked to issue #74. Issue #74 is open.
- **GPU-process provenance** is implemented: snapshots at start, during polling and at end, recorded in run.json.
  The writer rejects missing, unreadable or foreign snapshots. The 1-second polling limit is documented.

**Interpretation (descriptive only):** at 640, the FP32 control and the FP16-requested run agree within about 0.001
on every accuracy value reported. This is one comparison and does not decide FP16 vs FP32. No winner, no threshold.

## Open (owner)

1. **D-069** — whether any AP change should drive a decision. Answered for the FP32 control only (measurement-only).
   Stays OPEN generally.
2. **Q30** — precision floor and operating point. "Not yet." Stays OPEN. Needed before any production choice.
3. **Q31** — repository versus skill ownership of the trt-perf-analysis contract. Stays OPEN.
4. **Q27** — official size-stratified mAP needs `instances_val2017.json`. Stays OPEN.

## Blockers

None for the repository. Any production or precision decision waits on Q30 and D-069.

## Next actions

1. Owner: review EXP-20261004-04 and decide whether to close issue #74.
2. Owner: decide whether any further GPU series is wanted. Any run needs a fresh approval reference and a clean
   GPU process check (ADR-0018 §6).

## Do not start yet

Any GPU job without a fresh owner approval reference. Training. Model swaps (Q25). NMS or crowd experiments.
TensorRT, DeepStream, Model Optimizer. Stopping or controlling another project's processes. Pushing or
merging this branch without owner review.
