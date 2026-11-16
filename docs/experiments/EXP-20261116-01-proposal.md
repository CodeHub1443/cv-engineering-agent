# EXP-20261116-01 — Integrity replication of EXP-20261004-01 on the restored COCO val2017 (PROPOSED; not run)

**Status:** proposed 2026-11-16, owner-approved as an integrity replication (D-119). Issue #164. No GPU run has happened.
**Experiment id:** `EXP-20261116-01` (owner-fixed). **Approval reference:** `EXP-20261116-01-OWNER-20261116` (owner-issued under the D-080/D-087 standing grant; bound to this one experiment and the cost ceiling in §7).
**Candidate:** EXP-20261116-01, imgsz 640
**Baseline:** `EXP-20261004-01` (FP16-requested, imgsz 640; D-082). **Kind:** inference-only, deterministic, one run. Hardware figures are RTX 3060 proxies (Q25).

**Purpose.** This is an **integrity replication**, not an optimisation candidate and **not a sweep value** (D-115 is untouched: no new imgsz is being tried). It exists only to prove that the restored dataset is byte-for-byte equivalent in effect to the one EXP-20261004-01 measured, before EXP-20261115-01 (imgsz 768) is run against that baseline.

## 1. Operational problem `[P§5]`

COCO val2017 was deleted from the Linux PC (`~/Documents/data_cleaner` was gone). On 2026-11-16 the owner restored it to the original path from Ultralytics' `coco2017labels-segments.zip` plus the official `val2017.zip`, and verified on CPU:

- `val2017.txt` sha256 `4d010d0d7200a7b9176acd164d36c9769350a2e41661152f2cf8ba16c9e2aa73` (equals the baseline's);
- 5000 val-list lines and 5000 images;
- 10,777 person boxes (equals the baseline's GT count).

The measured-run wrapper fingerprints the weights, the data yaml and the val list, but **not the label files** (Q69). The checks above cannot see a label file that differs in content with the same person count (a different label-set revision, a box edited or reordered). A deterministic re-run is the check that can: on one host the evaluation path is deterministic (D-112; byte-identical predictions across attempts, EXPERIMENTS.md:222-223), so any metric difference is attributable to the data.

## 2. Reference values (EXP-20261004-01, EXPERIMENTS.md:160)

| Metric | Recorded value |
|---|---|
| mAP@0.5:0.95 | 0.517 (3 decimals) |
| AP@0.5 small | 0.3556127… (full stored precision) |
| `fixed_thr@0.25/precision` (P@0.25) | 0.7768 (full stored precision) |

Medium and large AP, recall, latency, FPS and VRAM are also recorded and reported, not gated.

## 3. Hypothesis (stated before the run)

On the restored dataset, with the protocol of EXP-20261004-01 unchanged, the run reproduces EXP-20261004-01's accuracy exactly: every delta on mAP@0.5:0.95, AP@0.5 small and P@0.25 is 0. It is falsified by any non-zero delta.

## 4. Why imgsz 640

640 is the baseline's own size. The only variable is the dataset's provenance (the restored label files); nothing about the model, protocol, host or software changes. It is deliberately not a new size, so it consumes no sweep allowance.

## 5. Success criteria

All three must hold (replication, not improvement):

1. mAP@0.5:0.95 equals EXP-20261004-01's: **0.517** at 3 decimals.
2. AP@0.5 small equals EXP-20261004-01's: **0.3556127…** at full stored precision.
3. P@0.25 equals EXP-20261004-01's: **0.7768** at full stored precision.

**Any difference means the restored labels differ from the original: stop, and do NOT run EXP-20261115-01 against this baseline** (the baseline would no longer describe the same data). Record the difference and report; do not retry or tune.

**Expected comparer output.** `scripts/compare_candidate.py` will report `does_not_meet_criteria`: the D-113 gain rule requires gains of at least +0.010 and +0.020, and a replication has none, by design. That verdict is expected and is not a failure here. The check is that **every delta is 0**; read the deltas, not the verdict.

## 6. Protocol: identical to EXP-20261004-01

Nothing differs from the baseline except the run name, which the wrapper derives from the exp id.

- **Model:** `yolo11n.pt`, sha256 `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`.
- **Data:** `coco-val2017-5k`, `classes=[0]`, data yaml sha256 `27d2702ad12452589014ea219ad1eac8b9298041fcd5dc4a055716a3df626c76`, val list `val2017.txt` sha256 `4d010d0d7200a7b9176acd164d36c9769350a2e41661152f2cf8ba16c9e2aa73`.
- **Protocol:** `imgsz=640`, `conf=0.001` (Q28, D-067), `batch=1`, `device=0`, `quantize=16` (FP16 *requested*, ADR-0017 §3a), NMS IoU and `max_det` at defaults.
- **Software and host (must match the baseline):** Linux PC, RTX 3060 12 GB, driver 535.309.01, Ultralytics 8.4.138, Python 3.10.12, torch 2.5.1+cu121.

**Code check (read, not run; no code is changed).**

- The wrapper accepts `--exp-id` with imgsz 640: `candidate_problems` (`cv_agent/experiments/evaluation_records.py:170-184`) requires only an `EXP-YYYYMMDD-NN` id that is not in `RESERVED_SERIES_IDS` (`:81-83`: the EXP-20261004 ids and the FP32 control) and an imgsz that is a multiple of 32 in [320, 1280]. EXP-20261116-01 is not reserved and 640 qualifies. The wrapper calls it at `scripts/run_yolo_val_measured.py:285`; the recorder at `scripts/record_evaluation_runs.py:285`.
- The run name differs from the baseline's run directory: with an exp id the wrapper uses `candidate_run_name` (`run_yolo_val_measured.py:75-77`, `evaluation_records.py:187-189`), giving `exp-20261116-01-yolo11n-coco-val2017-imgsz640-conf0001`; the baseline's is `e1-yolo11n-coco-val2017-imgsz640-conf0001` (`run_yolo_val_measured.py:78-79`). The recorder also requires the run directory to equal the derived name (`record_evaluation_runs.py:287-288`), and `run.json` `series` to equal the exp id (`:283-284`).

## 7. Cost estimate and ceiling (`docs/APPROVALS.md`; D-080, D-087)

| Item | Estimate | Basis |
|---|---|---|
| GPU wall | about 60 s (ceiling 180 s) | 59.5 s measured at 640 in EXP-20261004-01 |
| GPU-hours | about 0.017; **ceiling 0.05** | wall / 3600 |
| Peak VRAM | about 750 MiB | 748 MiB at 640 |
| Disk | about 0.1 GB | `predictions.json` is about 105 MB |
| Download, spend | none, $0 | local hardware |

Hardware implications (CLAUDE.md §3.4): none new. The model, size and host equal the baseline's, so latency, FPS and VRAM are expected to match it to within run noise; they do not enter the criteria.

## 8. Linux PC preflight (read-only, before the run)

1. `nvidia-smi`: RTX 3060 12 GB, driver 535.309.01; `yolo version` 8.4.138; Python 3.10.12; torch 2.5.1+cu121.
2. sha256 of the weights, data yaml and val list equal the §6 values.
3. No GPU compute process in the ADR-0018 start snapshot (the NoMachine node is exempt, D-076). Another project's processes are not stopped.
4. Clean, committed checkout at the merged code (ADR-0016); the recorder refuses a run whose commit is not HEAD.
5. GPU idle and cool (about 2 minutes since the last GPU job).

## 9. Commands (NOT run)

```bash
python3 scripts/run_yolo_val_measured.py --imgsz 640 --exp-id EXP-20261116-01 \
  --approval-ref "EXP-20261116-01-OWNER-20261116"
python3 scripts/record_evaluation_runs.py --approval-ref "EXP-20261116-01-OWNER-20261116" \
  --candidate EXP-20261116-01=<run dir> --baseline EXP-20261004-01 \
  --proposal docs/experiments/EXP-20261116-01-proposal.md --dry-run   # review, then rerun without --dry-run
python3 scripts/compare_candidate.py EXP-20261116-01   # expect does_not_meet_criteria; check every delta is 0
```

## 10. What a result would mean

- **All three deltas 0:** the restored labels are equivalent in effect to the original on these metrics; EXP-20261115-01 (768) may run against the EXP-20261004-01 baseline. This is evidence of equivalence on three metrics, not a cryptographic proof of identical label files (Q69).
- **Any delta non-zero:** the restored labels differ. Stop. Do not run EXP-20261115-01. Report the deltas and ask the owner (for example, restoring the label revision the baseline used).

## 11. Stop conditions

Stop and report, changing no existing record, if: the tree is dirty or the commit is not HEAD; any §8 check fails (including a foreign GPU process); the predictions file is not full-curve; the run exceeds the 0.05 GPU-hour ceiling; or the record is incomplete under `[P§25]`.
