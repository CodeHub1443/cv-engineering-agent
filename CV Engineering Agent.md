**CV Engineering Agent — Project Definition**

This should become the **master project description** from which we derive AGENTS.md, CLAUDE.md, architecture docs, roadmap, memory files, and implementation specs.

**1\. What are we building?**

We are building **CV Engineering Agent** — an AI engineering system specialized in taking a computer-vision problem from **problem definition → research → architecture → dataset → training → evaluation → optimization → deployment → benchmarking → monitoring**.

It is not simply a chatbot that knows computer vision.

It is not simply an LLM wrapper.

It is not simply a RAG system.

It is not simply an autonomous coding agent.

It is intended to become an **AI Computer Vision Engineer** that can reason about an actual CV project, select appropriate techniques and tools, execute engineering work through specialized capabilities, evaluate the results, and iteratively improve the system.

The agent should eventually be able to receive something as vague as:

"I have a prison project. They want escape-attempt detection, wall climbing, and maybe some other security analytics."

and turn that into an engineering process.

Instead of immediately proposing YOLO or writing code, it should first determine:

- What exactly constitutes an escape attempt?
- What is the physical environment?
- What cameras exist?
- Camera positions?
- FPS?
- Resolution?
- Lighting?
- Indoor/outdoor?
- Number of cameras?
- Edge or server deployment?
- Jetson/NVIDIA GPU?
- Required latency?
- Required recall?
- False-positive tolerance?
- Is this detection, tracking, action recognition, anomaly detection, segmentation, pose, or a combination?
- What data exists?
- What data must be collected?
- What labels are required?
- What baseline should be established?
- Which existing models are appropriate?
- Which NVIDIA skills/tools are available?
- What recent research or industrial techniques are relevant?

Then it should construct the engineering plan.

**2\. The fundamental problem it solves**

The problem is **CV engineering complexity**.

Modern computer vision is no longer:

collect images

→ train YOLO

→ export TensorRT

→ deploy

A production CV system can involve:

Problem definition

↓

Camera/environment analysis

↓

Dataset strategy

↓

Annotation

↓

Model selection

↓

Training

↓

Evaluation

↓

Failure analysis

↓

Tracking / temporal reasoning

↓

Optimization

↓

Deployment

↓

Hardware profiling

↓

Production monitoring

↓

Iteration

And every stage contains dozens of possible techniques.

The difficult part is not merely knowing that these techniques exist.

The difficult part is deciding:

**Which technique should be used, when, why, and in what combination?**

For example, a prison wall-climbing problem might eventually require:

Object detection

-

person tracking

-

zone definition

-

pose/action recognition

-

temporal reasoning

-

camera geometry

-

possibly optical flow

-

event state machine

rather than simply training an object detector.

The agent's job is to discover that architecture.

**3\. The mission**

The mission is:

**Build an AI engineering agent capable of autonomously reasoning about, researching, developing, training, evaluating, optimizing, benchmarking, and deploying production-grade computer-vision systems while keeping humans in control of consequential decisions.**

There are several important words here.

**Reasoning**

It must understand the engineering problem before selecting a solution.

**Researching**

It must continuously acquire current knowledge rather than relying solely on its pretrained knowledge.

**Developing**

It must generate and modify actual engineering artifacts.

**Training**

It should eventually be capable of executing training workflows itself, subject to appropriate human approval.

**Evaluating**

It must measure whether the solution actually works.

**Optimizing**

It should optimize models and pipelines for the target hardware and operational constraints.

**Benchmarking**

It must compare alternatives quantitatively rather than declaring something "better" based on intuition.

**Deploying**

It must eventually understand real production deployment, particularly NVIDIA/Jetson/TensorRT/DeepStream environments.

**Human control**

Expensive, destructive, irreversible, production-impacting, or externally consequential actions should require explicit approval.

**4\. What makes this different from a generic AI coding agent?**

A generic coding agent thinks primarily:

User request

↓

write code

CV Engineering Agent should think:

User problem

↓

Understand problem

↓

Identify CV task(s)

↓

Identify engineering constraints

↓

Research current approaches

↓

Design solution

↓

Identify required capabilities

↓

Build dataset/training/evaluation plan

↓

Establish baseline

↓

Experiment

↓

Measure

↓

Diagnose

↓

Optimize

↓

Deploy

↓

Monitor

The **engineering lifecycle**, not code generation, is the primary abstraction.

**5\. The agent's core interaction model**

The agent should behave like a **senior CV engineer / technical lead**, not like an autocomplete system.

For example:

**User**

I need to detect garment theft in a factory.

The agent should not immediately say:

Use YOLOv8.

Instead:

I need to understand the operational definition of theft first.

1\. What physically happens when a garment is stolen?

2\. Where are garments allowed to move?

3\. What are the controlled entry/exit points?

4\. Are workers allowed to carry garments?

5\. Are bags allowed?

6\. What camera coverage exists?

7\. How long is the typical theft sequence?

8\. Do you need real-time intervention or post-event investigation?

...

Then it converts the answers into a CV architecture.

**6\. The agent should operate through stages**

The eventual agent should naturally move through these stages:

DISCOVER

↓

DEFINE

↓

RESEARCH

↓

DESIGN

↓

DATA

↓

BASELINE

↓

TRAIN

↓

EVALUATE

↓

DIAGNOSE

↓

OPTIMIZE

↓

BENCHMARK

↓

DEPLOY

↓

MONITOR

↓

ITERATE

Not every project requires every stage.

The agent decides which stages are necessary.

**7\. CV knowledge scope**

The agent should eventually understand the complete CV engineering stack.

That includes, but is not limited to:

**Image fundamentals**

- pixels
- RGB/BGR
- color spaces
- normalization
- resizing
- interpolation
- image quality
- blur
- noise
- compression
- illumination
- camera artifacts

**Dataset engineering**

- dataset design
- annotation strategy
- class definitions
- imbalance
- hard negatives
- edge cases
- train/validation/test splitting
- leakage
- temporal leakage
- camera leakage
- dataset versioning
- augmentation
- synthetic data
- active learning

**Deep learning**

- CNNs
- transformers
- detection
- classification
- segmentation
- pose
- embedding models
- action recognition
- metric learning
- multimodal models
- temporal models
- attention

**Modern architectures**

The agent must not be locked to a fixed architecture list.

It should continuously evaluate current approaches including:

- YOLO-family architectures
- RF-DETR
- DINO-family architectures
- RT-DETR
- Grounding DINO
- SAM-family models
- MobileViT
- EfficientFormer
- NVIDIA TAO models
- other relevant current architectures

The important principle is:

**Architecture selection must be problem-driven, not framework-driven.**

**8\. Classical CV remains part of the agent**

The agent should not become a "deep learning only" system.

Depending on the problem, it should know when classical methods are superior.

Examples:

- ORB
- ECC
- optical flow
- Lucas-Kanade
- MOG2
- KNN background subtraction
- geometric methods
- homography
- camera calibration
- GPP / ground-plane projection
- rule-based temporal logic

For a stable CCTV camera, a lightweight classical method may sometimes outperform a large neural model in cost, latency, or reliability.

The agent should recognize that.

**9\. Real-time CCTV specialization**

This is a major specialization.

The agent must understand that CCTV is fundamentally different from offline image datasets.

It should reason about:

- camera placement
- field of view
- blind spots
- frame rate
- bitrate
- resolution
- compression
- RTSP
- decoding
- stream latency
- buffering
- frame dropping
- temporal consistency
- tracking
- zones
- regions of interest
- camera calibration
- multi-camera systems
- GPU/CPU pipeline behavior

Techniques such as:

- ByteTrack
- BoT-SORT
- Kalman filtering
- zone masking
- optical flow
- background subtraction
- GPP
- temporal event logic

must be considered when appropriate.

**10\. Training intelligence**

