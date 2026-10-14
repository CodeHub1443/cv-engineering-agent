# ADR-0019: Training execution pipeline — approval-gated jobs and candidate acceptance

- **Status:** Proposed (2026-10-14). Implemented on `feature/claude/76-training-execution-pipeline`; not merged. Acceptance does not approve any GPU run.
- **Date:** 2026-10-14
- **Layer:** execution (job lifecycle) + experiments (acceptance comparison)
- **Canon:** `[P§24]` (human approval), `[P§25]` (reproducibility), `[P§29.2]`, `[P§29.3]`, `[P§29.5]`, `[P§29.8]`, `[P§34]`
- **Supersedes / Superseded by:** — (extends ADR-0013 and ADR-0017; changes neither)
- **Issue:** #76

## 1. Context

ADR-0013 gives a generic approval-pinned job boundary but nothing training-specific: no typed request that carries the `[P§25]` reproducibility fields, no cost estimate before approval (`docs/APPROVALS.md`), and no rule for deciding whether a finished candidate beats its baseline. D-077 and D-078 (2026-10-14) set the precision floor and the "both APs must improve" rule. Issue #76 authorizes the foundation only, with **no real GPU run**.

## 2. Responsibility `[P§34]`

- **`cv_agent/execution/jobs/training.py` owns:** the typed training-job request, preflight validation of provenance completeness and cost estimate, the explicit owner approval reference, and mapping lifecycle outcomes to a provenance-complete training result. It delegates start, poll, cancel and collect to `JobExecutor`.
- **`cv_agent/experiments/acceptance.py` owns:** comparing a candidate `ExperimentRecord` with its named baseline against `AcceptanceCriteria`, keeping full-curve AP and fixed-threshold precision as separate, protocol-labelled findings.
- **Neither owns:** process spawning (JobRuntime), pin/host checks (JobExecutor), metric math (`detection_metrics`), storage (ledger), or the approval workflow itself (`docs/APPROVALS.md`; the reference is recorded, not minted).
- **Why not an existing component:** `JobExecutor` is workload-agnostic and must stay so. `evaluation_records` verifies measured run directories and refuses to judge them. Layering forbids experiments importing execution (ADR-0017 §4), so the two halves cannot be one module.

## 3. Decision

1. **No new runtime and no real training runtime.** Only the typed layer and tests with fake runtimes are added. A real training runtime needs its own issue and approval.
2. **Approval gate precedes the executor.** `start_training` refuses, without calling `JobExecutor`, when the approval reference is blank, the cost estimate is missing, or the request is provenance-incomplete. The executor's pin and approval checks still run after it; this layer only adds a stricter earlier gate.
3. **Provenance-complete request.** Required before start: 40-hex commit SHA, dataset version, model, precision, hardware target, config (hyperparameters), seed, baseline experiment id, cost estimate, approval reference. A result built from an incomplete request cannot exist.
4. **No success without evaluation.** A `completed` job is `training_completed`, not accepted. Acceptance requires a candidate record with measured full-curve and fixed-threshold metrics (ADR-0017) and a named baseline.
5. **Acceptance rules (D-077, D-078).** Precision at conf 0.25 >= 0.75 (approved). Overall AP@0.5:0.95 gain >= +0.010 and small-person AP@0.5 gain >= +0.020 (**provisional**, Q32). A passing report is `meets_provisional_criteria`, never a winner.
6. **Protocol separation.** Standard AP keys require the full-curve protocol (the record's `confidence_protocol` note names conf=0.001); `fixed_thr@0.25/*` keys are never used as AP and AP keys are never used as precision. Missing keys fail closed.

## 4. Alternatives considered

| Alternative | Why not chosen |
|---|---|
| Extend `JobExecutor` with training logic | Makes a workload-agnostic executor training-aware; breaks ADR-0013 scope. |
| One module spanning execution and experiments | Violates ADR-0017 §4 layering. |
| Hard-code the +0.010/+0.020 deltas as final gates | D-078: not validated (variance, baseline precision, rationale — Q32). They are configuration marked provisional. |
| Implement a real YOLO train runtime now | Issue #76 out of scope; needs GPU approval. |

## 5. Consequences

No schema change to `ExperimentRecord`. No change to the ledger, binding registry or existing runtimes. Revisit when Q32 is answered (gates become final) or when a real training runtime is proposed.
