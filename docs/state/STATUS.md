# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-11-04 · **Phase:** 5e — ADR-0019 Accepted (D-084); D-083 merge sequence in progress
(#69 → provenance-recovery, which brings #71 and #73 → #76). Annotation review paused (47 of 63 labelled).
**Health (Windows, 2026-11-04):** 31 failed / 1882 passed / 6 skipped; the 31 are the Windows-only baseline (identical
by node ID before and after). #76 files 100 passed; ruff clean; mypy 1 known error (linux_nvidia SIGKILL). No Linux run.

## Where we are

Branch `feature/claude/76-training-execution-pipeline`, stacked on `feature/claude/experiment-provenance-recovery`.
Merge sequence (D-085): Claude Code opens and merges each PR with a merge commit once CI is green; it stops at
the first failure. #71 and #73 are never merged directly. See JOURNAL 2026-11-04 for the audit. If this file
says merges are pending but main already contains them, trust `git log origin/main` and rewrite this file.

**Ledger: 10 records, unchanged** (sha256 `9251eb0c…8fef8fa`, full value in JOURNAL).

**Done:**
- **EXP-20261004-01..04** (measurement only): 640 SELF FP16-requested, 960, 1280, FP32 640 control. EXPERIMENTS.md.
- **Failure analysis** (#75) and the **annotation-label review** (34 valid, 5 error, 8 ambiguous, 16 unlabelled; not
  representative, no error rate claimed): see `docs/experiments/`.
- **#76 (ADR-0019 Accepted; D-079, D-081, D-084):** training job lifecycle and approval gate (approval bound to one
  experiment, "single run" scope and a cost ceiling; default controller `for_repository` checks a clean, matching
  HEAD) and the acceptance comparer (both APs must improve, precision >= 0.75 at conf 0.25, like-for-like
  precision/resolution/model). Fake runtimes only; no training runtime. Acceptance approves the design, not a run.

## Decisions in force

- **D-077:** precision floor 0.75 at conf 0.25 (fixed-threshold, never mAP). **D-078:** both APs must improve;
  +0.010 / +0.020 are provisional.
- **D-080:** standing authorization for local tools and GPU runs; each run still records an approval reference bound
  to one experiment and one cost ceiling, and the ADR-0018 §6 idle-GPU and process checks apply. Conflicts with
  ADR-0018 §6 wording and the APPROVALS.md table until ADR-0018 is amended.
- **D-082 (Q32 b):** the baseline is FP16-requested EXP-20261004-01; `-04` is not the baseline.
- **D-083 / D-085:** merge bottom-up with merge commits; the video fixture is kept; #76 is one PR.

## Open (owner)

1. **Q32** (a) run-to-run variance, (c) delta rationale, (d) the meaning of "improve". The gains stay provisional.
2. **Q27**, **Q31**, **Q33** (typed identities); labels for ranks 011, 013, 027; whether to review ranks 051–063.

## Next actions

1. Finish the merge sequence and verify main contains all three PRs.
2. Linux/WSL full-suite baseline; ADR-0018 amendment for the D-080 standing grant.
3. M4 wording PR (`evaluation_records.py:566`, `docs/EVALUATION.md:46`); Q32(a) and (c).

## Do not start yet

Any GPU run without a standing-grant approval reference bound to one experiment and cost ceiling, an idle GPU and
process provenance (D-080, ADR-0018 §6). A real training runtime (needs its own issue).
Model swaps (Q25). NMS or crowd experiments. TensorRT, DeepStream, Model Optimizer. Stopping or controlling another
project's processes.
