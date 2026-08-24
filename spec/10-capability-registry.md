# Capability Registry

## Purpose

The CV Engineering Agent must discover and use specialized engineering capabilities when they materially improve a task. Capabilities may be provided by local agent skills, external coding agents, MCP tools, command-line tools, SDKs, or internal implementations.

## Core Principle

Capabilities are registered and selected by applicability. The agent must not assume that a named skill or tool is appropriate merely because it exists.

For each capability, the registry should track:

- capability identifier
- provider/project
- category
- supported tasks
- invocation method
- required runtime/environment
- supported hardware/software versions when relevant
- trust/provenance
- installation status
- availability status
- constraints
- approval level
- last verified timestamp

## NVIDIA Capability Families

The first-class NVIDIA capability family includes:

### Base NVIDIA / CV infrastructure

- DALI dynamic mode
- DeepStream development
- DeepStream pipeline generation
- DeepStream vision-model import
- DeepStream pipeline profiling
- TAO fine-tuning Hugging Face models
- TAO workflow launch
- TAO Hugging Face model porting
- TAO AutoML
- TAO single-step training

### CV architecture / training

- action recognition
- CenterPose
- Deformable DETR
- Depth Anything V2
- DINO
- Grounding DINO
- image classification
- Mask2Former
- metric-learning recognition
- NV-DINOv2
- OCDNet
- OCRNet
- ReID
- RT-DETR
- SegFormer

### GPU kernel optimization

- CUTILE kernel creation
- CUTILE to Triton conversion
- CUTILE autotuning
- CUTILE Python integration
- CUTILE kernel performance improvement

### CLIP

- CLIP fine-tuning

### Advanced CV / industrial

- optical inspection
- Visual ChangeNet
- OneFormer
- Mask Auto Encoder
- Mask Auto Label
- Mask Grounding DINO
- pose classification

### TensorRT

- C++ runtime quickstart
- ONNX quickstart
- performance analysis
- strong typing migration
- Torch quickstart

### NVIDIA Model Optimizer

- PTQ
- quantization recipe search
- result comparison
- Day-0 release
- monitoring
- debugging
- evaluation
- MLflow access
- evaluation launching

## CUDA Agent

The project should recognize CUDA-Agent (`BytedTsinghua-SIA/CUDA-Agent`) as a specialized GPU/CUDA engineering capability for CUDA kernel development, analysis, optimization and related engineering workflows.

CUDA-Agent is complementary to the NVIDIA skill collection. The agent should select between them based on task requirements rather than treating them as interchangeable.

## Skill Selection Policy

The agent should prefer a specialized capability when:

1. the task falls directly within its documented scope;
2. the capability is available in the current environment;
3. its version/runtime constraints are satisfied;
4. using it reduces engineering effort or increases reliability;
5. the capability is appropriate for the target hardware and deployment constraints.

The agent should record which capability it used and why when producing an engineering artifact or experiment record.

## Installation

The NVIDIA skills and CUDA-Agent tooling are installed globally in the user's development environment. The repository should contain the registry and configuration necessary for the CV Engineering Agent to discover and reason about those capabilities, but it must not copy the installed skill implementations into this repository.

## Separation of Concerns

- Skills provide specialized procedures/knowledge.
- Coding agents such as Codex CLI and Claude Code provide implementation workers.
- MCP tools provide structured execution interfaces.
- LLM providers provide reasoning models.
- The CV Engineering Agent decides which capability is appropriate and orchestrates the workflow.

## Future Integration

The runtime should expose capability discovery to agents through a structured interface, for example:

- `capability.list`
- `capability.describe`
- `capability.check`
- `capability.select`
- `capability.invoke`

The initial implementation should remain lightweight and should not require a separate orchestration framework beyond the project's chosen agent runtime.
