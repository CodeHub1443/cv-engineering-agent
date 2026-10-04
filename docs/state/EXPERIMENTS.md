# EXPERIMENT LEDGER

> **Append-only.** Every training, benchmark, or optimization run gets a row. A run whose
> metadata is incomplete **is not a valid result** and may not be cited in an ADR, a PR,
> or a recommendation `[P§25]`, `[P§29.5]`.
>
> This file exists so the agent can answer *"why did we choose this model?"* from record
> rather than from conversational memory `[P§25]`.
>
> **Relationship to `cv_agent/experiments/` (ADR-0011, `OPEN_QUESTIONS.md` Q16,
> resolved 2026-09-24):** this file remains the authoritative, human-facing definition
> of the schema and rules below. `cv_agent.experiments` is the machine-readable
> SQLite-backed ledger that enforces this exact schema in code (`ExperimentRecord`,
> `ExperimentLedger`, `SqliteExperimentLedger`) — it does not replace or redefine
> this file, and nothing writes real rows to it yet (no training/evaluation subsystem
> exists to call it). If this schema changes, `cv_agent/experiments/models.py` must
> change with it.

## Rules

1. One row per run. Never edit a row after the run completes — errors are corrected by a
   new row plus a note.
2. Every run names the **baseline** it is compared against `[P§29.2]`. The first run in a
   project is the baseline and says so.
3. Accuracy metrics without system metrics are incomplete `[P§12]`, `[P§29.4]`. A model
   at 99% mAP that runs at 2 FPS on the target when 20 FPS is required is a failed run,
   not a good one.
4. Every run links to its config, dataset version, and commit SHA. Reproducible or void.
5. Runs above the approval thresholds in `docs/APPROVALS.md` link their approval record.

## Schema `[P§25]`

| Field | Notes |
|---|---|
| `exp_id` | `EXP-YYYYMMDD-NN` |
| `parent_exp_id` | the run this one was forked/derived from, or blank if none. Distinct from `baseline_id`: parent is lineage, baseline is what the result is compared against — they may differ |
| `status` | `proposed` / `running` / `completed` / `failed` / `cancelled` |
| `hypothesis` | what this run is testing, stated before it runs |
| `success_criteria` | the measurable bar this run must clear to be judged a success, stated before it runs |
| `baseline_id` | the run being compared against, or `SELF` for a baseline |
| `commit` | code SHA |
| `approval_ref` | the `docs/APPROVALS.md` approval record id, if this run required one — blank if the run was free per the approval table |
| `created_at`, `completed_at` | ISO-8601 timestamps |
| `model` | architecture + variant + weights origin |
| `dataset_version` | manifest id from `docs/DATA.md` |
| `input_resolution` | |
| `batch_size` | |
| `optimizer`, `lr`, `scheduler` | |
| `augmentations` | reference to config, not prose |
| `epochs` | |
| `precision` | FP32 / FP16 / INT8 (+ PTQ or QAT) |
| `hardware` | training hardware **and** target hardware |
| `params`, `flops` | |
| `train_time`, `gpu_hours` | |
| `val_metrics` | per `docs/EVALUATION.md` |
| `test_metrics` | |
| `latency` | end-to-end **and** inference-only, on target `[P§12]` |
| `fps` | on target, at production stream conditions |
| `memory` | VRAM + RAM |
| `power` | where target is Jetson/edge |
| `failure_analysis` | link to the analysis, not a number `[P§27]` |
| `decision` | what this run caused us to do next |
| `notes` | |

## Artifacts and decisions produced by a run

A run's outputs (configs, checkpoints, reports) are referenced by URI + content hash
from the row that produced them, not embedded in this file. A run's `decision` field
is a short phrase here; if the decision merits its own record, add one line to
`docs/state/DECISIONS.md` (its existing lightweight, append-only, one-line format —
this file does not define a separate, heavier decision schema).

## Runs

The table below is a condensed rollup view for scanning; full row records live in
`cv_agent.experiments`'s SQLite ledger (ADR-0011, `OPEN_QUESTIONS.md` Q16 resolved).

