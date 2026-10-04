# ADR-0018: FP32 control for the image-size series (precision as the only variable)

- **Status:** Accepted (2026-10-04, owner acceptance; recorded in D-075 and JOURNAL). Implemented on the branch under issue #74 (commits `d0aea40` and `9170e39`). Acceptance approves the design only. It does **not** approve any GPU run: each run needs a fresh owner approval reference (§3.8) and an idle GPU (§6).
- **Date:** 2026-10-04
- **Layer:** experiments (provenance and recording, ADR-0016, ADR-0017)
- **Canon:** `[P§25]` (reproducibility metadata), `[P§29.2]` (baseline discipline), `[P§29.3]` (no claim without a quantitative comparison), `[P§29.5]` (metadata completeness)
- **Supersedes / Superseded by:** — (amends ADR-0017 §3a, which fixed the protocol to FP16, and adds GPU-process provenance on top of ADR-0017 §3)
- **Issue:** #74 (ADR-0018 FP32-control/preflight work: contaminated-run quarantine, GPU-process provenance and preflight, writer eligibility checks, FP32 control path). Required by `CLAUDE.md` §5. The first FP32 attempt was committed (`5861718`) before this issue existed; that omission is recorded here, not hidden.

## 1. Context

EXP-20261004-01 records FP16 requested (`quantize=16`) at conf=0.001. The historical records (EXP-20260930-01 and the sweep rows) ran FP32 at conf=0.25. The two differ in both precision and conf, so no record isolates the precision effect. EVALUATION.md requires a re-measurement before any optimization (quantization) is accepted, so the FP16 accuracy cost is unmeasured.

The first FP32 640 attempt ran on 2026-10-04 under owner reference `EXP-20261004-FP32-640-OWNER-20261004`. A training job from another project shared the GPU. Its device-wide VRAM (baseline 1164 MiB, peak 1629 MiB), FPS and latency were therefore not valid, and the run was not written to the ledger (§3.9). ADR-0017's VRAM measure is device-wide, so it could not detect the contamination. This ADR closes that gap.

## 2. Responsibility `[P§34]`

- **This owns:** one additional measured run, FP32 at imgsz 640 on the same protocol as EXP-20261004-01, recorded as its own ExperimentRecord. It owns the protocol difference between the two precisions and the eligibility rule for a run's GPU state: a run whose GPU was shared with a foreign process is not ledger-eligible.
- **This does NOT own:** whether any precision choice is good (Q30, open; D-069). Running `yolo val` (the wrapper, ADR-0017 §4a). The metric mathematics and the record schema, which are unchanged. Stopping or controlling any other project's GPU process: the agent observes and refuses, and never acts on another process.
- **Why not an existing component:** ADR-0017 fixes one precision for one series. A separate control with its own id and protocol amends that protocol. GPU-process provenance belongs with run recording (ADR-0017), because it decides whether a run can be recorded at all.

## 3. Decision

