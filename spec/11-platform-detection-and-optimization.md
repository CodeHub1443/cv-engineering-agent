# CV Engineering Agent — Platform Detection and Hardware Optimization

**Version:** V1.0  
**Status:** Foundational specification

## Purpose

Detect the execution environment before platform-dependent installation, training, inference, profiling, or deployment and select a compatible software and optimization strategy.

## Supported Platform Classes

```text
macOS
Linux
Windows
NVIDIA Jetson
```

Jetson is treated as a distinct profile even though it uses Linux because its JetPack/Jetson Linux, ARM64, CUDA, TensorRT, DeepStream, power, and thermal characteristics affect execution.

## Platform Profile

The detector should return structured data covering, where available:

```text
OS and version
distribution / release
kernel
CPU architecture
CPU model
RAM
GPU / accelerator
GPU vendor
GPU architecture / compute capability
driver version
CUDA/runtime version
framework backend availability
Python/runtime versions
container runtime
power / thermal information
Jetson model and JetPack/L4T information
```

It must distinguish hardware presence, hardware accessibility, driver availability, runtime availability, toolkit installation, and framework backend support.

## Detection Flow

```text
OS
 ↓
Architecture
 ↓
Hardware
 ↓
Accelerator
 ↓
Driver / Runtime
 ↓
Framework Compatibility
 ↓
Platform Optimization Profile
```

## Platform Rules

### macOS

Detect Intel vs Apple Silicon.

For Apple Silicon, use the supported PyTorch MPS backend when available; do not describe MPS as CUDA. See the PyTorch MPS documentation. 

Do not assume NVIDIA CUDA, TensorRT, or DeepStream is available on macOS.

### Linux

Detect distribution, release, kernel, architecture, compiler/toolchain where relevant, NVIDIA GPU and driver state.

For CUDA installation, select a toolkit compatible with the detected OS, compiler and GPU rather than installing an arbitrary version. NVIDIA's Linux guide requires a supported Linux distribution, CUDA-capable GPU and compatible host toolchain.

Prefer the platform's supported package/repository installation method and avoid mixing incompatible installation mechanisms.

### Windows

Detect Windows version, architecture, GPU/driver state, Python/runtime environment, and WSL2 availability.

The planner must distinguish native Windows, WSL2, container/VM, and remote Linux execution and choose the strategy compatible with the required CV/NVIDIA stack.

### NVIDIA Jetson

Detect at minimum:

```text
Jetson model/family
ARM64 architecture
Jetson Linux / L4T
JetPack
CUDA
TensorRT
DeepStream
memory
power / thermal state where available
```

Jetson uses a device-specific NVIDIA software stack and constraints; use the matching JetPack/Jetson Linux documentation rather than generic desktop/server instructions.

## Installation Planner

The agent must not begin installation from a generic script.

It must first produce:

```text
Platform Profile
 ↓
Required Components
 ↓
Compatibility Check
 ↓
Install / Upgrade Plan
 ↓
Post-Install Verification
 ↓
Optimization Plan
```

Each dependency should be classified as:

```text
installed + compatible
installed + outdated
missing
incompatible
unknown
```

System-level changes require the applicable approval policy.

## GPU Optimization

The objective is maximum useful end-to-end performance within accuracy, latency, throughput, memory, power, thermal, and reliability constraints. Maximum reported GPU utilization is not itself a success criterion.

Before optimization, identify whether the bottleneck is:

```text
CPU
GPU
memory
I/O
PCIe / interconnect
data loading
video decode
preprocess
kernel launch
inference
postprocess
tracking / event logic
thermal throttling
power limits
```

## GPU Validation

Before reporting GPU acceleration as working, verify:

```text
GPU detected
driver operational
runtime operational
framework sees accelerator
model placed on accelerator
accelerator kernels execute
expected performance observed
```

A framework-reported GPU device is not sufficient evidence of end-to-end acceleration.

## Optimization Profile

The platform layer should produce:

```text
recommended backend
recommended precision
recommended batch/concurrency
recommended data pipeline
recommended memory strategy
recommended profiling tools
recommended deployment runtime
known incompatibilities
power/thermal constraints
```

Examples:

```text
NVIDIA Linux GPU
→ CUDA / TensorRT / Nsight as applicable

Jetson
→ JetPack-compatible CUDA / TensorRT / DeepStream as applicable

Apple Silicon
→ MPS / Metal-aware PyTorch workflow where supported

Windows
→ native Windows or WSL2/remote Linux based on compatibility
```

## Optimization Loop

```text
Detect
 ↓
Verify
 ↓
Baseline
 ↓
Profile
 ↓
Find Bottleneck
 ↓
Apply Platform-Specific Optimization
 ↓
Benchmark
 ↓
Compare
 ↓
Accept / Reject
```

The agent must never claim full GPU utilization, a speedup, or improved efficiency without measurement.

## Safety

Installing or upgrading drivers/toolkits, changing system packages, changing power/performance modes, modifying kernel/runtime configuration, or altering production infrastructure may require elevated privileges and explicit human approval.

The agent should show the intended system changes before executing materially consequential system modifications.
