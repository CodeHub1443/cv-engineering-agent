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
| EXP-20261001-01 | At conf=0.10, does lowering threshold recover missed TPs (recall↑, mAP≈stable) vs adding noise (FP↑, mAP↓)? | EXP-20260930-01 | yolo11n (yolo11n.pt, 2.6M params, 6.5 GFLOPs) | coco-val2017-5k | FP16 (torch+cu121) | RTX 3060 12GB | **proposed** | — | — | — | — | — | — | awaiting owner approval to execute |
| EXP-20261001-02 | At conf=0.15, same hypothesis as above | EXP-20260930-01 | yolo11n (yolo11n.pt) | coco-val2017-5k | FP16 | RTX 3060 12GB | **proposed** | — | — | — | — | — | — | awaiting owner approval |
| EXP-20261001-03 | At conf=0.25 (control — same as EXP-20260930-01), confirm reproducibility of baseline result | EXP-20260930-01 | yolo11n (yolo11n.pt) | coco-val2017-5k | FP16 | RTX 3060 12GB | **proposed** | — | — | — | — | — | — | awaiting owner approval |
| EXP-20261001-04 | At conf=0.50, does raising threshold improve precision at cost of recall? | EXP-20260930-01 | yolo11n (yolo11n.pt) | coco-val2017-5k | FP16 | RTX 3060 12GB | **proposed** | — | — | — | — | — | — | awaiting owner approval |