1. **Scope.** One control run: YOLO11n, COCO val2017 persons, imgsz 640, conf 0.001, batch 1, device 0, classes [0], `quantize` unset (FP32). Only the precision differs from EXP-20261004-01.
2. **Protocol and narrowness.** `quantize` is not passed, so ultralytics uses its default `None` (`fp16=False`). `--precision fp32` is accepted only at imgsz 640 and is refused, before the git check, at any other size. The FP16 path is unchanged: its argv, run name, series id and label are the same as before. Tests cover this.
3. **Label.** `precision_requested` is `FP32 requested (quantize unset; ultralytics default None, fp16=False); actual inference precision is not logged`. As in ADR-0017 §3a, the label records the request, not a measurement.
4. **Identity.** The clean rerun uses the proposed experiment id `EXP-20261004-04` (§3.10). Its baseline is `EXP-20261004-01`, the FP16 640 record. The run name carries a `-fp32` suffix.
5. **Approval.** Each run carries an owner approval reference, given exactly as the owner provides it. The writer requires the run's reference to equal `--approval-ref`. The agent never chooses, invents or substitutes one (§3.8).
6. **Measurement only (D-069).** No pass/fail threshold and no production selection. The record's notes say so.
7. **Verification.** The FP32 run is verified under the FP32 protocol (`quantize` unset). An FP16 run is refused under that protocol and an FP32 run under the FP16 protocol. ADR-0017 §3 and §5 otherwise apply unchanged.
8. **Approval is required for every run.** A fresh owner approval reference is mandatory for the rerun. The reference for the contaminated attempt is consumed and cannot be reused, because approvals are specific and non-transferable (`docs/APPROVALS.md`). The approval record in JOURNAL must have the fields `docs/APPROVALS.md` requires: id, timestamp, requester, action, estimate presented, approver, scope, and `exp_id`.
9. **Contaminated run: permanently not ledger-eligible.** The first FP32 attempt, `e1-yolo11n-coco-val2017-imgsz640-conf0001-fp32` (commit `5861718`), is **not ledger-eligible, permanently**. Its VRAM, RAM, FPS, latency and `gpu_hours` are invalid. Its accuracy values are retained as evidence only, and no claim is made about them. It is quarantined by rename, not copy or delete, to `/home/dev/cv-engineering-evidence/EXP-20261004-FP32-640/contaminated-concurrent-gpu/`. The archive holds the run directory, `run.json`, `val.log`, `PRE-MOVE-SHA256.txt`, `POST-MOVE-SHA256.txt`, `MANIFEST.sha256` and `CONTAMINATED.md`, and is read-only. `MANIFEST.sha256` lists the 15 archived run files; `CONTAMINATED.md` is written after the manifest and is not in it. Its original artifacts are preserved byte-for-byte, and pre- and post-move hashes were compared. No ledger row was written for it, and no historical row was changed.
10. **GPU-process provenance (ADR-0018).** `nvidia-smi --query-compute-apps=pid,process_name` is taken at three points and recorded in `run.json` as `gpu_process_snapshots`:
    - **start:** before the run process exists. The snapshot must contain **zero** compute processes. A busy or unreadable list refuses the run before anything starts.
    - **during:** at every VRAM poll, in the same thread. The run's own pid (`own_pid`, the `yolo val` process) is excluded when judging foreign processes. A process whose pid is not a number makes the snapshot unreadable, and an unreadable snapshot is never treated as idle.
    - **end:** after the run process exits.

    `run.json` also records `own_pid` and `foreign_process_seen`, a boolean computed from all three points. The **polling limitation** is stated here: polling is at 1-second intervals, so a process that starts and exits between two polls is not seen. This is a known limit of the method, not a claim that the GPU was idle between polls.

    **Own-pid assumption (UNVERIFIED on a real run).** The exclusion above assumes that the pid nvidia-smi reports for the run's GPU work is the pid of the `yolo val` process the wrapper started (`proc.pid`). No real GPU run has yet confirmed this. The rule fails closed. If the run's GPU work appears under a different pid, its own process is recorded as foreign, so `foreign_process_seen` is true and the writer refuses the run. A wrong assumption can therefore block a clean rerun, but it cannot allow a contaminated one. The first rerun must confirm the pid match, and its snapshots are the evidence. A refused run is never recorded as eligible.
11. **Writer rejection.** The writer refuses any run that:
    - has no `gpu_process_snapshots` or `own_pid`;
    - has a start snapshot that is missing, unreadable, or non-empty;
    - has no during-polling samples, or an unreadable one;
    - has an end snapshot that is missing, unreadable, or lists a foreign process;
    - has a foreign process at any point;
    - has a `foreign_process_seen` that is missing or disagrees with the snapshots.

    Failing any one refuses the run. A run with one of these problems is never recorded as incomplete.
