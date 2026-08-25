# CV Engineering Agent

Autonomous Computer Vision engineering assistant built on LangGraph.

## Overview

`cv-agent` is a structured agent runtime for Computer Vision engineering workflows:
model selection, training design, evaluation, benchmarking, deployment optimisation,
and research survey.

## Requirements

- Python 3.10+
- No API keys required to run tests (uses `FakeLLMProvider` by default)

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

```bash
# Health check
python -m cv_agent
# or, after install:
cv-agent
```

## Running Tests

```bash
pytest tests/ -v
```

## Project Structure

```
cv_agent/
├── config/         # Configuration loading (TOML)
├── llm/            # LLM provider abstraction + mock
├── capabilities/   # Capability registry interface
├── graph/          # LangGraph state + graph builder
└── runtime/        # CVAgent orchestrator + CLI

spec/
├── 10-capability-registry.md   # Authoritative capability registry spec
└── capability_registry.json    # Machine-readable registry data

config/
└── default.toml                # Default configuration
```

## Capability Registry

The capability registry (`spec/capability_registry.json`) represents the agent's
CV engineering knowledge structure. It distinguishes:

- **CAPABILITY** — what the agent accomplishes (e.g. `cv.deployment.optimization`)
- **SKILL** — specialised procedural knowledge (e.g. TensorRT, DeepStream)
- **TOOL** — executable interface (e.g. `trtexec`, `tegrastats`)
- **AGENT/RUNTIME** — execution worker (e.g. Claude Code, CUDA Agent)
- **KNOWLEDGE SOURCE** — reference material (e.g. arXiv, NVIDIA docs)

See `spec/10-capability-registry.md` for the full specification.

## Adding a Real LLM Provider

```python
from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.registry import register_provider

class AnthropicProvider(LLMProvider):
    PROVIDER_NAME = "anthropic"
    # ... implement complete()

register_provider("anthropic", AnthropicProvider)
```

Then set in `config/default.toml`:
```toml
[llm]
provider = "anthropic"
model    = "claude-opus-4-5"
```
