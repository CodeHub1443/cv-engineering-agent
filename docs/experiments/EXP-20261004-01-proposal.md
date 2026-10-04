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
- **Device and batch:** `device=0` (RTX 3060 12 GB), `batch=1`, FP16 (ultralytics default on CUDA).
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
| Record-writing script for this experiment | **not written**. The §11 commands write no ledger row |
| Owner decision on criteria (§7) | **open**. Needed only if the run is to drive a decision |
| Q30 operating point | **OPEN**. Not needed for measurement-only |

## 11. Command for EXP-20261004-01 (use only after final owner approval; NOT run)

Prerequisites: owner approval of this run (§8); the reviewed changes committed on the feature branch
`feature/claude/experiment-provenance-recovery`; `yolo11n.pt` and `coco-person-val.yaml` present in
the main checkout's `.cv_agent/` (restored 2026-10-04 under LEDGER-RECOVERY.md §4a).

The gate refuses a dirty code worktree, so the run cannot use uncommitted code. The state root is the
main checkout's `.cv_agent/` (ADR-0016 §3), which every worktree resolves to. These commands write
prediction files only. They write **no ledger row**. A ledger record needs a record-writing script
through the execute path, which does not exist yet (see §10).

```bash
CODE=/home/dev/cv-engineering-agent-sweep        # feature worktree: the code the analysis runs from
STATE=/home/dev/cv-engineering-agent/.cv_agent    # state root (main checkout), per ADR-0016
YOLO=/home/dev/.local/bin/yolo
MODEL=$STATE/models/yolo11n.pt
DATA=$STATE/evaluations/coco-person-val.yaml
OUT=$STATE/evaluations

# Provenance gate: clean, committed code only (same rule as cv_agent.experiments.provenance)
if [ -n "$(git -C "$CODE" status --porcelain --untracked-files=normal)" ]; then
  echo "REFUSED: dirty worktree; commit first"; exit 1
fi
COMMIT=$(git -C "$CODE" rev-parse HEAD)
echo "running from commit $COMMIT"

for SZ in 640 960 1280; do
  $YOLO val model=$MODEL data=$DATA 'classes=[0]' conf=0.001 imgsz=$SZ \
      batch=1 device=0 project=$OUT name=e1-yolo11n-coco-val2017-imgsz$SZ-conf0001
done

cd "$CODE"
python3 scripts/run_fixed_threshold_strata.py \
  --coco-root /home/dev/Documents/data_cleaner/datasets/coco \
  --run "E1-640=$OUT/e1-yolo11n-coco-val2017-imgsz640-conf0001/predictions.json" \
  --run "E1-960=$OUT/e1-yolo11n-coco-val2017-imgsz960-conf0001/predictions.json" \
  --run "E1-1280=$OUT/e1-yolo11n-coco-val2017-imgsz1280-conf0001/predictions.json" \
  --threshold 0.25
```

Each run must print `[full-curve]`. A `TRUNCATED` flag means the file is not at conf 0.001 and is invalid for this experiment.

## 12. Stop conditions

Stop and report, changing no existing record, if:
- the 640 control does not run cleanly at conf 0.001, or its `predictions.json` is not full-curve;
- the tree was dirty at launch (the gate in §11 fires);
- the prerequisite files are not restored and verified.
