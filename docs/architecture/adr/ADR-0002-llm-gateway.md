# ADR-0002: LLM Gateway and Provider Abstraction

- **Status:** Draft / Awaiting approval
- **Date:** 2026-08-31
- **Layer:** cross-cutting
- **Canon:** `[P§20]`, `[P§29.3]`, `[P§29.5]`, `[P§34]`
- **Supersedes / Superseded by:** —
- **Issue:** —

## 1. Context

The CV Engineering Agent requires language-model capabilities while remaining
independent of any specific LLM provider.

`[P§20]` requires provider abstraction so that provider-specific SDKs, authentication,
execution semantics, and model behavior do not leak into orchestration or reasoning
layers.

The existing repository contains a skeletal LLM boundary under `cv_agent/llm/`
(`complete()` method). Phase 1 formalizes that boundary before additional reasoning and
orchestration implementation proceeds. During Phase 2/3, the existing implementation
will be audited and refactored to conform strictly to this specification.

The gateway architecture defines support for three initial provider classes:

- Anthropic
- OpenAI
- Local/Ollama

Specific credentials, API keys, endpoints, and runtime availability remain deployment
configuration concerns rather than architectural mandates. Concrete model identifiers
are selected through configuration and are intentionally not hard-coded in this ADR.

The gateway must also preserve operational metadata needed for reproducibility and
quantitative comparison `[P§29.3]`, `[P§29.5]`.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** provider abstraction, provider lifecycle, request translation,
  configuration-driven provider/model selection, structured response extraction,
  token/cost accounting, latency measurement, rate-limit handling, transient failure
  fallback, and normalized error creation.

- **This does NOT own:**
  - business prompts or CV reasoning logic → reasoning layer;
  - workflow sequencing, checkpoints, or approval state → orchestration layer;
  - capability resolution → capability registry;
  - tool execution → tools / MCP layer;
  - project memory or experiment persistence → memory layer.

- **Why this responsibility does not belong to an existing component:**

  Provider SDKs and provider-specific execution semantics must be isolated behind a
  single boundary. Placing them in reasoning or orchestration would couple those
  layers to external vendors and violate the provider boundary required by `[P§20]`.

## 3. Decision

Use a single typed LLM Gateway interface with configuration-driven provider selection.

The initial gateway defines adapters for three provider classes: Anthropic, OpenAI,
and Local/Ollama. Concrete provider selection and fallback sequencing are governed
by configuration.

Routing is policy-driven by configuration. The gateway, rather than the caller,
determines the configured provider/model sequence for a request.

Transient provider failures trigger sequential fallback to the next configured
provider. Fallback applies to:

- rate limiting / HTTP 429 (`rate_limited`);
- transient HTTP 5xx failures (`transient_server`);
- request timeouts (`timeout`).

The gateway fails fast (no fallback) for non-transient, request-specific, or
configuration failures:

- authentication/credential errors (`authentication`);
- malformed request / schema errors (`invalid_request`);
- prompt exceeding model context window (`context_length_exceeded`);
- unsupported model/provider configuration (`unsupported_model`).

Failed provider attempts raise or return a normalized `LLMError`. Successful attempts
return an `LLMResponse`. Failed attempts do not produce successful `LLMResponse` objects.

Every successful provider attempt produces structured response metadata sufficient to
compare provider behavior and preserve reproducibility:

- provider identifier;
- model identifier;
- request/attempt identifier;
- attempt number;
- latency in milliseconds;
- token usage (input/output) where available;
- estimated cost where calculable;
- whether fallback was used.

Provider-specific SDK imports and semantics remain strictly inside `cv_agent/llm/`.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Provider-specific calls from reasoning/orchestration | Minimal initial implementation | Couples higher layers to provider SDKs and semantics; violates `[P§20]` | Rejected |
| Single hard-coded provider | Simplest configuration and implementation | Creates provider lock-in and prevents configuration-only provider substitution | Rejected |
| Gateway with configuration-driven provider adapters | Preserves provider boundary and allows provider substitution without higher-layer changes | Requires explicit adapter and error-taxonomy contracts | **Accepted** |

