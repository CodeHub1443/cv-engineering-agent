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

_None yet. The first entry must be a baseline (`baseline_id = SELF`)._

The table below is a condensed rollup view for scanning; it does not repeat every
field from the schema above (e.g. `status`, `approval_ref`, `created_at`) — those
live in the full row record when a real experiment-tracking backend exists
(`OPEN_QUESTIONS.md` Q8).

| exp_id | hypothesis | baseline | model | dataset_ver | precision | target hw | mAP@.5:.95 | recall | FPS | latency | VRAM | power | gpu_h | decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| _(example — delete when the first real run lands)_ | | | | | | | | | | | | | | |
| EXP-20260901-01 | establish baseline detector on target Jetson | SELF | _tbd_ | _tbd_ | FP16 | _tbd_ | — | — | — | — | — | — | — | — |
