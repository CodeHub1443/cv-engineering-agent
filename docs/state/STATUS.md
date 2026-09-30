# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-30 · **Phase:** 5d — baseline diagnosis complete ·
**Health:** green

## Where we are

Baseline diagnosis (D-063/D-064) complete. Three measurable failure modes identified
from EXP-20260930-01 artifacts. Next experiment proposed (conf threshold sweep) but
NOT yet authorized or executed. Branch `feature/claude/diagnosis-baseline` ready for PR.

NOTE: Branch `feature/claude/adr-0009-second-binding` (D-050–D-062, PR #69) is still
open and not merged. The diagnosis branch targets main independently.

## Key results

**EXP-20260930-01** — yolo11n, COCO val2017, RTX 3060, 5000 images:
  precision=0.791, recall=0.661, mAP@0.5=0.635, mAP@0.5:0.95=0.459
  FPS=99.9 e2e / 188.7 inf-only, VRAM peak=596 MiB

**Diagnosis (EXP-20260930-01, from predictions.json + GT labels):**
- Small objects 2.7× over-represented in completely-missed images (63% vs 24% baseline)
- 17.5% of person predictions in near-threshold band (0.25–0.35)
- High-density images (>5 persons): 677 images, 64% of all GT persons

## Completed this session (2026-09-30)

| D | Work |
|---|---|
| D-063 | ADR-0015 accepted — `cv_agent/diagnosis/` authorized |
| D-064 | Baseline diagnosis: `DetectionEvidence`, `collect_detection_evidence()`, 33 tests, `scripts/run_diagnosis.py` |
| Q27 | Opened: size-stratified mAP blocked by absent `instances_val2017.json` |
| #70 | GitHub issue created for diagnosis milestone |

## Next 3 actions

1. **Open PR** for `feature/claude/diagnosis-baseline` (D-063 → D-064)
2. **After PR #69 merges**: follow-up merge of this branch
3. **Next milestone (NOT yet authorized)**: conf threshold sweep experiment
   (conf ∈ {0.10, 0.15, 0.25, 0.50}) — requires owner approval

## Blockers

- ANTHROPIC_API_KEY not set (FakeLLMProvider acceptable for current work)
- PR #69 (adr-0009-second-binding) not yet merged — this branch from main is independent
- Q27: size-stratified mAP blocked by absent instances_val2017.json (~250 MB)

## Do not start yet

Conf threshold sweep (needs owner approval), training, NAS, optimization, TensorRT,
DeepStream, second LLM provider, AgentState changes (requires ADR).
