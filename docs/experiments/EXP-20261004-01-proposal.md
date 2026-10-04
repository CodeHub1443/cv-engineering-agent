# EXP-20261004-01 — Inference resolution: measurement-only (PROPOSED, NOT RUN)

**Status:** proposed, not executed. **Revised:** 2026-10-04 (second revision). No pass/fail criteria are defined in this revision. See §7.
**Approval:** required before running. A three-setting grid is a sweep, which `docs/APPROVALS.md` gates (⛔ always).
**Baseline:** EXP-20260930-01, legacy truncated protocol, reference only. **Control:** the 640 run in §3, new, Q28 protocol.
**Depends on:** ADR-0015 (diagnosis; branch `feature/claude/diagnosis-baseline`, PR #71, not on this branch).

## 1. Evidence

Measured on saved `predictions.json` files. Recall is IoU ≥ 0.5 at conf = 0.25. That value is a **reference point**, not an operating point (Q30 is open). COCO val2017, class person, 10,777 GT persons.

| Stratum (normalized GT area) | GT share | Recall @0.25 (reference) | Share of misses |
|---|---|---|---|
| small (< 0.0025) | 23.7% (2,552) | 0.268 | **52.5%** (1,869 of 3,559) |
| medium | 34.2% (3,689) | 0.656 | 35.7% |
| large | 42.1% (4,536) | 0.907 | 11.8% |

- **Small persons are the strongest measured failure mode** at this reference point: about half of misses, from under a quarter of ground truth.
- **No evidence of an independent crowd failure mode.** Dense images (> 5 GT persons) have recall 0.606, against 0.782 for sparse. Within size bins the difference is small at conf 0.25 (large 0.907 vs 0.908, medium 0.654 vs 0.663, small 0.262 vs 0.290). At conf 0.10 the small-object difference reverses sign (dense 0.437, sparse 0.400). The residual has not been tested for significance. ADR-0015's "677 high-density images contain 64% of GT persons" is a prevalence statistic, not a failure rate.
- **Fully missed images are a small share of misses.** The 161 fully missed images (ADR-0015) hold 344 persons, about 10% of misses.
- **Threshold alone does not close the small-object gap.** At conf 0.10, small recall is 0.430 (EXPERIMENTS.md, sweep result).

## 2. Question (not a hypothesis with a pass/fail bar)

Under the standard protocol (conf = 0.001), how does small-, medium- and large-person AP@0.5 change when inference image size changes from 640 to 960 and 1280? The measurement is intended to inform the owner's next decision. It does not decide one by itself.

Expected direction, stated as an expectation to observe, not as an established mechanism: a larger input gives small persons more feature-map cells, so small-object AP may rise. Medium and large AP may move too, and the measurement will report them.

## 3. Controlled variables

- **Protocol:** `conf = 0.001` for every run (Q28, D-067).
- **Model:** `yolo11n.pt`, the same file for every run. Record its sha256 in the run notes.
- **Dataset:** `coco-val2017-5k`, `classes=[0]`, 5,000 images. The same split as the baseline.
- **Device, batch and precision:** `device=0` (RTX 3060 12 GB), `batch=1`, `half=True` (FP16, passed explicitly so precision is a recorded setting, not an assumed default).
- **NMS IoU and `max_det`:** ultralytics defaults. The binding does not expose NMS IoU.
- **Software:** Ultralytics 8.4.138, Python 3.10, torch 2.5.1+cu121, as in existing runs.
- **Commit and provenance:** the run must execute from a **clean, committed** worktree. The provenance rule (`cv_agent/experiments/provenance.py`) refuses otherwise.

## 4. Independent variable

`imgsz ∈ {640 (control), 960, 1280}`. Nothing else varies.

## 5. Dataset

`coco-val2017-5k` only. No new data, no training data, no augmentation.

## 6. Metrics (all reported, none gated)

- **Threshold-free AP@0.5** for small, medium and large persons, from the full curve (`stratum_ap50`, `scripts/run_fixed_threshold_strata.py`). Approximate: predicted-box area, greedy matching, no COCO area-range prioritisation. Not the COCO evaluator.
- **Standard mAP@0.5 and mAP@0.5:0.95** at conf 0.001 (ultralytics summary).
- **Reference only:** fixed-threshold precision and recall at conf 0.25, and dense/sparse recall at 0.25. Labelled as reference, not as mAP and not as an operating point (Q30 open).
- **System, reported:** inference-only and end-to-end latency, FPS, peak VRAM. Target hardware is not decided (Q25).

## 7. Success criteria: none defined

This revision defines **no** pass/fail criteria and no magnitudes. The earlier proposal's values (+0.05 small-object AP, ≤0.02 guardrails, a precision floor of 0.726) were planning numbers, not established requirements, and they are withdrawn. Specifically:

- No precision floor, recall target, or operating point is defined (Q30 is open).
- No AP gain is set as the bar for any next step.

**Decision for the owner (before a run, if the run is to inform a decision):** what AP@0.5 change for small persons, and what guardrail on medium and large persons, would justify the next step? Without that, the experiment is measurement-only: it reports the numbers and changes no decision by itself.

## 8. Expected cost and resources

- **Compute:** three `yolo val` runs over 5,000 images. The 640 runs took 46–50 s wall each (measured in the ledger). 960 and 1280 are **not measured**. Estimate: 1.5–3 min each. Total GPU wall about 5–10 min, roughly 0.1–0.2 GPU-hours (estimate).
- **VRAM:** 614–695 MiB peak at 640 (measured). Higher at 1280 (unmeasured).
- **Storage:** `predictions.json` at conf 0.001 is much larger than the 6.8 MB conf 0.10 file. Expect tens of MB per run (estimate).
- **Human:** commit the reviewed changes (so the tree is clean), restore the prerequisites (§10), and run the commands in §11.
- **Approval:** required. Present this estimate, including that 960 and 1280 are unmeasured.

## 9. Why this experiment, and not the alternatives

- **A (targeted training or augmentation):** not justified now. It is training (⛔ approval; GPU-hours unknown until a measured epoch). It would be considered only after the owner has a decision criterion (§7) that resolution alone cannot meet.
- **B (RT-DETR, TAO, another model):** not justified yet. Only one model has been measured, so there is no evidence the architecture is the limit. Target latency and memory are unknown (Q25; `[P§12]`). Newer is not evidence of better (`[P§29.3]`).
- **C-other (NMS IoU, `max_det`):** no evidence of a crowd mechanism (§1), so not justified now.
- **Crowd-specific experiment:** not justified. The measured density effect is explained by size composition.

## 10. Readiness

| Item | Status |
|---|---|
| Q28 protocol (eval default 0.001, test) | done, uncommitted |
| Threshold-free AP instrument (with tests) | done, uncommitted |
| Provenance refusal and commit capture on execute paths | done, uncommitted; takes effect only from a clean tree |
| Committing the reviewed changes | **owner decision**: a run cannot start from a dirty tree. The analysis script must be in that commit too (§11 runs it from the same commit) |
| ADR-0016 (experiment provenance; new module `cv_agent/experiments/provenance.py`) | drafted, owner review |
| Restoring `yolo11n.pt` and `coco-person-val.yaml` from Trash | **prerequisite**, LEDGER-RECOVERY.md §4 (owner approval) |
| Ledger restore (Q29) | **owner approval**; required to record a completed row |
| Record-writing path (verifier, writer, wrapper; ADR-0017) | done on the feature branch, 35 tests; owner acceptance of ADR-0017 before the first real run |
| Owner decision on criteria (§7) | **open**. Needed only if the run is to drive a decision |
| Q30 operating point | **OPEN**. Not needed for measurement-only |

## 11. Commands (use only after final owner approval; NOT run)

Preconditions: owner approval (§8) with an approval id; the reviewed changes committed and the
code tree clean (`feature/claude/experiment-provenance-recovery`); `yolo11n.pt` and
`coco-person-val.yaml` present in the main checkout's `.cv_agent/` (restored 2026-10-04).

The wrapper refuses a dirty tree and never overwrites a run directory. Each run writes
`<project>/<name>/predictions.json`, `<project>/<name>.val.log` and `<project>/<name>.run.json`. The
writer verifies all three runs and records them only if every check passes (ADR-0017). Nothing is
written if any run fails. Use `--dry-run` first.

```bash
cd /home/dev/cv-engineering-agent-sweep        # committed, clean feature branch
for SZ in 640 960 1280; do
  python3 scripts/run_yolo_val_measured.py --imgsz $SZ
done

STATE=/home/dev/cv-engineering-agent/.cv_agent/evaluations
python3 scripts/record_evaluation_runs.py --approval-ref "<owner approval id>" \
  --run 640=$STATE/e1-yolo11n-coco-val2017-imgsz640-conf0001 \
  --run 960=$STATE/e1-yolo11n-coco-val2017-imgsz960-conf0001 \
  --run 1280=$STATE/e1-yolo11n-coco-val2017-imgsz1280-conf0001 \
  --dry-run
# Review the printed records. Then run the same command without --dry-run to write them.
```

Each run must show a full curve, and the writer checks that for every predictions file. A
`TRUNCATED` message is a refusal, not a warning.

## 12. Stop conditions

Stop and report, changing no existing record, if:
- the 640 control does not run cleanly at conf 0.001, or its `predictions.json` is not full-curve;
- the tree was dirty at launch (the gate in §11 fires);
- the prerequisite files are not restored and verified.
