# EXP-20261115-01 — Inference resolution 768: first optimisation candidate (PROPOSED; not run)

**Status:** proposed 2026-11-15, owner-approved as candidate C1 (D-115). Issue #157. No GPU run has happened and none starts until the code prerequisites in §10 are merged.
**Experiment id:** `EXP-20261115-01` (owner-fixed). **Approval reference:** `EXP-20261115-01-OWNER-20261115` (owner-issued under the D-080/D-087 standing grant; bound to this one experiment and the cost ceiling in §8).
**Candidate:** EXP-20261115-01, imgsz 768
**Baseline:** `EXP-20261004-01` (FP16-requested, imgsz 640; D-082). **Kind:** inference-only, deterministic, one run. **Hardware figures are RTX 3060 proxies:** the deployment GPU is still unnamed (Q25, annotated 2026-11-15).

## 1. Operational problem `[P§5]`

Reference task: person detection and tracking on CCTV/video, high-performance, real-time, low-resource, NVIDIA GPU target (D-043, D-044). Reference data: COCO val2017 persons (5000 images, 10,777 GT persons). Small persons are the failure that D-078 targets. From `docs/experiments/FAILURE-ANALYSIS-EXP-20261004.md` (EXP-20261004-01, conf 0.25 reference point):

- Small boxes are 23.7% of GT (2552 of 10,777) but 52.4% of the misses at 0.25 (1863 of 3555), line 47.
- 30.1% of small persons are fully missed (769 of 2552), against 3.4% medium and 0.8% large, line 48.
- The dominant miss type is `no_overlap`: 3059 persons, 28.4% of all GT, lines 21 and 46.

Baseline EXP-20261004-01 (EXPERIMENTS.md:160, 183, 191, 196): mAP@0.5:0.95 **0.517**, AP@0.5 small **0.3556**, medium 0.7259, large 0.9410, P@0.25 **0.7768**, R@0.25 0.6701, 84.0 FPS end to end, 5.8 ms inference, 748 MiB VRAM peak, RTX 3060 12 GB.

## 2. What the imgsz series already established (EXPERIMENTS.md:181-212, one deterministic run each)

| imgsz | mAP@.5:.95 | AP@0.5 small | P@0.25 | FPS (e2e) | Inference ms | VRAM peak MiB |
|---|---|---|---|---|---|---|
| 640 (baseline) | 0.517 | 0.3556 | 0.7768 | 84.0 | 5.8 | 748 |
| 960 | 0.532 (+0.015) | 0.4589 (+0.103) | 0.7273 | 78.6 | 6.1 | 797 |
| 1280 | 0.489 (−0.028) | 0.4828 (+0.127) | 0.6607 | 71.6 | 6.4 | 772 |

Resolution is a real small-person lever, and 960 clears both D-113 gains. But precision at 0.25 falls with imgsz and 960 misses the D-077 floor by 0.0227; only 640 clears it, with 0.0268 of headroom (D-077). The unmatched predictions at 0.25 grow 2075 → 2962 → 4102 (FAILURE-ANALYSIS lines 39-41). The question is whether an intermediate size keeps the floor and still earns the gains.

## 3. Hypothesis (stated before the run)

At imgsz 768 with everything else equal to the baseline: (i) overall AP@0.5:0.95 rises by at least +0.010, (ii) small-person AP@0.5 rises by at least +0.020, and (iii) fixed-threshold precision at conf 0.25 stays at or above 0.75.

## 4. Why 768, fixed before the run

768 is a multiple of 32, between 640 and 960. A three-point quadratic through the series (640, 960, 1280) gives, at 768: mAP@0.5:0.95 ≈ 0.530 (+0.013), small AP@0.5 ≈ 0.407 (+0.051), P@0.25 ≈ 0.759 (margin 0.009 over the floor). Linear interpolation finds no feasible point (the floor needs imgsz ≤ about 813, the overall gain needs about 853 or more); the measured curves are concave, which is why the middle is the candidate.

**This fit is a planning heuristic on three points, not evidence.** A quadratic through three points always fits them exactly and says nothing about error. The run decides. 768 is **one benchmark run, not a sweep** (owner decision 1, D-115): any further imgsz value is a sweep and needs explicit owner approval (`docs/APPROVALS.md`, ⛔ always).

## 5. Success criteria

All three must hold (D-113; D-077). The two gains are **provisional** per D-113 and are revisited when a noisy path is measured.

1. Overall AP@0.5:0.95 gain ≥ **+0.010** over EXP-20261004-01 (≥ 0.527).
2. Small-person AP@0.5 gain ≥ **+0.020** over EXP-20261004-01 (≥ 0.3756).
3. D-077 floor: `fixed_thr@0.25/precision` ≥ **0.75** (fixed threshold, never mAP).

The gains are the D-113 minimums because the `.pt` evaluation path's spread is below the 0.001 reporting resolution (D-112), so 2 × spread does not exceed them. A pass is `meets_provisional_criteria`, never a winner and never a production decision (ADR-0019 §3.5). Medium and large AP, latency, FPS and VRAM are reported, not gated.

## 6. Protocol: identical to EXP-20261004-01 except imgsz

Only `imgsz` changes (640 → 768); the comparer declares it as `variable_under_test="input_resolution"` (ADR-0019 §3.7).

