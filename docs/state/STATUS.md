# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-10-04 · **Phase:** 5d — ADR-0017 accepted (D-073); owner-review blocking changes implemented;
**no GPU run; recording writer not run against real artifacts** · **Health:** green on repository
tests; amber on experiment readiness

## Where we are

Branch `feature/claude/experiment-provenance-recovery` (worktree `/home/dev/cv-engineering-agent-sweep`).
Committed on the branch. **Not pushed, not merged.**

**Done (six blocking changes from the ADR-0017 review):**
1. `quantize=16` replaces the deprecated `half=True` in the measured wrapper. `run.json` records the
   exact requested-precision label.
2. Historical precision corrected in EXPERIMENTS.md: EXP-20260930-01 and the sweep rows ran FP32, so
   EXP-20261004-01 is FP16-requested and NOT like-for-like. Historical rows are unedited.
3. `--approval-ref` is mandatory at GPU-run time, recorded in `run.json`, and the writer requires all
   three runs to carry the same reference.
4. Peak VRAM (nvidia-smi polling) and peak RAM (`getrusage`, Linux KiB to MiB) are required. `gpu_hours`
   is derived from wall time and labelled as derived.
5. ADR-0017 §4a states the operator-run exception to the ADR-0013/ADR-0009 JobExecutor path, limited to
   this series.
6. ADR-0017 §3.2 states that verification is all-or-nothing and ledger writes are sequential, not transactional.

**Validation:** full pytest 1713 passed, 4 skipped, 0 failed (before a final typing-only fix; the
record tests and mypy re-checked after it). `ruff check .` clean. `mypy cv_agent` clean (81 files).

## Next (owner)

1. ~~Accept ADR-0017~~ **Done 2026-10-04 (D-073):** ADR-0017 is Accepted.
2. **Approve the GPU run** for EXP-20261004-01 and supply the approval id as `--approval-ref`. This is the only remaining owner action before execution.
3. Dry-run the writer on the three real run directories before writing anything.

## Blockers

- The recording writer has only been tested on synthetic runs. The first real run is the first end-to-end check.
- Historical records keep their original precision labels; the correction lives in EXPERIMENTS.md only.
- Q30, Q31, Q27 and D-069 remain OPEN. None blocks the measurement.

## Do not start yet

EXP-20261004-01 execution before the owner's approval reference (ADR-0017 is accepted). Training. Model swaps (Q25).
NMS or crowd experiments. Any precision floor, recall target, or operating point (Q30). TensorRT,
DeepStream, Model Optimizer. Pushing or merging this branch without owner review.
