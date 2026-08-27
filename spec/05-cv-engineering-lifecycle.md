# CV Engineering Agent — CV Engineering Lifecycle

**Version:** V1.0  
**Status:** Foundational specification

## Lifecycle

~~~text
Requirement Discovery
        ↓
Initial Research / Problem Framing
        ↕
Problem Formulation
        ↓
System Architecture
        ↓
Data / Dataset Audit & Design
        ↓
Model Selection
        ↓
Experiment Design
        ↓
Training
        ↓
Evaluation
        ↓
Benchmarking
        ↓
Failure Analysis
        ↓
Optimization / Architecture Search
        ↓
Deployment
        ↓
Production Validation
        ↓
Monitoring
~~~

The arrows do not imply irreversible transitions. Research, formulation, architecture, data, evaluation and optimization may loop when evidence requires it.

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

## Requirement Discovery

Convert an ambiguous business request into structured technical requirements, including as applicable:

- events/classes/tasks;
- camera and scene constraints;
- temporal requirements;
- accuracy/recall/false-positive targets;
- latency/throughput;
- hardware;
- data availability;
- deployment environment;
- operational response requirements.

Missing requirements must remain explicit unknowns until answered or safely bounded.

## Problem Formulation

Determine what CV problem actually represents the business requirement.

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

The agent must not assume the task is object detection merely because objects are involved.

## Research

Research is used to reduce uncertainty around problem formulation, architecture, data, algorithms, tooling, and deployment.

## Data / Dataset

Audit data before committing to a training strategy. Check:

- annotation quality;
- class balance;
- camera/scene coverage;
- hard negatives;
- edge cases;
- leakage;
- train/validation/test independence.

For video/CCTV data, avoid correlated-frame leakage and consider camera, scene, time, sequence and identity boundaries where relevant.

## Model Selection

When alternatives materially differ, produce a comparison based on:

- task suitability;
- accuracy;
- latency;
- memory;
- training/data requirements;
- deployment compatibility;
- maturity;
- evidence.

Do not choose a model solely because it is popular.

## Experiment Design

Each experiment must have a defined objective/hypothesis and expected decision criterion.

## Training

Training must be reproducible and subject to approval for materially expensive execution.

## Evaluation

Use task-appropriate held-out evaluation and include per-class/error analysis when useful.

## Benchmarking

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

## Failure Analysis

Failure analysis should classify errors, identify probable root causes and produce targeted follow-up experiments.

## Optimization / NAS

Optimization must start from a reproducible baseline and a measured bottleneck.

NAS is optional. Use it only when the architecture gap, search space, constraints and compute budget justify it.

## Deployment

Deployment decisions must account for hardware, runtime, packaging, reliability, monitoring, rollback and production validation.

Production-changing actions require approval.