- **Model:** `yolo11n.pt`, sha256 `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`.
- **Data:** `coco-val2017-5k`, `classes=[0]`, data yaml sha256 `27d2702ad12452589014ea219ad1eac8b9298041fcd5dc4a055716a3df626c76`, val list `val2017.txt` sha256 `4d010d0d7200a7b9176acd164d36c9769350a2e41661152f2cf8ba16c9e2aa73`.
- **Protocol:** `conf=0.001` (Q28, D-067), `batch=1`, `device=0`, `quantize=16` (FP16 *requested*; actual precision is not logged, ADR-0017 §3a), NMS IoU and `max_det` at ultralytics defaults.
- **Metrics:** full-curve mAP@0.5, mAP@0.5:0.95, AP@0.5 small/medium/large (approximate: predicted-box area, greedy matching, not the COCO evaluator; Q27 stays open), and `fixed_thr@0.25/*` (D-077).
- **Software and host (must match the baseline):** Linux PC, RTX 3060 12 GB, driver 535.309.01, Ultralytics 8.4.138, Python 3.10.12, torch 2.5.1+cu121.

## 7. Linux PC preflight (read-only checks, before the run)

Measured runs belong on the Linux PC (D-112). Before the run, record and check:

1. `nvidia-smi`: GPU is the RTX 3060 12 GB, driver 535.309.01.
2. `yolo version` is 8.4.138; Python 3.10.12; torch 2.5.1+cu121.
3. sha256 of the weights, data yaml and val list equal the §6 values.
4. No GPU compute process (the ADR-0018 start snapshot must be empty apart from the exempt NoMachine node, D-076). Another project's processes are not stopped.
5. The checkout is a clean, committed tree at the merged code of §10 (ADR-0016); the recorder refuses a run whose commit is not HEAD.
6. GPU idle and cool (about 2 minutes since the last GPU job) so latency and FPS are comparable. Throttle state is read from `nvidia-smi` and reported; it affects system metrics, not accuracy.

## 8. Cost estimate and ceiling (`docs/APPROVALS.md`; D-080, D-087)

| Item | Estimate | Basis |
|---|---|---|
| GPU wall | about 62 s (ceiling 180 s) | measured 59.5 s at 640 and 63.6 s at 960 (5000 / 78.59 FPS) |
| GPU-hours | about 0.017; **ceiling 0.05** | wall / 3600 |
| Total wall incl. CPU verification | about 10 min | verification time unmeasured |
| Peak VRAM | below 1 GiB (expect 760–800 MiB) | 748 MiB at 640, 797 MiB at 960 |
| Peak RAM | about 2.2 GB | 2190 MiB at 640 |
| Disk | about 0.1 GB | `predictions.json` is about 105 MB |
| Download, spend | none, $0 | local hardware |

Hardware implications on the proxy GPU (CLAUDE.md §3.4): 768² is 1.44× the pixels of 640², about 9.4 GFLOPs against 6.5 (scaled, not measured). Batch-1 nano inference is overhead-bound on the 3060 (5.8 → 6.1 ms for 2.25× pixels from 640 to 960), so expect about 6.0 ms and about 81 FPS at 768. On a smaller edge GPU latency would scale closer to the FLOPs ratio. Power is not measured. The deployment GPU is unnamed, so none of this is a target measurement.

## 9. What a failure would mean

- **Precision below 0.75:** resolution alone cannot meet D-077 and the gains together in this size range (the floor and the small-person gain trade against each other through the extra low-confidence false positives).
- **Gains below +0.010 / +0.020:** the heuristic fit overestimated the middle of the curve.
- **Either way** the result is recorded, not retried at another size. Another imgsz is a sweep (owner approval, ⛔). The next levers need an owner unblock: a model swap or a real training runtime (STATUS "Do not start yet"; training would also need ≥ 3 seeds, D-112).
- **A pass** earns a next step only; it does not select 768 for deployment, which also depends on the unnamed target GPU and on tracking and CCTV conditions that COCO does not measure (domain shift: FAILURE-ANALYSIS line 81).

## 10. Code prerequisites (separate issues; this document needs none)

The measured-run wrapper and recorder are hard-wired to the imgsz series: `APPROVED_IMGSZ = (640, 960, 1280)` (`scripts/run_yolo_val_measured.py:55`), the run name and `series` (`:69-71`, `:336`), the recorder's fixed ids and exactly-640/960/1280 rule (`scripts/record_evaluation_runs.py:41-45`, `:60-61`), the hypothesis and series note (`cv_agent/experiments/evaluation_records.py:49-58`, `:546-551`), and the ADR-0017 §4a exception ("this controlled series only"). So the run cannot start until:

- **Issue B:** an ADR-0017 amendment and a generalised wrapper and recorder (owner-fixed exp id, imgsz a multiple of 32, hypothesis and criteria as parameters; about 300 lines including tests).
- **Issue C:** a read-only comparison entry point calling `evaluate_candidate(..., variable_under_test="input_resolution")` (`cv_agent/experiments/acceptance.py`), and the D-113 wording for the provisional label (about 150 lines).

## 11. Commands (NOT run; shapes depend on Issue B)

```bash
# Linux PC, clean checkout of the merged Issue B/C code, after the §7 preflight
python3 scripts/run_yolo_val_measured.py --imgsz 768 --exp-id EXP-20261115-01 \
  --approval-ref "EXP-20261115-01-OWNER-20261115"
python3 scripts/record_evaluation_runs.py --approval-ref "EXP-20261115-01-OWNER-20261115" \
  --candidate EXP-20261115-01=<run dir> --baseline EXP-20261004-01 \
  --proposal docs/experiments/EXP-20261115-01-proposal.md --dry-run   # review, then rerun without --dry-run
python3 scripts/compare_candidate.py EXP-20261115-01
```

## 12. Stop conditions

Stop and report, changing no existing record, if: the tree is dirty or the commit is not the merged prerequisite code; any §7 check fails (including a foreign GPU process); the predictions file is not full-curve (the writer refuses it); the run exceeds the 0.05 GPU-hour ceiling; or the record is incomplete under `[P§25]` (it is then not a valid result).
