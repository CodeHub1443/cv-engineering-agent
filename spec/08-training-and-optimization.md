# CV Engineering Agent — Training and Optimization

**Version:** V1.0  
**Status:** Foundational specification

## Training Loop

~~~text
Dataset Audit
   ↓
Experiment Proposal
   ↓
Approval (when required)
   ↓
Training
   ↓
Evaluation
   ↓
Benchmark
   ↓
Failure Analysis
   ↓
Next Experiment Proposal
~~~

The loop may repeat while the project remains within approved scope and resource limits.

## Experiment Contract

Every material experiment should define:

~~~text
experiment_id
parent_experiment_id
objective
hypothesis
success_criteria

dataset_version
dataset_split
code_commit

model
model_configuration
training_configuration

hardware
software_environment
seed
resource_budget
approval_reference

execution_status
artifacts
metrics
benchmark_results
decision
~~~

## Reproducibility

Record, where applicable:

- dataset/version and split;
- source/code commit;
- model and model configuration;
- training configuration;
- optimizer and scheduler;
- augmentations;
- input resolution;
- batch size;
- random seed;
- software environment;
- hardware;
- checkpoints/artifacts;
- evaluation metrics;
- benchmark results.

## Training Strategy

The agent may propose:

- transfer learning;
- data augmentation;
- loss selection;
- optimizer/scheduler selection;
- mixed precision;
- gradient clipping;
- regularization;
- distributed training;
- knowledge distillation;
- architecture modification.

Recommendations must include assumptions, expected trade-offs and decision criteria.

## Baseline

A baseline is an immutable reference configuration and measured result used to compare subsequent changes.

It should record:

~~~text
model
dataset
input
precision
hardware
software/runtime
benchmark procedure
accuracy metrics
performance metrics
~~~

## Optimization Loop

~~~text
Baseline
   ↓
Profile
   ↓
Identify Bottleneck
   ↓
Generate Candidates
   ↓
Select Candidate
   ↓
Approval (when required)
   ↓
Optimize
   ↓
Re-evaluate with comparable procedure
   ↓
Benchmark
   ↓
Accept / Reject
~~~

## Optimization Candidates

Potential candidates include:

- ONNX graph optimization;
- TensorRT;
- FP16;
- INT8 PTQ;
- QAT;
- pruning;
- distillation;
- layer/block replacement;
- channel/resolution search;
- kernel fusion;
- CUDA/kernel optimization;
- DeepStream pipeline optimization.

Use only when justified by measured bottlenecks and constraints.

## NAS

NAS is optional.

Use NAS when:

- current candidates do not satisfy the target Pareto requirements;
- the search space is meaningful;
- sufficient compute budget exists;
- evaluation is well-defined;
- expected value exceeds search complexity.

When an existing architecture meets the requirements, select and validate it rather than running NAS by default.

## Acceptance Criteria

An optimization is accepted only when measured results satisfy the project's stated constraints and the trade-off is acceptable.

Possible dimensions:

~~~text
accuracy
recall
precision
latency
throughput
memory
power
deployment compatibility
operational complexity
~~~

The agent must never fabricate before/after measurements.