The agent should eventually be able to design and execute training experiments.

It should reason about:

**Training**

- optimizer
- learning rate
- warmup
- cosine decay
- warm restarts
- batch size
- mixed precision
- gradient clipping
- regularization
- dropout
- normalization
- label smoothing
- augmentation
- loss functions

**Losses**

It should understand the mathematics and practical tradeoffs behind:

- cross entropy
- focal loss
- IoU losses
- CIoU
- DIoU
- GIoU
- contrastive/metric losses
- Log-Sum-Exp
- task-specific losses

**Hyperparameter optimization**

Potentially:

- grid search
- random search
- Bayesian optimization
- AutoML
- reinforcement-learning-based search

But it should **not automatically run expensive searches**.

It should estimate cost and obtain approval when necessary.

**11\. NAS**

NAS is part of the knowledge base, but the philosophy must be:

**Baseline first. NAS only when justified.**

The agent should not hear "optimize the model" and immediately launch NAS.

It should first establish:

baseline model

↓

baseline accuracy

↓

baseline latency

↓

baseline memory

↓

baseline power

↓

identify bottleneck

↓

determine whether NAS is justified

NAS is an optimization instrument, not the default methodology.

**12\. Evaluation philosophy**

The agent must be measurement-driven.

It should understand:

**Detection**

- Precision
- Recall
- F1
- mAP@0.5
- mAP@0.5:0.95
- IoU
- AP per class

**Classification**

- accuracy
- precision
- recall
- F1
- confusion matrix
- ROC-AUC
- PR-AUC

**Tracking**

- MOTA
- IDF1
- HOTA
- ID switches
- track fragmentation

**System performance**

- FPS
- latency
- end-to-end latency
- inference latency
- throughput
- GPU utilization
- CPU utilization
- VRAM
- RAM
- power
- thermal behavior

The agent should never optimize only one metric.

A model with:

99% mAP

is useless if the target Jetson can only process:

2 FPS

when the application requires:

20 FPS

**13\. Hardware-aware engineering**

Hardware is a first-class constraint.

The agent should understand:

- NVIDIA GPUs
- CUDA
- TensorRT
- ONNX
- DeepStream
- Jetson
- GPU memory
- CPU/GPU synchronization
- decoding
- batching
- kernels
- memory transfers
- kernel fusion
- quantization
- pruning
- TensorRT optimization
- Nsight profiling
- NVIDIA profiling tools

It should eventually be able to answer:

Why is my GPU only 20% utilized while CPU is 40%?

and investigate the entire pipeline rather than simply suggesting "use a bigger GPU."

**14\. Model optimization**

The agent should support:

PyTorch

↓

ONNX

↓

TensorRT

↓

FP32

↓

FP16

↓

INT8

and understand:

- PTQ
- QAT
- calibration
- pruning
- sparsity
- kernel fusion
- layer-wise optimization
- TensorRT tactics
- custom CUDA kernels
- Triton
- CUTLASS/CuTe-related optimization
- profiling

It should measure every optimization against the baseline.

**15\. NVIDIA ecosystem integration**

This is particularly important for this project.

We have decided to leverage the available NVIDIA skills rather than recreate their knowledge manually.

The agent should eventually know how to discover and invoke relevant installed capabilities such as:

**DeepStream**

- pipeline development
- pipeline generation
- model import
- profiling
- deployment

**TAO**

- model training
- fine-tuning
- AutoML
- action recognition
- detection
- segmentation
- OCR
- Re-ID
- metric learning
- pose
- DINO
- RT-DETR
- Deformable DETR
- etc.

**TensorRT**

- ONNX conversion
- C++ runtime
- performance analysis
- TensorRT optimization

**NVIDIA Model Optimizer**

- PTQ
- quantization recipe search
- evaluation
- monitoring
- debugging
- release workflows

**CUDA Agent**

For low-level GPU/kernel optimization when higher-level optimization is insufficient.

The critical architectural principle is:

**The CV Agent should know these capabilities exist and select them when appropriate; it should not duplicate their implementation inside itself.**