| exp_id | hypothesis | baseline | model | dataset_ver | precision | target hw | mAP@.5:.95 | recall | FPS | latency | VRAM | power | gpu_h | decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EXP-20260929-01 | YOLO11n + ByteTrack can detect+track persons in real-time video on Linux/NVIDIA GPU, serving as the first measurable baseline for D-043 | SELF | yolo11n (yolo11n.pt, 2.6M params, 6.5 GFLOPs, AGPL-3.0) | person_detection_sample.mp4 (640×360, H.264, 25fps, 114.5s, 2862 frames) | FP16 (torch +cu121) | RTX 3060 12GB | — (not measured) | — | — | 8.8ms inference/frame (7.4ms run 1) | 12042MiB avail; usage not profiled | N/A (desktop) | — | first baseline established; measure val_metrics next |
| EXP-20260930-01 | yolo11n achieves mAP@0.5:0.95 > 0.30 on COCO val2017 person class | EXP-20260929-01 | yolo11n (yolo11n.pt, 2.6M params, 6.5 GFLOPs, AGPL-3.0) | coco-val2017-5k (5000 images, CC BY 4.0) | FP16 (torch +cu121) | RTX 3060 12GB | **0.459** | 0.661 | 99.9 e2e / 188.7 inf-only | 6.4ms e2e (0.4 pre+5.3 inf+0.7 post) | 596 MiB peak (360 baseline) | N/A (desktop) | — | D-043 eval milestone complete; yolo11n confirmed viable baseline |

### EXP-20260929-01 — full record

| Field | Value |
|---|---|
| `exp_id` | EXP-20260929-01 |
| `parent_exp_id` | — |
| `status` | completed |
| `hypothesis` | YOLO11n with ByteTrack can detect and track persons in a real-time video stream on a Linux/NVIDIA GPU host, serving as the first measurable baseline for the Person Detection + Tracking reference task (D-043) |
| `success_criteria` | yolo track exits 0; annotated video and per-frame tracking labels produced in output_dir/run_name/; no exception or crash |
| `baseline_id` | SELF |
| `commit` | branch `feature/claude/adr-0009-second-binding` @ 6934bdb (D-055 + D-056 + D-057 + D-058) |
| `approval_ref` | Tanvir instruction 2026-09-29: "execute the FIRST REAL baseline" (D-047 scoped exception to Q6/Q19) |
| `created_at` | 2026-09-29T11:39:07.836369+00:00 |
| `completed_at` | 2026-09-29T11:40:07.851557+00:00 |
| `model` | yolo11n — Ultralytics YOLO11 nano; yolo11n.pt (100 layers, 2,616,248 params, 6.5 GFLOPs); AGPL-3.0 |
| `dataset_version` | person_detection_sample.mp4 · 640×360 H.264 25fps 114.5s 2862 frames · local fixture |
| `input_resolution` | 384×640 (YOLO auto-padded from 640×360 source) |
| `batch_size` | 1 (streaming video inference) |
| `optimizer` | N/A (inference only) |
| `epochs` | N/A (inference only) |
| `precision` | FP16 via torch 2.5.1+cu121 on CUDA 12.1 |
| `hardware` | training=N/A; target=NVIDIA GeForce RTX 3060 12GB, driver 535.309.01, CUDA 12.2, Python 3.10.12, torch 2.5.1+cu121 |
| `params` | 2,616,248 |
| `flops` | 6.5 GFLOPs |
| `train_time` | 60.1s wall time (subprocess + drain threads + ledger write) |
| `gpu_hours` | not profiled (V1 limitation — no GPU profiling in LinuxNvidiaJobRuntime) |
| `val_metrics` | not measured in this run |
| `test_metrics` | not measured in this run |
| `latency` | preprocess 0.7ms · inference 8.8ms · postprocess 1.4ms per frame at (1,3,384,640) |
| `fps` | ~90 FPS sustained (8.8ms inference × 2862 frames / 25.2s GPU time estimated); not measured separately |
| `memory` | VRAM: 12042MiB available; peak not profiled; RAM not profiled |
| `power` | not measured |
| `failure_analysis` | none — run completed successfully |
| `artifacts` | `.cv_agent/baselines/baseline-yolo11n-person-track-20260929-2/` · `person_detection_sample.avi` · `labels/` (2601 txt files — frames with ≥1 detection) |
| `decision` | first baseline established; next steps: measure mAP/recall on a labelled split, measure true FPS end-to-end, profile VRAM |
| `notes` | SelectionRecommendation: yolo11n, confidence=insufficient_evidence, is_proposal=True (D-053). 2601/2862 frames had detections (91%). Pipe-buffer deadlock fixed in D-058 before this run. open_ledger positional-arg bug fixed in D-059. Run directory auto-incremented to -2 because prior failed attempt created the base directory. |