## 5. Interface

Data contracts use dataclasses; behavioral interfaces use Protocols; message items use TypedDict.

```python
# module: cv_agent.llm.base

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypedDict


FailureCategory = Literal[
    "rate_limited",
    "transient_server",
    "timeout",
    "authentication",
    "invalid_request",
    "context_length_exceeded",
    "unsupported_model",
    "unknown",
]

MessageRole = Literal[
    "system",
    "user",
    "assistant",
    "tool",
]


class Message(TypedDict):
    role: MessageRole
    content: str  # Multimodal message blocks are deferred to a future interface revision.


@dataclass(frozen=True)
class LLMRequest:
    messages: tuple[Message, ...]
    response_schema: object | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    attempt: int = 1
    fallback_used: bool = False


@dataclass(frozen=True)
class LLMStreamChunk:
    delta: str
    provider: str
    model: str
    is_done: bool = False


@dataclass(frozen=True)
class LLMError(Exception):
    category: FailureCategory
    provider: str
    retryable: bool
    message: str
    details: dict[str, str] = field(default_factory=dict)


class LLMProvider(Protocol):
    provider_id: str
    model: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...


class LLMGateway(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...

    def stream(
        self,
        request: LLMRequest,
    ) -> Iterator[LLMStreamChunk]:
        """Architectural extension point only. Implementation is not required for Phase 1."""
        ...
```

The interface does not authorize provider SDK usage outside `cv_agent/llm/`.
Multimodal message blocks required for CV frame/image inputs are reserved for a future
ADR revision or interface extension; ADR-0002 does not prescribe their transport
representation.

## 6. Consequences

* **Enables:**
  * provider substitution through configuration;
  * future addition of providers without changing reasoning/orchestration;
  * structured latency/token/cost measurements;
  * explicit transient-failure fallback with fast-fail protection for auth/context length;
  * consistent, normalized provider-independent errors.

* **Makes harder:**
  * direct provider-specific features from higher layers;
  * provider-specific shortcuts outside the gateway.

  This restriction is intentional `[P§20]`, `[P§34]`.

* **Costs (build, runtime, GPU, $):**
  * additional adapter and normalization code;
  * provider configuration maintenance;
  * fallback requests may increase latency and cost;
  * local/Ollama deployments transfer operational responsibility to the local environment.

* **Migration / blast radius if reversed:**
  Replacing the gateway would affect reasoning/orchestration callers and provider
  configuration. Provider adapters remain isolated so replacing an individual provider
  does not require changes outside `cv_agent/llm/`.

## 7. Acceptance test

The implementation must provide a runnable acceptance suite demonstrating:

1. Two distinct configured providers can satisfy the same gateway request without
   changing reasoning/orchestration code.
2. Provider SDK imports occur only under `cv_agent/llm/`.
3. A transient 429, timeout, or 5xx failure on the configured primary provider
   sequentially attempts the configured fallback provider.
4. Authentication, invalid-request, and context-length-exceeded failures do not trigger
   fallback (raise normalized `LLMError` immediately).
5. Every successful response exposes provider, model, latency, token metadata where
   available, attempt number, and fallback state.
6. A provider can be replaced by configuration without modifying orchestration code.

Named implementation test location: `tests/test_llm_gateway.py`

*Note: Streaming is an interface extension point only and is not an acceptance criterion for Phase 1.*

## 8. Revisit trigger

Reconsider this ADR if:
* the configured routing model cannot express required task policies;
* provider-specific semantics leak into higher layers;
* measured fallback behavior creates unacceptable latency or cost;
* provider APIs require an abstraction that cannot be represented cleanly by the
  current interface;
* a new provider class requires fundamentally different lifecycle semantics;
* structured output, streaming, or multimodal requirements invalidate the current
  interface contract.
