# EXP-20261118-01 — R1: COCO integrity replication through the EvalDatasetRef path (PROPOSED; not run)

**Status:** proposed 2026-11-18. Issue #181. No GPU run has happened.
**Experiment id:** `EXP-20261118-01` (owner-fixed). **Approval reference:** `EXP-20261118-01-OWNER-20261118` (owner-issued under the D-080/D-087 standing grant; bound to this one experiment and the ceiling in §7).
**Candidate:** EXP-20261118-01, imgsz 640
**Baseline:** `EXP-20261004-01` (FP16-requested, imgsz 640; D-082). **Kind:** inference-only, deterministic, one run. Hardware figures are RTX 3060 proxies (Q25).

**Purpose.** An **integrity replication**, not an optimisation candidate and not a sweep value (D-115 untouched). It proves that I3–I5 and I4a (the `EvalDatasetRef` path, run hygiene, spec and label-digest recording) changed no measurement, and it is the first row to carry `label_digest`, which closes Q69.

## 1. Operational problem `[P§5]`

The measured path was rewired from a hard-coded COCO root to `--dataset-spec` and `--data-yaml` (I4a, #179) and gained environment pinning (I5, #177). Unit tests cannot show that the live evaluation still yields the same numbers. One deterministic re-run can: on one host the path is deterministic (D-112), so any metric difference is attributable to the code or the data, and is a defect.

## 2. Reference values (EXP-20261004-01, `docs/state/EXPERIMENTS.md:160`)

mAP@0.5:0.95 0.517 (3 decimals); AP@0.5 small 0.3556127… and `fixed_thr@0.25/precision` 0.7768 (full stored precision). Every key in the baseline's `val_metrics` is compared, not just these three.

## 3. Hypothesis (stated before the run)

With the protocol of EXP-20261004-01 unchanged, the run reproduces every `val_metrics` key exactly (delta 0.0, no tolerance). Falsified by any differing key.

## 4. Why imgsz 640

It is the baseline's own size. The only variables are the code path (I3–I5, I4a) and the recorded dataset evidence; nothing about model, protocol, host or software changes. No sweep allowance is consumed.

## 5. Success criteria

1. `python3 scripts/compare_candidate.py --replication --candidate EXP-20261118-01` prints `verdict: replicates` and exits 0 (`scripts/compare_candidate.py:148-151`; exact comparison, `:102-123`).
2. Two notes are expected and are **not** defects: `note: confidence_protocol wording differs` (`:109-110`) and `label_digest` on one side only (the baseline predates digests; I4b adds that note).
3. Any differing metric key, or `verdict: invalid` (exit 2), is a **defect: stop and report**; do not retry or tune, and do not run EXP-20261115-01 against this baseline.

## 6. Protocol: identical to EXP-20261004-01 and EXP-20261116-01

- **Model:** `yolo11n.pt`, sha256 `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`.
- **Data:** `coco-val2017` (ledger `coco-val2017-5k`), `classes=[0]`, the same data yaml file, sha256 `27d2702ad12452589014ea219ad1eac8b9298041fcd5dc4a055716a3df626c76`; val list `val2017.txt` sha256 `4d010d0d7200a7b9176acd164d36c9769350a2e41661152f2cf8ba16c9e2aa73`. `_protocol_problems` (`compare_candidate.py:81-100`) marks the run `invalid` if weights, yaml or val-list hashes, precision, imgsz, model or `dataset_version` differ.
- **Protocol:** `imgsz=640`, `conf=0.001` (Q28, D-067), `batch=1`, `device=0`, `quantize=16` (FP16 requested, ADR-0017 §3a; `--precision` defaults to `fp16`, `run_yolo_val_measured.py:388-393`), NMS IoU and `max_det` at defaults.
- **Host:** Linux PC, RTX 3060 12 GB, driver 535.309.01, Ultralytics 8.4.138, Python 3.10.12, torch 2.5.1+cu121.

## 7. Cost estimate and ceiling (`docs/APPROVALS.md`; D-080, D-087)

About 60 s wall (ceiling 180 s), 0.017 GPU-h, **ceiling 0.05 GPU-h**, peak VRAM about 750 MiB, disk about 0.1 GB, no download, $0 (EXP-20261116-01 measured about 1 min). No new hardware implications (CLAUDE.md §3.4): model, size and host equal the baseline's.

## 8. Linux PC preflight (read-only, before the run)

1. `nvidia-smi` shows the RTX 3060, driver 535.309.01; `yolo version` 8.4.138; Python 3.10.12; torch 2.5.1+cu121.
2. sha256 of the weights, data yaml and val list equal §6. `/home/dev/Documents/data_cleaner/datasets/coco/eval_dataset_ref.json` exists.
3. No GPU compute process in the ADR-0018 start snapshot (NoMachine exempt, D-076); other projects' processes are not stopped.
4. GPU idle and cool (about 2 minutes since the last GPU job).

## 9. Execution order and commit gate

The wrapper refuses a dirty tree (`run_yolo_val_measured.py:431`); the recorder refuses a run whose `commit` is not HEAD (`cv_agent/experiments/evaluation_records.py:435-438`). Therefore, in this order:

1. Merge I4b, then merge this proposal PR.
2. On the Linux PC: `git pull`, then `git status --short` (must print nothing).
3. Run (§10), record (§10), judge (§10).
4. **No merge to main between the run and the record**, and no new commit on the checkout: both must see the same HEAD.

## 10. Commands (NOT run; repository root on the Linux PC)

Flags are from `run_yolo_val_measured.py:373-407` (all of `--imgsz`, `--approval-ref`, `--dataset-spec`, `--data-yaml` required; `--exp-id` for a candidate) and `record_evaluation_runs.py:81-89` (`--approval-ref`, `--dataset-spec` required; `--candidate` needs `--baseline`, `--proposal`).

```bash
python3 scripts/run_yolo_val_measured.py --imgsz 640 --exp-id EXP-20261118-01 \
  --approval-ref "EXP-20261118-01-OWNER-20261118" \
  --dataset-spec /home/dev/Documents/data_cleaner/datasets/coco/eval_dataset_ref.json \
  --data-yaml .cv_agent/evaluations/coco-person-val.yaml
RUN=.cv_agent/evaluations/exp-20261118-01-yolo11n-coco-val2017-imgsz640-conf0001   # candidate_run_name, evaluation_records.py:207-209
python3 scripts/record_evaluation_runs.py --approval-ref "EXP-20261118-01-OWNER-20261118" \
  --dataset-spec /home/dev/Documents/data_cleaner/datasets/coco/eval_dataset_ref.json \
  --candidate EXP-20261118-01=$RUN --baseline EXP-20261004-01 \
  --proposal docs/experiments/EXP-20261118-01-proposal.md --dry-run   # review, then rerun without --dry-run
python3 scripts/compare_candidate.py --replication --candidate EXP-20261118-01   # expect "verdict: replicates", exit 0
```

## 11. Expected new record fields

The ledger row's notes should carry `label_digest` (recomputed from the files, `evaluation_records.py:534`), `spec_sha256`, `environment` (exactly 5 keys: `python_version`, `torch_version`, `torch_cuda_version`, `ultralytics_version`, `pip_freeze_sha256`; `run_yolo_val_measured.py:84`) and `vram_peak_above_idle_mib` (no comparison rule, D-125). **Q69 closes when the row carries `label_digest`.**

## 12. Stop conditions

Stop and report, changing no existing record, if: the tree is dirty or the commit is not HEAD; any §8 check fails; the run exceeds the 0.05 GPU-hour ceiling; the wrapper or recorder refuses; the predictions file is not full-curve; the record is incomplete under `[P§25]`; or the comparer prints a differing key or `verdict: invalid`.
