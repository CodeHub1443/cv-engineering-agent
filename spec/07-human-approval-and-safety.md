# CV Engineering Agent — Human Approval and Safety

**Version:** V1.0  
**Status:** Foundational specification

## Purpose

Define how the agent distinguishes autonomous planning from actions requiring explicit human approval.

## Policy Classes

~~~text
AUTO
ASK
DENY
~~~

| Action | Default |
|---|---|
| Read project files | AUTO |
| Inspect repository | AUTO |
| Research web | AUTO |
| Analyze dataset | AUTO |
| Generate requirements/design | AUTO |
| Generate experiment plan | AUTO |
| Create code on authorized feature branch | AUTO |
| Run small/local low-cost validation | AUTO / policy dependent |
| Start materially expensive training | ASK |
| Run large GPU training | ASK |
| Start broad hyperparameter sweep | ASK |
| Consume significant paid compute/API budget | ASK |
| Install/upgrade system drivers or GPU runtime | ASK |
| Change power/thermal/performance mode | ASK |
| Modify system packages or kernel/runtime configuration | ASK |
| Modify production deployment | ASK |
| Deploy model/software | ASK |
| Publish externally | ASK |
| Delete data/artifacts | DENY by default |

Project-specific policy may tighten these defaults.

## Approval Semantics

Approval is:

- explicit;
- attributable;
- scoped to a clearly bounded action;
- recorded in project state.

~~~text
Approval to plan ≠ approval to execute.

Approval for one experiment ≠ approval for an unbounded sweep.

Approval for staging ≠ approval for production.
~~~

## Resource Budgeting

Before materially expensive execution, the system should estimate and, where possible, enforce:

- GPU-hours;
- API/token cost;
- wall-clock runtime;
- storage;
- data volume;
- concurrency.

An operation crossing the configured risk/cost threshold requires approval.

## Policy Enforcement

Safety must be enforced outside the LLM through the runtime/tool layer.

The enforcement layer should evaluate:

~~~text
action
actor
target
cost
risk
environment
authorization
approval
~~~

## Repository Safety

Current development policy:

~~~text
main
  = OFF LIMITS to normal agent development

dev-munna
  = development integration trunk

feature/*
  = short-lived implementation branches
~~~

The agent creates feature branches from dev-munna. Feature PRs target dev-munna.

Promotion from dev-munna to main belongs to the Official Project Manager process.

## Data and Privacy

The system should minimize sensitive data exposure.

Do not send project data to external providers unless:

- the operation is authorized;
- the selected provider is permitted;
- the data-handling policy allows it.

## Failure / Uncertainty

When authorization, policy, or safety is ambiguous:

~~~text
STOP
 ↓
record uncertainty
 ↓
request clarification / approval
~~~

Do not guess.


## Platform-Sensitive Actions

System-level installation and performance changes must use a verified PlatformProfile. The agent must not execute Linux-specific or Jetson-specific commands on another platform. Hardware/driver/toolkit changes require the applicable approval policy.