### EXP-20260930-01 — full record

| Field | Value |
|---|---|
| `exp_id` | EXP-20260930-01 |
| `parent_exp_id` | — |
| `status` | completed |
| `hypothesis` | YOLO11n (D-053 recommendation) achieves non-trivial person detection accuracy (mAP@0.5:0.95 > 0.30) on COCO val2017, confirming it as a viable baseline for the D-043 reference task |
| `success_criteria` | yolo val exits 0; mAP@0.5:0.95 > 0.30 for person class; FPS > 20 on RTX 3060; metrics written to ledger |
| `baseline_id` | EXP-20260929-01 |
| `commit` | branch `feature/claude/adr-0009-second-binding` (D-060 + D-061 + D-062) |
| `approval_ref` | Tanvir instruction (evaluation milestone, D-043) — `approved=True` set in scripts/run_evaluation.py |
| `created_at` | 2026-09-30 (evaluation run executed ~14:04 UTC) |
| `completed_at` | 2026-09-30 (wall_time=50.0s) |
| `model` | yolo11n — Ultralytics YOLO11 nano; yolo11n.pt (100 layers, 2,616,248 params, 6.5 GFLOPs); AGPL-3.0 |
| `dataset_version` | coco-val2017-5k — Microsoft COCO 2017 val split, 5000 images (2693 with person annotations), CC BY 4.0, cocodataset.org. Labels from ultralytics/assets coco2017labels.zip. Held-out from yolo11n training (pre-trained on COCO train2017). |
| `input_resolution` | 640×640 (YOLO auto-padded/resized from original COCO images) |
| `batch_size` | 1 |
| `optimizer` | N/A (inference only) |
| `epochs` | N/A (inference only) |
| `precision` | FP16 via torch 2.5.1+cu121 on CUDA 12.1 |
| `hardware` | training=N/A; target=NVIDIA GeForce RTX 3060 12GB, driver 535.309.01 / CUDA 12.1, Python 3.10.12, torch 2.5.1+cu121 |
| `params` | 2,616,248 |
| `flops` | 6.5 GFLOPs |
| `train_time` | N/A (inference only) |
| `gpu_hours` | N/A |
| `val_metrics` | **precision=0.791, recall=0.661, mAP@0.5=0.635, mAP@0.5:0.95=0.459** (person class, classes=[0], conf=0.25, 5000 images, 10777 instances) |
| `test_metrics` | not measured (same split used for eval) |
| `latency` | preprocess 0.4ms · inference 5.3ms · postprocess 0.7ms per image → end-to-end 6.4ms |
| `fps` | 99.9 FPS end-to-end (5000 images / 50.0s wall); 188.7 FPS inference-only (1000ms / 5.3ms) |
| `memory` | VRAM peak=596 MiB; VRAM baseline=360 MiB; delta=236 MiB; RAM not profiled |
| `power` | not measured |
| `failure_analysis` | none — exit 0. `faster-coco-eval` secondary check skipped (instances_val2017.json not downloaded); primary box P/R/mAP metrics are valid and complete. |
| `artifacts` | `.cv_agent/evaluations/eval-yolo11n-coco-val2017-20260930-2/` · `predictions.json` · `eval-yolo11n-coco-val2017-20260930-2.csv` (YOLO run outputs) · `.cv_agent/experiments.sqlite` |
| `decision` | D-043 evaluation milestone complete. yolo11n person detection confirmed viable on COCO val2017 (mAP@0.5:0.95=0.459, FPS=99.9 on RTX 3060). Baseline EXP-20260929-01 now has a labelled accuracy companion. |
| `notes` | yolo val command: `yolo val model=yolo11n.pt data=coco-person-val.yaml classes=[0] conf=0.25 imgsz=640 batch=1 device=0`. "all" and "person" rows in yolo val output have identical metrics because classes=[0] filters evaluation to only person class. YAML required `train:` key (added, pointing to val2017.txt) to pass ultralytics check_det_dataset. Run directory auto-incremented to -2 because first attempt (missing train: key) created the base directory before failing. |
| EXP-20261001-01 | conf=0.10 — does lowering threshold recover missed persons? | EXP-20260930-01 | yolo11n (yolo11n.pt) | coco-val2017-5k | FP16 | RTX 3060 12GB | **0.495** ⚠ conf-truncated, see [sweep result](#sweep-result--exp-20261001-0104-completed-2026-10-02) | 0.651 (ultralytics, max-F1 point) · **0.773 at conf=0.10** (fixed-threshold matcher, P=0.541) | 108.6 (wall) | 6.2 e2e / 5.3 inf | 695 MiB peak | N/A | — | fixed-threshold recall +10.3 pts, precision −23.5 pts; mAP rise is a protocol artifact, not a finding |
| EXP-20261001-02 | conf=0.15 — same question | EXP-20260930-01 | yolo11n (yolo11n.pt) | coco-val2017-5k | FP16 | RTX 3060 12GB | **0.483** ⚠ conf-truncated | 0.651 (ultralytics) · 0.733 at conf=0.15 (fixed-threshold matcher, P=0.642) | 108.6 (wall) | 6.2 e2e / 5.3 inf | 668 MiB peak | N/A | — | as above; intermediate point on the same trade-off curve |
| EXP-20261001-03 | conf=0.25 — control, reproduce baseline | EXP-20260930-01 | yolo11n (yolo11n.pt) | coco-val2017-5k | FP16 | RTX 3060 12GB | **0.459** (identical to baseline) | 0.661 (identical to baseline) | 108.6 (wall) | 6.2 e2e / 5.3 inf | 615 MiB peak | N/A | — | **baseline reproduced exactly** (P, R, mAP50, mAP50-95 all equal); harness deterministic at this config |
| EXP-20261001-04 | conf=0.50 — does raising threshold trade recall for precision? | EXP-20260930-01 | yolo11n (yolo11n.pt) | coco-val2017-5k | FP16 | RTX 3060 12GB | **0.390** ⚠ conf-truncated | 0.521 (ultralytics) · 0.521 at conf=0.50 (fixed-threshold matcher, P=0.927) | 108.6 (wall) | 6.2 e2e / 5.3 inf | 614 MiB peak | N/A | — | yes, trade-off confirmed: precision 0.927 at recall 0.521; small-object recall falls to 0.104 |
| EXP-20261004-01 | (PROPOSED, not run; measurement-only, no pass/fail criteria) imgsz 640→960→1280 at the Q28 protocol (conf=0.001): report threshold-free AP@0.5 by size, mAP, and reference P/R | 640 control at conf=0.001 (new; not EXP-20261001-03) | yolo11n (yolo11n.pt) | coco-val2017-5k | FP16 | RTX 3060 12GB | **proposed** | — | — | — | — | — | — | awaiting owner approval and §10 prerequisites — see [proposal](../experiments/EXP-20261004-01-proposal.md); not yet in SQLite |

### Sweep result — EXP-20261001-01..04 (completed 2026-10-02)

Ledger values (`.cv_agent/experiments.sqlite`, read-only). "Fixed-threshold" columns come
from `scripts/run_fixed_threshold_strata.py` on each run's saved `predictions.json`:
IoU ≥ 0.5, greedy score-ordered matching, predictions with score ≥ threshold only. This
is not the COCO evaluator.

| run | conf | ultralytics P | ultralytics R | mAP@.5 | mAP@.5:.95 | fixed P | fixed R | fixed small R | fixed dense R |
|---|---|---|---|---|---|---|---|---|---|
| EXP-20260930-01 (baseline) | 0.25 | 0.791 | 0.661 | 0.635 | 0.459 | 0.776 | 0.670 | 0.268 | 0.606 |
| EXP-20261001-01 | 0.10 | 0.809 | 0.651 | 0.709 | 0.495 | 0.541 | **0.773** | **0.430** | 0.734 |
| EXP-20261001-02 | 0.15 | 0.809 | 0.651 | 0.685 | 0.483 | 0.642 | 0.733 | 0.364 | 0.685 |
| EXP-20261001-03 | 0.25 (control) | 0.791 | 0.661 | 0.635 | 0.459 | 0.776 | 0.670 | 0.268 | 0.606 |
| EXP-20261001-04 | 0.50 | 0.927 | 0.521 | 0.514 | 0.390 | 0.927 | 0.521 | 0.104 | 0.423 |

**Findings (measured):**

1. **Control reproduces the baseline exactly** (EXP-20261001-03 = EXP-20260930-01 on all
   four ultralytics metrics). The harness is deterministic at this configuration.
2. **Recall at a fixed threshold does improve with lower conf.** Fixed-threshold recall
   goes 0.670 (conf=0.25) → 0.773 (conf=0.10), a +10.3-point gain, paid for by precision
   0.776 → 0.541. The earlier statement "recall does not improve over the baseline" is
   **only true at ultralytics' reported operating point**, not at a fixed threshold (see
   finding 4). It should not be cited as the threshold result.
