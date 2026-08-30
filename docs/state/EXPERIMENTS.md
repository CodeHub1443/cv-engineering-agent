# EXPERIMENT LEDGER

> **Append-only.** Every training, benchmark, or optimization run gets a row. A run whose
> metadata is incomplete **is not a valid result** and may not be cited in an ADR, a PR,
> or a recommendation `[P§25]`, `[P§29.5]`.
>
> This file exists so the agent can answer *"why did we choose this model?"* from record
> rather than from conversational memory `[P§25]`.

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
| `hypothesis` | what this run is testing, stated before it runs |
| `baseline_id` | the run being compared against, or `SELF` for a baseline |
| `commit` | code SHA |
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

## Runs

_None yet. The first entry must be a baseline (`baseline_id = SELF`)._

| exp_id | hypothesis | baseline | model | dataset_ver | precision | target hw | mAP@.5:.95 | recall | FPS | latency | VRAM | power | gpu_h | decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| _(example — delete when the first real run lands)_ | | | | | | | | | | | | | | |
| EXP-20260901-01 | establish baseline detector on target Jetson | SELF | _tbd_ | _tbd_ | FP16 | _tbd_ | — | — | — | — | — | — | — | — |
