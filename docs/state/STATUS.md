# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-11-12 · **Phase:** 5e/6 — ADR-0019 foundation on main (fake runtimes only); LLM gateway v2 accepted, slice G1 in flight.
Annotation review paused (47 of 63 labelled).
**Health:** Linux CI (#80, last measured): ruff clean, mypy ok (85 files), pytest 1893 passed / 26 skipped. Windows local after G1: 31
known Linux-only failures (unchanged baseline), 1946 passed. Linux CI is authoritative; the G1 PR run replaces these numbers.

## Where we are

origin/main = 1559d50 (C2 merged, checked 2026-11-12). In flight: issue #89, slice **G1** on branch
`feature/claude/89-llm-adapter-v2` (adapter v2: no `temperature`, stop-reason policy, usage/request-ID reporting,
`max_retries=0`, the typed `LLMCallError` family) plus the recorded acceptance of ADR-0020; merged under D-090 once CI is
green. If this file disagrees with `git log origin/main`, trust git and rewrite this file.

**Ledger: 10 records, unchanged** (sha256 `9251eb0c…8fef8fa`, full value in JOURNAL).

**LLM gateway v2:** [ADR-0021](../architecture/adr/ADR-0021-llm-credential-source.md) Accepted (D-088: key
`CV_AGENT_ANTHROPIC_API_KEY`, `.env`, no `ANTHROPIC_API_KEY`). [ADR-0020](../architecture/adr/ADR-0020-llm-gateway-v2.md)
**Accepted** by the owner 2026-11-12 (D-092; Q34, Q35, Q36, Q42, Q43, Q44, Q50 answered with the safe defaults): two tiers,
$5/day, 100 calls/day, UTC+06:00 day, call log with `request_id`, default-deny privacy, thinking counted in the 4000-token
cap. Hosted tiers: owner's Windows PC only (it alone holds the key). D-089 model choice (haiku-5-5 fast, opus-5-5 strong).
D-090 merge permission in force. D-091: both PCs are measured CV hosts, no local LLM. Built: C2 credential loader; G1 adapter v2
(this branch). The gateway still runs on the mock; nothing governs a real call until G5.

**Done earlier:**
- **EXP-20261004-01..04** (measurement only) and the failure analysis (#75) / annotation-label review: see `docs/experiments/`.
- **ADR-0019 training pipeline foundation** (D-079, D-081, D-084): approval-gated job lifecycle, acceptance comparer; fake runtimes only.

## Decisions in force

- **D-077:** precision floor 0.75 at conf 0.25 (fixed-threshold, never mAP). **D-078:** both APs must improve;
  +0.010 / +0.020 are provisional. **D-082:** the baseline is FP16-requested EXP-20261004-01.
- **D-080 / D-087:** standing authorization for local tools and GPU runs, no per-run wait and no cap. Each run records a
  cost estimate and an approval reference issued under the grant, bound to one experiment and one cost ceiling.
  ADR-0018 §6 idle-GPU and process checks still apply.
- **D-084:** ADR-0019 Accepted. **D-085:** merge commits once CI is green. **D-086:** Pillow declared.
- **D-088 to D-092:** LLM credential source, model choice, LLM-layer merge permission, no local LLM, gateway v2 (see above).

## Open (owner)

1. **ADR-0020** open questions Q38–Q41, Q46–Q49 (safe defaults recorded).
2. **Q32** (a) variance, (c) delta rationale, (d) meaning of "improve"; gains stay provisional.
3. **Q27**, **Q31**, **Q33** (typed identities); M4 wording PR; annotation labels for ranks 011, 013, 027.

## Next actions

1. Finish slice **G1** (issue #89): CI green, then merge under D-090.
2. Owner puts `CV_AGENT_ANTHROPIC_API_KEY` in the project `.env` on the Windows PC (never printed or committed).
3. Slices **G2** (SQLite call store, `llm-log init`) to **G7**, one issue each.

## Do not start yet

Do not set `[llm] provider` to a real provider until G5. The legacy path is ungoverned and would send the raw
request. Any GPU run without a cost estimate and a standing-grant approval
reference bound to one experiment and cost ceiling, an idle GPU and process provenance (D-080/D-087, ADR-0018 §6). A real
training runtime (needs its own issue). Model swaps (Q25). NMS or crowd experiments. TensorRT, DeepStream, Model
Optimizer. Stopping or controlling another project's processes. Any local LLM tier or GPU contact by the gateway (D1).