3. **The mAP@.5:.95 ranking is a measurement artifact, not evidence that conf=0.10 is
   optimal.** The binding runs `yolo val` at `conf=0.25` (`DEFAULT_CONF` in
   `yolo_eval.py`). Ultralytics' validation default is `conf=0.001`. Verified on the saved
   files: the baseline's lowest person score is exactly 0.2500 with zero predictions below
   it; the conf=0.10 run contains 6,100 person predictions below 0.25. The PR curve is built
   from what survives the threshold, so mAP rises monotonically as conf falls
   (0.390 → 0.459 → 0.483 → 0.495). 0.495 is the best of the four tested points, not an
   optimum. Under the standard protocol the true mAP is unmeasured, and **the baseline's
   0.459 understates it.** Do not compare 0.459 with published yolo11n numbers.
4. **Ultralytics P and R are not values at the `conf` threshold.** `ap_per_class` reports
   the max-F1 point of each curve (`ultralytics/utils/metrics.py`). This explains why
   ultralytics recall at conf=0.10 (0.651) looks lower than at conf=0.25 (0.661), when the
   fixed-threshold recall rises. The fixed-threshold columns are the right comparison.
5. **Threshold alone is not an adequate recall fix.** Conf=0.10 lifts small-object recall
   only from 0.268 to 0.430, so 57% of small persons are still missed, and it costs 23.5
   points of precision. Whether any point on this curve is acceptable depends on a
   precision floor that the project has not defined (OPEN_QUESTIONS Q30).
