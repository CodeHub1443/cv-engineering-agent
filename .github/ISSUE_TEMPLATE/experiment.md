---
name: Experiment
about: A training, benchmark, or optimization run
labels: ["type:experiment", "needs-approval"]
---

**Hypothesis:** <!-- stated BEFORE the run; what would falsify it? -->
**Baseline compared against:** EXP-________ (or `SELF` if this establishes the baseline)
**Canon:** `[P§25]`, `[P§29.2]`

## Setup
- Model / variant:
- Dataset version:
- Split + leakage checks passed:
- Target hardware:
- Precision:
- Key hyperparameters (link config, don't retype):

## Metrics to be reported
Accuracy **and** system metrics **and** the target constraint, per `docs/EVALUATION.md`.
A single-number result is not acceptable.

## Cost estimate `[P§24]`
- GPU-hours:
- Wall clock:
- $:
- Storage:
- Cheaper alternative considered, and why it is insufficient:

## Approval
- [ ] Estimate presented
- [ ] Approved by ______ on ______ (approval id: ______)

## Definition of done
Row appended to `docs/state/EXPERIMENTS.md` with the complete schema, composite result
reported, failure analysis performed `[P§27]`, and a recommended next experiment stated.
