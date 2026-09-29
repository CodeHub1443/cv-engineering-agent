# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-29 · **Phase:** 5c (pin contract + VRAM measurement complete) ·
**Health:** green

## Where we are

ADR-0014 + real research (D-053) + baseline wiring (D-054) + YOLO inference binding (D-055)
+ pin contract fix (D-056) + VRAM measurement (D-057) all on
`feature/claude/adr-0009-second-binding`. 1500 tests, 4 skipped. Ruff clean. Mypy clean.

- `cv_agent/execution/host.py` — `HostProfile.vram_mb`, `_parse_vram_mb()`, `_measure_vram_mb()`,
  real VRAM check in `verify()` (fail-closed, ADR-0013 §3.3)
- `cv_agent/execution/jobs/runtimes/yolo_inference.py` — verified binding for `yolo-inference`
- `scripts/run_baseline.py` — ready-to-run baseline script using `registry.pin()` (D-056 fix)
- `cv_agent/graph/experiment_wiring.py` — `ExperimentContext`, `job_result_to_experiment_record()`

## Baseline readiness

`scripts/run_baseline.py` is architecture-complete and passes all pre-flight checks. **Requires
Tanvir to execute manually** (approval gate is live — `approved=True` in the request, guarded by
`expected_binding_pin`). Two remaining runtime blockers:

1. **Video fixture missing:** `tests/fixtures/person_detection_sample.mp4` not committed. The
   script will `sys.exit()` at the fixture check. Commit a short royalty-free clip to unblock.
2. **CUDA driver:** RTX 3060 present (12288 MiB, driver 535.309.01, CUDA 12.2). Torch requires
   CUDA 13.0+ for +cu130. GPU inference blocked; CPU fallback (`device=cpu`) works but won't
   produce GPU latency data. Either upgrade driver or change `device=0` → `device=cpu` in the
   script for a CPU baseline.

## Manual run command (once fixture exists)

```
cd /home/dev/cv-engineering-agent && python3 scripts/run_baseline.py
```

## Next 3 actions

1. **Commit video fixture** to `tests/fixtures/person_detection_sample.mp4` OR change device to cpu.
2. **Run** `python3 scripts/run_baseline.py` manually (approval gate live).
3. **After successful baseline:** update JOURNAL/EXPERIMENTS, then open PR for this branch.

## Blockers

- Video fixture not committed (integration test unconditionally skipped; baseline script exits)
- CUDA 12.2 vs torch +cu130 mismatch (GPU path blocked; CPU fallback available)
- ANTHROPIC_API_KEY not set (LLM uses FakeLLMProvider; acceptable for D-053 research)

## Do not start yet

Training, NAS, optimization, evaluation, TensorRT, DeepStream, AgentState wiring for model
selection (requires ADR if shape changes), second LLM provider, embeddings/vector search `[P§34]`.