**16\. External knowledge**

The agent's knowledge cannot be static.

CV changes too quickly.

Therefore it needs two complementary knowledge mechanisms.

**Persistent knowledge**

Structured/project knowledge such as:

- CV engineering principles
- architecture documentation
- learned project knowledge
- benchmark results
- internal experiments
- NVIDIA documentation
- model documentation
- papers
- engineering guides

This will eventually involve a RAG/knowledge subsystem.

**Live research**

For information that changes frequently, the agent should research the web.

Examples:

- latest YOLO developments
- Roboflow releases
- Hugging Face models
- NVIDIA announcements
- new CV papers
- TensorRT changes
- DeepStream changes
- Jetson developments
- new benchmarks
- GitHub projects
- engineering discussions

**17\. Why LinkedIn matters**

This is an unusual but intentional requirement.

A lot of practical CV engineering knowledge is not published in formal papers.

Engineers publish:

- implementation tricks
- benchmark results
- deployment experiences
- failure cases
- CUDA optimizations
- YOLO modifications
- industrial CV techniques
- dataset strategies
- real-world lessons

on LinkedIn.

Therefore the agent should consider relevant LinkedIn/public professional content as **research signals**, while distinguishing:

peer-reviewed research

official documentation

official repository

engineering blog

professional post

community discussion

They should not all receive the same evidence weight.

**18\. Roboflow / YOLO / Hugging Face / NVIDIA monitoring**

These are important sources for keeping the agent current.

The agent should continuously be capable of researching:

Roboflow

YOLO ecosystem

Hugging Face

NVIDIA

TensorRT

DeepStream

TAO

CUDA

relevant GitHub projects

research papers

professional engineering discussions

But this does **not** mean indiscriminately ingesting everything.

The research system should:

1. find information
2. determine relevance
3. assess credibility
4. extract useful knowledge
5. record provenance
6. record freshness
7. make it available to the reasoning system

**19\. RAG's role**

RAG is important, but **RAG is not the agent**.

The architecture should conceptually be:

CV ENGINEERING AGENT

│

┌────────────────┼────────────────┐

│ │ │

Reasoning Knowledge Tools

│ │ │

LLM Layer RAG/Search MCP

RAG provides knowledge.

The LLM provides reasoning.

Tools provide execution.

LangGraph provides orchestration.

Skills provide specialized expertise/workflows.

These must remain separate.

**20\. LLM architecture**

We deliberately do not want the agent hardwired to one model.

The project should have an abstraction like:

LLM Gateway

│

┌─────────────┼─────────────┐

│ │ │

Claude OpenAI Qwen

│ │

DeepSeek future...

Potential providers include:

- Claude
- OpenAI/Codex-compatible models
- Qwen
- DeepSeek
- future models

The agent should be able to select different models according to task complexity and cost.

For example:

simple classification/routing

↓

cheap model

architecture reasoning

↓

strong reasoning model

code generation

↓

coding-specialized model

research synthesis

↓

strong reasoning model

The provider must therefore be **replaceable**.

**21\. LangGraph's role**

LangGraph is the orchestration layer.

It should manage:

- state
- workflow
- branching
- iteration
- human approval
- tool execution
- retries
- checkpoints
- multi-step reasoning

It should not become the knowledge layer or skill registry.

**22\. MCP's role**

MCP should eventually provide a standardized boundary between the agent and external capabilities.

Conceptually:

CV Agent

│

├── Knowledge tools

├── Research tools

├── GitHub

├── filesystem

├── NVIDIA tools

├── training infrastructure

├── profiling

└── deployment infrastructure

The agent should reason about **what needs to be done**, while tools provide the ability to do it.

**23\. Skill architecture**

A critical concept:

**Capability**

What the agent can accomplish.

Example:

model.optimize.quantization

**Skill**

Specialized knowledge/instructions for accomplishing something.

Example:

NVIDIA Model Optimizer PTQ skill

**Tool**