6. **Conf=0.50 confirms the expected trade-off:** precision 0.927 at recall 0.521, and
   small-object recall 0.104.

**Evaluation protocol (Q28, accepted 2026-10-04, D-067):**

- **mAP is reported at `conf=0.001`** (standard ultralytics validation threshold). The
  `yolo_eval` binding default is now `0.001`.
- **Fixed-threshold precision and recall are a separate measurement**, produced by
  `scripts/run_fixed_threshold_strata.py`, and are labelled as such. They are never reported as mAP.
- **Threshold-free AP per size stratum** (`stratum_ap50`, same script) is computed from the
  full curve. It is valid only for files whose lowest score is ≤ 0.002 (the script flags others as TRUNCATED).
- **The operating point is not chosen.** Q30 is open. Nothing here sets a precision floor or a
  reported threshold.
- **Legacy values:** all mAP values at `conf=0.25` (EXP-20260930-01 and the sweep rows) are
  truncated-protocol values. They are not comparable with Q28-protocol mAP.
- **Script defaults:** `scripts/run_evaluation.py` (the mAP run) now configures `conf=0.001`. The
  historical EXP-20260930-01 row is unchanged, and a rerun would be refused as terminal anyway.
  `scripts/run_baseline.py` (tracking) keeps `conf=0.25`, an operating point (Q30 open).

**Corrections to earlier wording (2026-10-04):**

- **Ultralytics P and R are max-F1 values, not values at the `conf` threshold.** The "recall
  0.661" in EXP-20260930-01, and the 0.651 and 0.521 in the sweep rows, are the max-F1 point
  of each curve. They are not recall at conf=0.25 or at any other threshold. The fixed-threshold
  recall at conf=0.25 is **0.670** (IoU-matched analysis). Any statement that "recall does not
  change with conf" based on the ultralytics columns is wrong.