12. **ADR-0017 system metrics preserved.** Peak VRAM and peak RAM are still required, and their definitions are unchanged. VRAM is still device-wide memory, not per-process memory. Process provenance is an additional rule. It never replaces a metric and never relaxes a refusal.
13. **FP16 records unchanged.** EXP-20261004-01, -02 and -03 are not edited. Their process-idleness is **inferred from baseline VRAM** (413–433 MiB, against 1164 MiB in the contaminated run), **not process-verified**: their run.json files have no process snapshot. This is an acknowledged limitation of those records. It is not a claim that they were contaminated.
14. **Experiment id.** An id is allocated only when a record is written to the ledger. The writer's preflight refuses an id that is already in the ledger, and an id is permanent once written. Appearing in a run.json, a document or this ADR does not allocate it. A failed or ineligible attempt does not allocate an id. `EXP-20261004-04` was named in the contaminated run.json but was never written, so it is **not allocated**. The owner has authorized it for the clean rerun. It must still be absent from the ledger at write time, or the write is refused.
15. **Writer.** `scripts/record_evaluation_runs.py --fp32-control <run dir> --approval-ref <ref>` records one run. The three-run series mode is unchanged.

## 4. Alternatives considered

| Alternative | Why not chosen |
|---|---|
| Re-run FP16 at 640 with a new id and compare | Does not isolate precision; it repeats EXP-20261004-01. |
| Put the FP32 run into the EXP-20261004-01 series | The series ids are owner-fixed and written as one batch. A fourth member would change the approved batch. |
| Change the precision of EXP-20260930-01 or the sweep rows | Historical rows are never edited (ADR-0016). |
| Treat process checks as advisory and record a warning | An advisory flag can be ignored by the writer. Eligibility must be enforced. |
| Stop or pause the foreign process before the run | Not the agent's to do. It belongs to another project. The agent refuses the run instead. |
| Use per-process VRAM (`used_gpu_memory` per pid) as the metric | Changes ADR-0017's measure. This ADR keeps the metric and adds provenance. A per-process measure would need its own ADR. |

## 5. Consequences

- The clean FP32 640 record can be compared with EXP-20261004-01 on precision alone, at identical conf and protocol. It cannot be compared with EXP-20260930-01 on mAP, because that record used conf=0.25.
- A busy GPU at start, a foreign process at any point, or an unreadable process list makes a run unrecordable. This is deliberate. It means a rerun can fail for reasons outside the agent's control.
- The FP32 control does not decide whether FP16 is acceptable. Q30 stays open.
- The contaminated attempt stays as evidence outside the repository. It is not used for any claim.

## 6. Rerun gate

The clean FP32 640 rerun may start only when **all** of these hold:

1. The working tree is clean and HEAD is captured.
2. Issue #74 exists, and this ADR cites it.
3. This ADR is **Accepted** by the owner.
4. The contaminated artifacts are in quarantine, with the manifest verified, and the active evaluations path for `e1-yolo11n-coco-val2017-imgsz640-conf0001-fp32` is free.
5. A fresh owner approval reference has been supplied, and an approval record with the required fields is in JOURNAL before the run.
6. `nvidia-smi --query-compute-apps` lists **no process** immediately before launch. The start snapshot will be checked again by the wrapper.
7. No concurrent GPU workload from another project is running. The agent does not stop or control such a process.

After the run: the writer runs in dry-run mode first. The record is written only if the run is eligible (§3.11) and the id is absent from the ledger. The ledger's hash is recorded before and after the write. STATUS, EXPERIMENTS and JOURNAL are updated in one commit. Nothing is pushed or merged.

## 7. Verification

- `tests/test_evaluation_records.py` (102 tests) covers: a clean start snapshot; a foreign process at start, during polling, and at end; a missing, unreadable or empty snapshot; a flag that disagrees with the snapshots, or is missing; the wrapper refusing a busy GPU and an unreadable process list before any run; the run's own process not counted as foreign; parsing of empty, clean and unreadable output; the FP32 argv and run name; refusal of FP32 at sizes other than 640; the FP16 path unchanged.
- The tests use a fake `nvidia-smi`. No GPU run is part of the test suite.
- ADR-0018 was accepted by the owner on 2026-10-04 (see the status line). Acceptance does not approve a GPU run.