An executable interface.

Example:

TensorRT profiling command

**Agent**

An autonomous reasoning/execution worker.

Example:

CUDA optimization agent

These are not interchangeable.

The agent should eventually resolve:

User task

↓

required capability

↓

appropriate skill

↓

required tools

↓

execution agent

**24\. Autonomous training**

Eventually the agent should be capable of doing something like:

User:

Train a detector for these images.

Agent:

I need approval to start training because this will consume

approximately X GPU-hours.

\[Approval\]

Agent:

Training experiment A started.

...

Agent:

Experiment A completed.

mAP: ...

Recall: ...

Latency: ...

Failure analysis indicates...

I recommend experiment B.

The agent should not silently consume hundreds of GPU-hours.

Likewise:

- NAS
- massive hyperparameter sweeps
- cloud GPU usage
- production deployment
- destructive dataset operations

should have appropriate approval gates.

**25\. Experiment-driven development**

The agent should maintain experiment history.

Every experiment should have reproducible metadata:

Experiment ID

Model

Dataset version

Input resolution

Batch size

Optimizer

Learning rate

Scheduler

Augmentations

Epochs

Hardware

Precision

Parameters

FLOPs

Training time

GPU hours

Validation metrics

Test metrics

Latency

Memory

Power

Notes

This allows the agent to answer:

Why did we choose this model?

rather than relying on conversational memory.

**26\. Dataset/version control**

The agent must treat data as an engineering artifact.

It should eventually support:

- dataset manifests
- dataset versions
- annotation versions
- reproducibility
- data lineage
- dataset cards
- train/validation/test provenance
- DVC/Git LFS where appropriate
- experiment-to-dataset linkage

**27\. Failure analysis**

This should become one of the agent's strongest capabilities.

After evaluation, it should not simply report:

mAP = 72%

It should investigate:

Why are 28% failing?

Potential failure categories:

- small objects
- occlusion
- blur
- low illumination
- camera angle
- compression
- class confusion
- localization error
- false positives
- domain shift
- temporal instability
- tracking failures
- annotation errors

Then:

failure pattern

↓

root cause hypothesis

↓

experiment

↓

measurement

↓

decision

**28\. Production monitoring**

The eventual system should continue after deployment.

Monitor:

**Model**

- confidence distribution
- class distribution
- detection rate
- false positives
- false negatives
- drift

**System**

- FPS
- latency
- GPU
- CPU
- memory
- power
- thermal conditions
- dropped frames

**Data**

- resolution
- lighting
- camera health
- stream quality
- scene changes

The agent should detect when production behavior deviates from the validated baseline.

**29\. The project's philosophy**

Several principles are non-negotiable.

**1\. Problem first**

Never start with:

"Which model should we use?"

Start with:

"What exactly are we trying to detect/predict/understand?"

**2\. Baseline first**

Never optimize before measuring.

**3\. Evidence over hype**

A new model is not automatically better because it is newer.

**4\. Hardware-aware**

Accuracy without deployability is incomplete engineering.

**5\. Reproducibility**

Every important result must be reproducible.

**6\. Modular architecture**

Capabilities, skills, tools, knowledge, models, and agents remain separable.

**7\. Current knowledge**

The agent must continuously update its understanding of the ecosystem.

**8\. Human approval**

High-cost/high-impact actions require authorization.

**9\. Don't reinvent existing expertise**

Use NVIDIA skills, CUDA Agent, existing tools, models, and frameworks where appropriate.

**10\. Measure everything important**

No optimization without quantitative evidence.

**30\. What the final product should feel like**

Eventually you should be able to open the agent and say:

**"I have a prison surveillance project."**

The agent should respond something like:

"Before selecting a model, I need to characterize the operational problem."

It asks targeted questions.

You answer.

Then it produces:

PROJECT UNDERSTANDING

↓

CV TASK DECOMPOSITION

↓

SYSTEM ARCHITECTURE

↓

DATA REQUIREMENTS

↓

RESEARCH FINDINGS