- **"Recall does not improve over the baseline" is withdrawn** for fixed-threshold recall. It
  holds only at ultralytics' max-F1 point. At a fixed threshold, recall rises from 0.670 to 0.773
  when conf goes 0.25 → 0.10, at a precision cost (see finding 2).
- **The diagnosis derived TP/FP/FN from the reported P/R** (ADR-0015 §5, limitation 1, on PR #71's
  branch). Those reported values are max-F1 points, so the derived counts are not counts at
  the conf=0.25 operating point. The IoU-matched analysis supersedes them for fixed-threshold
  statements. An erratum is drafted in ADR-0015 on PR #71's branch (uncommitted).
- **Crowding:** the earlier "crowd-related failure pattern" is withdrawn. ADR-0015's
  "677 high-density images contain 64% of GT persons" is a prevalence statistic, not a failure
  rate. The measured dense/sparse gap is explained by size composition (proposal §1).
- **Strongest current failure mode:** small persons, which are 52.5% of misses from 23.7% of GT
  (recall 0.268 at conf=0.25; 0.430 at conf=0.10).
- **"conf=0.10 gives the highest mAP"** is true only of the four legacy points tested. It is not
  a Q28-protocol result, and it is not an optimum.

**Precision correction (2026-10-04, ADR-0017 §3a). Historical FP16 labels are wrong.**

- **EXP-20260930-01 and the 20261001 sweep rows (EXP-20261001-01..04) ran FP32, not FP16.** Their
  `precision` field says "FP16", but no precision argument was supplied. Ultralytics `quantize`
  defaulted to None, so the model ran at FP32 (`engine/validator.py:191,195`). The historical rows are
  **not edited**. This note is the correction.
- **EXP-20261004-01 is FP16-requested via `quantize=16` and is NOT like-for-like with those runs.**
  Any precision comparison against EXP-20260930-01 or the sweep rows must say so. The precision label
  on new records is the requested setting, not a measured inference precision.
- **Precision of the new series is requested, not measured.** Ultralytics does not log actual inference
  precision. `half` is deprecated in 8.4.138 and is mapped to `quantize`, so the protocol uses `quantize=16`.
- The 640 control names EXP-20260930-01 as the legacy FP32 reference in its record notes.

**Validity status (`[P§25]` rules):**

- `commit_sha` is **NULL on all six ledger rows**, including the baseline. Rule 4 requires
  a commit SHA, so these rows cannot yet be reproduced from record. The sweep execute path
  does not pass `commit` into `job_result_to_experiment_record`. Corrections go in new rows
  (Rule 1); the existing rows are not edited.
- `dataset_version = coco-val2017-5k` is a name, not a registered `DatasetManifest` (Q26).
- The baseline row's `baseline_id` is `EXP-20260929-01` (a video-tracking run with no
  metrics), not `SELF`. Rule 2 wants the accuracy baseline to name itself. Q29.
- The `commit` field in the baseline's rollup entry names a branch, not a SHA.
- (Historical, as of 2026-10-04 before recovery; restored to the main checkout's `.cv_agent/` the same day, see LEDGER-RECOVERY.md §4a.) The ledger file had been in the Trash (`~/.local/share/Trash/files/cv-engineering-agent/.cv_agent/`),
  not in the repository. Its contents were read without modification.
- The `predictions.json` artifacts and the baseline eval directory are in the same Trash
  location.
- FPS (108.6 vs 99.9 for an identical workload) is run-to-run wall-clock variance, not a
  speed effect. Use inference-only latency (5.3 ms in every run) for speed comparisons.
- Only one model and one dataset. IoU 0.5 only. Matching is approximate (see above).
- **Inferred, not recorded, commits** (never written to `commit_sha`; see
  [LEDGER-RECOVERY.md](../experiments/LEDGER-RECOVERY.md) §5.2): EXP-20261001-01..04 ≈ `1531344`
  (most likely; the execute-time working tree is unknown). EXP-20260930-01 ≈ `8f29618`, but its
  code was **uncommitted at run time**: the `yolo_eval` binding first appears in `8f29618`, committed
  five minutes after the run. No single commit reproduces the baseline exactly.
