# APPROVAL GATES

Derived from `[P§24]`, `[P§29.8]`, `[P§10]`, `[P§11]`.

> The agent must never silently consume hundreds of GPU-hours `[P§24]`. Autonomy is
> bounded by consequence, not by confidence.

## The rule

An action requires explicit human approval if it is **expensive, destructive,
irreversible, production-affecting, or externally consequential** `[P§3]`.

Before asking, the agent **estimates the cost**. "May I train?" is not an approval
request. "This is ~14 GPU-hours ≈ $X on the configured backend, producing N checkpoints,
comparing against EXP-…" is.

## Gated actions

| Action | Gate | Estimate required |
|---|---|---|
| Training run | ⛔ always | GPU-hours, wall time, cost, storage |
| Hyperparameter sweep | ⛔ always | runs × cost, search space size |
| NAS `[P§11]` | ⛔ always, **plus** a written justification that the baseline bottleneck warrants it | as above + why NAS over cheaper options |
| Cloud GPU allocation | ⛔ always | instance, hours, $ |
| Dataset mutation (delete, relabel, overwrite, re-split) | ⛔ always | files affected, reversible y/n |
| Production deployment | ⛔ always | target, rollback plan, blast radius |
| Model promotion to "recommended" | ⛔ always | benchmark table vs. baseline |
| External API spend above threshold | ⛔ always | $ |
| Writing to any path outside the workspace | ⛔ always | paths |
| Install/upgrade system drivers or GPU runtime | ⛔ always | what changes, rollback path |
| Change power/thermal/performance mode | ⛔ always | current vs. target mode, why |
| Modify system packages or kernel/runtime configuration | ⛔ always | packages/settings affected |
| Long-running profiling on shared hardware | ⚠️ notify + proceed | duration |
| Read-only research, retrieval, analysis | ✅ free | — |
| Code, docs, config, tests inside the repo | ✅ free (still via PR) | — |
| Dry-run / cost-estimation of any gated action | ✅ free | — |

### Platform-sensitive actions

System-level installation, driver, and performance changes must use a verified
platform profile (OS, architecture, GPU, driver/runtime state). The agent must not
execute Linux-specific or Jetson-specific commands on another platform. This applies
in addition to the approval gates above, not instead of them.

### Data and privacy

The agent must minimize sensitive project-data exposure. Do not send project data to
an external provider (LLM API, research tool, third-party service) unless the
operation is authorized, the provider is permitted, and the data-handling policy
allows it.

## Thresholds

*Placeholders — see `OPEN_QUESTIONS.md` Q6. Set these before Phase 2.*

| Threshold | Value |
|---|---|
| GPU-hours requiring approval | any > `TBD` |
| Cost requiring approval | any > `$TBD` |
| Wall-clock requiring approval | any > `TBD` hours |
| Files a dataset op may touch without approval | `0` — always gated |

## Approval record

Every granted approval is recorded and referenced by the run it authorized. Minimum
fields: `approval_id`, timestamp, requester (agent/session), action, estimate presented,
approver, scope (one run / N runs / until date), and the `exp_id` it authorized.

An approval is **specific and non-transferable**: approval for experiment A is not
approval for experiment B, and approval to train is not approval to deploy.

## Agent behavior at a gate

1. Assemble the estimate. If the estimate cannot be made, say so — an un-estimable action
   is not approvable.
2. State the alternative that avoids the cost, and why it is insufficient
   (`[P§29.2]` — has the baseline been measured?).
3. Ask once, clearly, and **stop**. Do not begin preparatory work that implies the answer.
4. On denial, record it in `JOURNAL.md` and propose the cheaper path.