↓

MODEL OPTIONS

↓

EXPERIMENT PLAN

↓

TRAINING PLAN

↓

EVALUATION PLAN

↓

DEPLOYMENT PLAN

Then, with approval, it actually executes.

You should eventually be able to say:

"Train option B."

and the agent can:

prepare dataset

↓

validate dataset

↓

configure training

↓

request approval

↓

train

↓

evaluate

↓

failure analysis

↓

benchmark

↓

compare with baseline

↓

recommend next experiment

Then:

"Optimize it for Jetson."

and it can:

ONNX

↓

TensorRT

↓

FP16

↓

INT8 if justified

↓

profiling

↓

CUDA/kernel investigation if necessary

↓

DeepStream integration

↓

end-to-end benchmark

That is the product we are actually building.

**31\. What the project is NOT**

We should explicitly remember what we are **not** building.

**Not a generic chatbot**

The system must perform engineering workflows.

**Not a YOLO wrapper**

YOLO is one possible component, not the architecture.

**Not an NVIDIA-only agent**

NVIDIA is strategically important, but architecture selection remains vendor/model agnostic.

**Not an autonomous system with unlimited authority**

Humans retain control over consequential actions.

**Not a giant RAG dump**

Retrieval quality, provenance, freshness, and relevance matter more than document quantity.

**Not a fixed list of CV techniques**

The system must remain extensible as CV evolves.

**Not an LLM with hundreds of hardcoded prompts**

The architecture should use structured capabilities, skills, tools, knowledge and state.

**32\. Current implementation status**

We should treat the current repository as **very early foundation**, not as the finished agent.

Current verified foundation:

Python package

↓

configuration

↓

LLM abstraction

↓

mock provider

↓

LangGraph runtime

↓

agent state

↓

capability registry

↓

CLI

↓

tests

The current baseline has been repaired for:

- type-safe registry identities
- package-safe resource loading
- explicit dependencies
- CLI argument handling
- regression testing

But the major intelligence layers are still ahead.

**33\. Major future subsystems**

The eventual architecture will likely contain:

CV ENGINEERING AGENT

│

┌────────────────────┼────────────────────┐

│ │ │

Reasoning Knowledge Execution

│ │ │

LLM Gateway RAG / Memory MCP / Tools

│ │ │

Claude/OpenAI/etc. Research/Web/etc. Skills

│ │

│ NVIDIA Skills

│ CUDA Agent

│ Training

│ Profiling

│ Deployment

│

Project Memory

│

Experiment History

│

Dataset Knowledge

with LangGraph coordinating the workflows.

**34\. The most important architectural rule**

The system should **not become a pile of features**.

Every new subsystem must answer:

**What responsibility does this own, and why does that responsibility not belong somewhere else?**

For example:

LLM

\= reasoning

LangGraph

\= orchestration

RAG

\= knowledge retrieval

Web research

\= current information acquisition

Capability registry

\= what the system can do

Skill system

\= specialized procedural knowledge

MCP/tools

\= execution interfaces

Training subsystem

\= experiment execution

Evaluation subsystem

\= measurement

Project memory

\= persistent project state

That separation will determine whether this becomes a maintainable engineering platform or another fragile AI-agent codebase.

**35\. The ultimate goal**

The ultimate goal is **not merely to make an AI that knows computer vision**.

The goal is to make an AI system that can **perform computer-vision engineering**.

The distinction is fundamental.

CV knowledge

≠

CV engineering capability

We are building the latter.

The ideal final interaction is therefore:

**You provide a real-world CV problem.**

The agent:

**understands → researches → designs → plans → asks for approval → executes → measures → diagnoses → optimizes → benchmarks → deploys → monitors → learns from the project.**

That is the mission.

And **this document should become the canonical project context**, from which we derive the operational AGENTS.md, CLAUDE.md, architecture, decisions, roadmap, and rolling-state files.

The next step should be to turn this into those **actual repository MD files**, without losing or contradicting any of the above.