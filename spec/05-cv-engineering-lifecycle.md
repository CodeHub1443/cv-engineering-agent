# CV Engineering Agent — CV Engineering Lifecycle

**Version:** V1.1
**Status:** Technical elaboration of `docs/PROJECT.md` §6 (frozen canon, cited as
`[P§n]`) and `docs/GLOSSARY.md`'s stage table. The canonical 14-stage lifecycle
(`DISCOVER → DEFINE → RESEARCH → DESIGN → DATA → BASELINE → TRAIN → EVALUATE →
DIAGNOSE → OPTIMIZE → BENCHMARK → DEPLOY → MONITOR → ITERATE`) is defined once, in
`docs/PROJECT.md` §6 — it is not redefined here. This file elaborates each stage's
inputs/outputs/decision contract beyond what `docs/GLOSSARY.md`'s one-line-per-stage
table carries.

> **Implementation status:** none of this is built yet. No stage workflow exists in
> `cv_agent/` today. See `docs/state/STATUS.md`. Do not read this file as a
> description of current behavior.

## Stage Contract

Each stage should define:

- inputs;
- outputs;
- decisions;
- artifacts;
- acceptance criteria;
- required evidence;
- conditions requiring fresh research;
- conditions requiring human approval.

## Discover / Define

Convert an ambiguous business request into a structured project understanding and technical requirements, including as applicable:

- operational objective and success condition;
- events/classes/tasks;
- camera and scene constraints;
- temporal requirements;
- accuracy/recall/false-positive targets;
- latency/throughput;
- hardware;
- data availability;
- deployment environment;
- operational response requirements.

Ask only the questions necessary to remove material uncertainty. Missing requirements must remain explicit unknowns until answered or safely bounded.

## Research

Research is used to reduce uncertainty around problem formulation, architecture, data, algorithms, tooling, and deployment. Current or changing information must be researched rather than assumed from static model knowledge.

Relevant sources may include official documentation, primary repositories, papers, benchmarks, verified engineering implementations, practitioner reports, and professional/community discovery signals. Evidence must retain provenance, authority, verification state, and freshness.

## Design / Problem Formulation

Determine what CV problem actually represents the business requirement and design the complete system rather than defaulting to a single model.

Possible formulations include:

- detection;
- classification;
- segmentation;
- pose;
- tracking;
- temporal/action recognition;
- geometry/ground-plane reasoning;
- anomaly detection;
- classical CV;
- hybrid systems.

For real-time CCTV, consider camera placement, field of view, blind spots, frame rate, compression, RTSP/decoding, buffering, frame dropping, zones, calibration, tracking, temporal consistency, and multi-camera constraints where relevant.

The agent must not assume the task is object detection merely because objects are involved.

## Data / Dataset

Audit data before committing to a training strategy. Check:

- annotation quality and consistency;
- class balance;
- camera/scene/lighting coverage;
- hard negatives;
- edge cases;
- annotation and sampling bias;
- leakage;
- train/validation/test independence;
- dataset/version lineage.

For video/CCTV data, avoid correlated-frame leakage and consider camera, scene, time, sequence, and identity boundaries where relevant. The agent should recommend annotation, active-learning, synthetic-data, and augmentation strategies according to the problem rather than applying them by default.

## Baseline

Establish a reproducible baseline before optimization. Record model, dataset version, input, precision, hardware, software/runtime, benchmark procedure, accuracy metrics, and performance metrics.

The baseline is the reference against which subsequent experiments are compared; it must not be silently overwritten.

## Model Selection

When alternatives materially differ, produce a comparison based on:

- task suitability;
- accuracy and error profile;
- latency/throughput;
- memory;
- training/data requirements;
- deployment compatibility;
- maturity;
- evidence.

Modern architecture families are candidates, not commitments. The agent must remain architecture-agnostic and select based on the problem and measured constraints.

## Experiment Design

Each experiment must have a defined objective/hypothesis, reproducible configuration, resource budget, and expected decision criterion.

## Training

Training must be reproducible and subject to approval for materially expensive execution. The agent may propose transfer learning, augmentation, loss/optimizer/scheduler choices, mixed precision, gradient clipping, regularization, distillation, architecture modification, distributed training, or other justified methods.

Expensive NAS or hyperparameter searches require a cost/benefit assessment and appropriate approval before execution.

## Evaluation

Use task-appropriate held-out evaluation and include per-class metrics, confusion/error analysis, and threshold analysis when useful. Evaluation must distinguish model quality from system performance.

## Diagnose

Failure analysis should classify errors, identify probable root causes, quantify their impact where possible, and produce targeted follow-up experiments. Typical categories include small objects, occlusion, blur, illumination, camera angle, compression, class confusion, localization errors, domain shift, temporal instability, tracking failures, and annotation errors.

## Optimize

Optimization must start from a reproducible baseline and measured bottleneck. Candidates may include architecture changes, distillation, pruning, quantization, TensorRT, ONNX optimization, kernel fusion, CUDA/kernel optimization, DeepStream optimization, or NAS when justified.

NAS is an optional optimization instrument, not a default methodology.

## Benchmark

Measure system performance separately from model accuracy. Where applicable distinguish:

~~~text
Decode
Preprocess
Inference
Postprocess
Tracking
Event Logic
End-to-End
~~~

Record hardware and software environment for every material benchmark. Never claim an optimization or speedup without comparable measurements.

## Deploy / Monitor

Deployment decisions must account for hardware, runtime, packaging, reliability, observability, rollback, and production validation. Production monitoring should cover model behavior, data/scene changes, stream health, latency, throughput, CPU/GPU/memory usage, power, and thermal behavior where applicable.

Production-changing actions require approval.

## Iterate

A completed stage may trigger a return to an earlier stage when evidence indicates that assumptions, requirements, data, architecture, or constraints were incorrect or incomplete.
