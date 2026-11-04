# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-11-04 · **Phase:** 5e/6 — merges complete; ADR-0019 foundation on main (fake runtimes only).
Annotation review paused (47 of 63 labelled).
**Health:** Linux CI (#80): ruff clean, mypy ok (85 files), pytest 1893 passed / 26 skipped. Windows local: 31
known Linux-only failures (the Windows-only baseline). Linux CI is the authoritative baseline.

## Where we are

origin/main = ffd89e4. Merged: #69 (4f93352), #79 (96b2f4b), #77 (42bd16e), #80 (ffd89e4); #71 and #73 were
auto-marked merged; Issues #76 and #78 are closed. Housekeeping PR (issue #81) records D-086/D-087 and the
approval-policy alignment. If this file disagrees with `git log origin/main`, trust git and rewrite this file.

**Ledger: 10 records, unchanged** (sha256 `9251eb0c…8fef8fa`, full value in JOURNAL).

**Done:**
- **EXP-20261004-01..04** (measurement only): 640 SELF FP16-requested, 960, 1280, FP32 640 control. EXPERIMENTS.md.
- **Failure analysis** (#75) and the **annotation-label review** (34 valid, 5 error, 8 ambiguous, 16 unlabelled; not
  representative, no error rate claimed): see `docs/experiments/`.
- **ADR-0019 training pipeline foundation** (D-079, D-081, D-084): approval-gated job lifecycle and the acceptance
  comparer. Fake runtimes only; no real training runtime. Acceptance approves the design, not a run.

## Decisions in force

- **D-077:** precision floor 0.75 at conf 0.25 (fixed-threshold, never mAP). **D-078:** both APs must improve;
  +0.010 / +0.020 are provisional.
- **D-080 / D-087:** standing authorization for local tools and GPU runs, no per-run wait and no cap. Each run
  records a cost estimate and an approval reference issued under the grant, bound to one experiment and one cost
  ceiling, and reports it to the owner at launch. ADR-0018 §6 idle-GPU and process checks still apply.
  APPROVALS.md and ADR-0018 are amended accordingly.
- **D-082 (Q32 b):** the baseline is FP16-requested EXP-20261004-01; `-04` is not the baseline.
- **D-084:** ADR-0019 Accepted. **D-086:** Pillow declared (dev and diagnosis extras).

## Open (owner)

1. **Q32** (a) run-to-run variance, (c) delta rationale, (d) the meaning of "improve". The gains stay provisional.
2. **Q27**, **Q31**, **Q33** (typed identities); M4 wording PR; labels for ranks 011, 013, 027 and whether to
   review ranks 051–063 (annotation labels).

## Next actions

1. The owner chooses the next development track.
2. M4 wording PR (`evaluation_records.py:566`, `docs/EVALUATION.md:46`).
3. Q32(a) and (c).

## Do not start yet

Any GPU run without a cost estimate and a standing-grant approval reference bound to one experiment and cost
ceiling, an idle GPU and process provenance (D-080/D-087, ADR-0018 §6). A real training runtime (needs its own
issue). Model swaps (Q25). NMS or crowd experiments. TensorRT, DeepStream, Model Optimizer. Stopping or
controlling another project's processes.
