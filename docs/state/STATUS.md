# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-11-12 · **Phase:** 5e/6 — ADR-0019 foundation on main (fake runtimes only); LLM gateway v2 design recorded (D0).
Annotation review paused (47 of 63 labelled).
**Health:** Linux CI (#80, last measured): ruff clean, mypy ok (85 files), pytest 1893 passed / 26 skipped. Windows local: 31
known Linux-only failures (the Windows-only baseline). Linux CI is the authoritative baseline. D0 changes docs only.

## Where we are

origin/main = 20910cb (merge of #84, D0, checked 2026-11-12). In flight: issue #85, slice C1 on branch
`feature/claude/85-env-ignore-deny` (`.env` ignore, Read deny rules, rule 8 secrets sentence); merged under D-090 once CI is green. If this file disagrees with `git log origin/main`, trust git and
rewrite this file.

**Ledger: 10 records, unchanged** (sha256 `9251eb0c…8fef8fa`, full value in JOURNAL).

**LLM gateway v2 (D0):** [ADR-0021](../architecture/adr/ADR-0021-llm-credential-source.md) Accepted (D-088: key
`CV_AGENT_ANTHROPIC_API_KEY`, `.env`, no `ANTHROPIC_API_KEY`). [ADR-0020](../architecture/adr/ADR-0020-llm-gateway-v2.md)
**Proposed** (two tiers, $5/day, 100 calls/day, UTC+06:00 day, call log, default-deny privacy, thinking counted in the
4000-token cap). Hosted tiers: owner's Windows PC only (it alone holds the key). D-089 model choice (haiku-5-5 fast, opus-5-5 strong). D-090 merge permission for LLM-layer PRs **is in force (D0 merged)**. D-091: both PCs are measured CV hosts, no local LLM. No code changed; all on the mock.

**Done earlier:**
- **EXP-20261004-01..04** (measurement only) and the failure analysis (#75) / annotation-label review: see `docs/experiments/`.
- **ADR-0019 training pipeline foundation** (D-079, D-081, D-084): approval-gated job lifecycle and the acceptance
  comparer. Fake runtimes only; no real training runtime.

## Decisions in force

- **D-077:** precision floor 0.75 at conf 0.25 (fixed-threshold, never mAP). **D-078:** both APs must improve;
  +0.010 / +0.020 are provisional. **D-082:** the baseline is FP16-requested EXP-20261004-01.
- **D-080 / D-087:** standing authorization for local tools and GPU runs, no per-run wait and no cap. Each run records a
  cost estimate and an approval reference issued under the grant, bound to one experiment and one cost ceiling.
  ADR-0018 §6 idle-GPU and process checks still apply.
- **D-084:** ADR-0019 Accepted. **D-085:** merge commits once CI is green. **D-086:** Pillow declared.
- **D-088 to D-091:** LLM credential source, model choice, LLM-layer merge permission, no local LLM (see above).

## Open (owner)

1. **ADR-0020** acceptance (Q50) and its open questions Q34–Q36, Q38–Q44, Q46–Q49 (safe defaults recorded).
2. **Q32** (a) run-to-run variance, (c) delta rationale, (d) the meaning of "improve". The gains stay provisional.
3. **Q27**, **Q31**, **Q33** (typed identities); M4 wording PR; annotation labels for ranks 011, 013, 027.

## Next actions

1. Finish slice **C1** (issue #85): CI green, then merge under D-090.
2. Slice **C2**: credentials implementation per ADR-0021 (own issue).
3. Owner decision on **ADR-0020**; then G1–G7.

## Do not start yet

Do not set `[llm] provider` to a real provider until slice G5 lands (the legacy path is ungoverned and would send the raw
request; `claude-opus-5-5` also rejects `temperature`). Any GPU run without a cost estimate and a standing-grant approval
reference bound to one experiment and cost ceiling, an idle GPU and process provenance (D-080/D-087, ADR-0018 §6). A real
training runtime (needs its own issue). Model swaps (Q25). NMS or crowd experiments. TensorRT, DeepStream, Model
Optimizer. Stopping or controlling another project's processes. Any local LLM tier or GPU contact by the gateway (D1).
