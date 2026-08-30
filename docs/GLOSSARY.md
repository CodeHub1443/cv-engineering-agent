# GLOSSARY

Shared vocabulary. Terms defined here mean exactly this in code, ADRs, issues, and
commits. Where the canon defines a term, the canon wins `[P§23]`.

## The four that must never blur `[P§23]`

| Term | Definition | Example |
|---|---|---|
| **Capability** | *What* the system can accomplish. A typed identity in the registry. | `model.optimize.quantization` |
| **Skill** | Specialized procedural knowledge for accomplishing a capability. | NVIDIA Model Optimizer PTQ skill |
| **Tool** | An executable interface. | a TensorRT profiling command |
| **Agent** | An autonomous reasoning/execution worker. | CUDA optimization agent |

Resolution chain: `user task → required capability → appropriate skill → required tools →
execution agent`.

## Lifecycle stages `[P§6]`

`DISCOVER → DEFINE → RESEARCH → DESIGN → DATA → BASELINE → TRAIN → EVALUATE → DIAGNOSE →
OPTIMIZE → BENCHMARK → DEPLOY → MONITOR → ITERATE`

Not every project requires every stage; **the agent decides which are necessary** `[P§6]`.
A stage is a state in the orchestration graph, not a folder.

| Stage | Owns | Exit condition |
|---|---|---|
| DISCOVER | eliciting the operational problem `[P§5]` | the user's problem is stated in observable terms |
| DEFINE | class/event definitions, constraints, success criteria | written definitions incl. edge cases, target metrics, hardware, latency, FP tolerance |
| RESEARCH | current external knowledge `[P§16]`–`[P§18]` | candidate approaches with cited, dated evidence |
| DESIGN | CV task decomposition + system architecture `[P§4]` | architecture with justified component choices |
| DATA | dataset strategy, manifest, splits `[P§26]` | versioned dataset, leakage checks passed |
| BASELINE | first measured system `[P§29.2]` | accuracy + latency + memory + power recorded |
| TRAIN | experiment execution `[P§10]`, `[P§24]` | approved runs completed, ledger rows written |
| EVALUATE | measurement `[P§12]` | composite result vs. target constraint |
| DIAGNOSE | failure analysis `[P§27]` | ranked failure categories + root-cause hypotheses |
| OPTIMIZE | model/pipeline for target `[P§14]` | measured gain vs. baseline with accuracy re-check |
| BENCHMARK | quantitative comparison `[P§29.10]` | comparison table under identical conditions |
| DEPLOY | production integration `[P§13]` | approved deployment + rollback plan |
| MONITOR | drift and system health `[P§28]` | deviation from validated baseline detected |
| ITERATE | next-experiment decision | new hypothesis entering TRAIN or DATA |

## Architectural terms

- **Canon** — `docs/PROJECT.md`, frozen, cited as `[P§n]`.
- **ADR** — Architecture Decision Record; the only vehicle for architectural change.
- **Rolling state** — `docs/state/*`; `STATUS.md` is state, the rest is history.
- **Boundary test** — the `[P§34]` question every module must answer.
- **Gate** — an action requiring human approval `[P§24]`.
- **Provenance** — source, class, and date attached to any retrieved knowledge `[P§18]`.
- **Freshness horizon** — how long a retrieved fact stays trustworthy `[P§18]`.
- **Operating point** — the threshold at which a metric is reported `[P§12]`.
- **Baseline** — the measured reference an improvement is claimed against `[P§29.2]`.

## Metric shorthands `[P§12]`

`mAP@0.5` · `mAP@0.5:0.95` · `IoU` · `PR-AUC` · `ROC-AUC` · `MOTA` · `IDF1` · `HOTA` ·
`FPS (on target)` · `e2e latency` (capture → decision, **not** inference alone) ·
`inference latency` · `VRAM` · `power`.

"Latency" unqualified always means **end-to-end**. Inference-only latency must be labeled
as such — conflating them is how edge deployments get promised twice their real speed.

## CCTV / real-time terms `[P§9]`

RTSP · decode latency · buffering · frame drop · bitrate · GOP/keyframe interval ·
zone / ROI · zone masking · GPP (ground-plane projection) · homography · camera
calibration · temporal event logic · track fragmentation · ID switch.

## Optimization terms `[P§14]`

PTQ · QAT · calibration set · pruning · structured/unstructured sparsity · kernel fusion ·
TensorRT tactic · engine · FP32/FP16/INT8 · Nsight profile · CUDA kernel · Triton.
