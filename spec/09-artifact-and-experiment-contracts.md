# CV Engineering Agent — Artifact and Experiment Contracts

**Version:** V1.0  
**Status:** Foundational specification

## Purpose

Define durable records that make CV engineering decisions reproducible and auditable.

## Artifact Contract

A material artifact should have:

~~~text
artifact_id
artifact_type
project_id
created_by
created_at
source_run
source_experiment
git_commit
dataset_version
content_uri
content_hash
metadata
status
~~~

Artifact types may include:

~~~text
requirements
research_report
evidence_record
problem_formulation
architecture_decision
dataset_audit
dataset_specification
model_profile
model_artifact
training_config
training_result
evaluation_report
benchmark_report
failure_analysis
optimization_report
deployment_spec
deployment_artifact
model_card
~~~

Binary artifacts should be referenced by URI and content hash rather than embedded in agent state.

## Experiment Contract

A material experiment should have:

~~~text
experiment_id
parent_experiment_id
project_id
objective
hypothesis
success_criteria

dataset_version
dataset_split
code_commit

model
model_config
training_config

hardware
software_environment
seed
resource_budget
approval_reference

status
metrics
benchmark_results
artifacts
decision
created_at
completed_at
~~~

## Lineage

~~~text
Requirement
   ↓
Experiment
   ↓
Dataset Version
   ↓
Code Commit
   ↓
Model / Config
   ↓
Execution
   ↓
Metrics
   ↓
Artifacts
   ↓
Decision
~~~

The system should support parent/child experiment relationships so follow-up experiments preserve lineage.

## Decision Record

Material engineering decisions should record:

~~~text
decision_id
question
options_considered
selected_option
reason
evidence
constraints
assumptions
risk
approver
created_at
~~~

## Immutability

Completed baseline measurements, experiment results and released artifacts must not be silently overwritten.

Corrections should create a new version or superseding record while preserving historical lineage.

## Reproducibility

A material result should be reproducible from its recorded dataset, code, configuration, environment and execution metadata, subject to external infrastructure constraints.

## Storage

The exact experiment/artifact backend is TBD.

The contracts must not depend on a specific tracking or object-storage product.
