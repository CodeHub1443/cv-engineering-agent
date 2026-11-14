# ADR-0020: LLM gateway v2 — task routing, daily budget, length cap, privacy, call log

- **Status:** Accepted, accepted by owner (2026-11-12)
- **Amended by:** ADR-0023 (2026-11-12)
- **Date:** 2026-11-12
- **Layer:** reasoning (LLM Gateway)
- **Canon:** `[P§19]`, `[P§20]`, `[P§24]`, `[P§25]`, `[P§29.8]`, `[P§34]`
- **Supersedes / Superseded by:** amends [ADR-0002](ADR-0002-llm-gateway.md) (§3 "single configured model"; §5 "`LLMRequest`/`LLMResponse` unchanged"; §6 "no call/iteration budget"). On acceptance it supersedes D-033(2)'s "unchanged interfaces" clause. The model choice (D-033(3), D-034) is superseded by owner decision D-089, not by this ADR. The credential source (D-033(5)) is superseded by [ADR-0021](ADR-0021-llm-credential-source.md). D-033(4) (no automatic fallback) and D-033(6) (mock default) are **kept**.
- **Issue:** #83
- **Acceptance (2026-11-12, owner; issue #89):** accepted with the safe defaults of the previously open questions: Q34 `LLMRequest.temperature` is removed; Q35 a `max_tokens` stop raises `LLMTruncatedError` even when some text exists; Q36 the adapter uses `max_retries=0`; Q42 the call-log store is created only by an explicit `cv-agent llm-log init` and a missing store fails closed (implemented in G2); Q43 the call log is kept, append-only, with no pruning; Q44 the project `.env` is looked up at the main checkout root (already implemented in C2). Recorded as D-092.

## 1. Context

- The Anthropic adapter fails on `claude-opus-5-5`: it always sends `temperature` (`cv_agent/llm/anthropic_provider.py:103`) and the API answers 400 "`temperature` is deprecated for this model" (live check L-1, 2026-11-12).
- It ignores `stop_reason` (`:151`) and drops non-text blocks (`:131-133`). Live check L-3 showed `max_tokens=64` on Opus returns a `thinking`-only block with no text and 64 billed output tokens, which the adapter would hand back as an empty answer.
- There is no spend control (ADR-0002 §6), no call log, and no privacy check. The only call site reachable in production, the analyzer narrative, sends the raw user request (`cv_agent/requirements/analyzer.py:292`).
- `docs/architecture/OVERVIEW.md` already assigns "model selection by task class & cost, retries/limits, token accounting" to the gateway, and `[P§20]` asks for cheap and strong routing.
- Owner decisions of 2026-11-12 fix the shape: two tiers by task class, a $5 per day ceiling for the whole agent, a 4000-token cap including thinking, call logging, default-deny privacy, fail closed.

**Live-check facts (owner-run 2026-11-12, about $0.0016):**

| # | Fact |
|---|---|
| L-1 | Existing adapter, `claude-opus-5-5`, temperature 0.0: BadRequestError 400 "`temperature` is deprecated for this model." |
| L-2 | `claude-opus-5-5`, no temperature, `max_tokens=300`: OK, `end_turn`, blocks [text], 18 in / 4 out. |
| L-3 | `claude-opus-5-5`, `max_tokens=64`, long-answer prompt: `stop_reason=max_tokens`, blocks [thinking] only, 64 output tokens billed. |
| L-4 | `claude-haiku-5-5`, no temperature, `max_tokens=300`: OK, `end_turn`, [text], 18 in / 4 out. |

Untested: whether Haiku 5.5 rejects temperature (moot: the design never sends it).

**Documentation facts (Anthropic platform docs, retrieved 2026-11-12):** both models use adaptive thinking by default with default effort medium (low, medium, high, xhigh, max); the docs say to omit `temperature`, `top_p`, `top_k`; thinking tokens count against `max_tokens`. Opus 5.5: thinking cannot be disabled, enabled-with-budget, `between_tools` and forced `tool_choice` all return 400; price $4 / $20 per million input / output tokens. Haiku 5.5: thinking disabled accepted at effort high or below and 400 at xhigh or max; enabled-with-budget and `between_tools` return 400; price $0.10 / $0.50 up to 100K input tokens and $0.50 / $2.50 above (all input tokens count, cache included). Defaults for temperature, `top_p`, `top_k` and `max_tokens` are not stated in the docs.

## 2. Responsibility `[P§34]`

- **This owns:** selecting a provider and model per task class and, for every non-mock call: the privacy check, input and length limits, the daily spend and call budget, the stop-reason policy, and the call log.
- **This does NOT own:**
  - prompt content, nor deciding *whether* to call — reasoning nodes `[P§19]`;
  - orchestration and retries across graph steps — LangGraph `[P§21]`;
  - experiment records — `cv_agent/experiments` ([ADR-0011](ADR-0011-experiment-ledger.md));
  - credentials — [ADR-0021](ADR-0021-llm-credential-source.md);
  - GPU or process control — nothing owns it; the gateway never starts, stops or unloads a process (D1), and measured-run GPU provenance stays in [ADR-0018](ADR-0018-fp32-precision-control.md) §6;
  - approval interrupts — [ADR-0003](ADR-0003-orchestration-state-and-human-approval-interrupts.md).
- **Why this does not belong to an existing component:** these rules must apply to every call whatever the caller, so putting them in call sites would copy them three times. Adapters must stay thin and provider-specific. Orchestration never sees individual LLM calls. `OVERVIEW.md` names the gateway as the owner. No new layer is created.

## 3. Decision

1. **Typed enums** `TaskClass {EXTRACTION, SELECTION, NARRATIVE}` and `DataClass {PUBLIC_WEB, PROJECT_METADATA, PROJECT_DATA}` (`[P§32]`).
2. **Tiers and model facts** (capabilities, prices with `as_of` and source URL) live in the gateway-owned `cv_agent/llm/catalog.toml` (owner answer Q-H), so no provider or model string appears outside the gateway (`CLAUDE.md` §3.8). Changing a model is a PR to that file.
   - `offline` = mock;
   - `fast` = `claude-haiku-5-5`, thinking `disabled`, `max_tokens` 1024;
   - `strong` = `claude-opus-5-5`, thinking omitted (adaptive, its only accepted mode), `max_tokens` 4000.
   - Effort is omitted (provider default, medium) on both.
   - Project config holds only routing, budget, privacy and log settings. **Every task class routes to `offline` by default.** The model choice itself is owner decision D-089.
3. **Routing:** `EXTRACTION → fast`, `SELECTION → strong`, `NARRATIVE → fast` (recommended: it is short prose over already-computed fields and never a source of fact, D-011). In the shipped config all three stay `offline`. There is no fallback: a route resolves or raises.
4. `LLMRouter.for_task(tc)` returns a `GovernedProvider(LLMProvider)` bound to a task class, a tier and an adapter. Call sites keep receiving an `LLMProvider`.
5. **`GovernedProvider.complete()`** runs, in order:
   1. privacy: an empty `data_classes` counts as `{PROJECT_DATA}`; any class outside the allowed set for a hosted tier raises, before the budget and before any network I/O;
   2. input `len(system)+len(prompt) ≤ max_input_chars` (24,000) and `max_tokens` ≤ tier ≤ 4000 (thinking included);
   3. budget reserve (§3.6);
   4. the adapter call;
   5. stop-reason policy: only `end_turn` or `stop_sequence` with non-empty text is a normal answer; `max_tokens` (thinking-only or with text), `model_context_window_exceeded`, `refusal`, empty text, `tool_use`, `pause_turn` and unknown values raise a typed error carrying call ID, tier, model, stop reason and usage;
   6. a call-log row with the D4 fields plus `request_id` (owner answer Q-L), written with the budget settle.
   - A missing, corrupt or busy store fails closed. The mock tier is ungoverned (no store, no log), so tests and CI need no disk or credentials. Every non-mock tier is governed.
6. **Daily budget** (owner answers Q-A..Q-G):
   - ceiling **$5.00 per day**, at most **100 calls per day**, for the whole agent, across processes, in one SQLite file `<main checkout>/.cv_agent/llm_calls.sqlite` (git-ignored; `llm_calls` and `llm_budget` tables; `BEGIN IMMEDIATE`);
   - day = calendar day at a fixed offset **UTC+06:00** (resets at 18:00 UTC), no tz database;
   - pre-call worst case = `(UTF-8 bytes of system+prompt + 512 framing reserve) × input rate + effective max_tokens × output rate`, so thinking is covered; settled after the call from actual usage (cache tokens counted as input; thinking is inside `output_tokens`);
   - an error after sending leaves the reservation counted;
   - a clock moved back more than 300 s behind the last recorded call raises `LLMClockSkewError`;
   - a missing file refuses with an explicit init hint (`cv-agent llm-log init`); a corrupt or busy store raises `LLMStoreError`;
   - `LLMBudgetExceededError` and `LLMCallLimitError` are raised before any network I/O; **no silent downgrade** to another tier, model or provider;
   - Haiku price step at 100K input tokens: `max_input_chars × 4 + 512` must stay below the first step, checked at config load, and the rate is chosen from actual usage at settle;
   - **budget scope: one machine.** Hosted tiers are used from the owner's Windows PC only (owner answer Q-G, 2026-11-12). Only that machine holds the project `.env` key ([ADR-0021](ADR-0021-llm-credential-source.md) §3 item 12); on any other machine a hosted call fails closed with `LLMCredentialError`. The store is per checkout, so with one hosting machine the $5 per day ceiling is the true whole-agent ceiling.
7. **Privacy:** default-deny (D10). The allowed set for hosted tiers is `[llm.privacy] hosted_allowed_data_classes`, default `PUBLIC_WEB` and `PROJECT_METADATA`; `PROJECT_DATA` is blocked. The owner allows a class only by a PR editing that value with a D-entry; there is no env-var or CLI override. Non-hosted tiers allow every class.
8. **Adapter v2:** never sends `temperature`, `top_p`, `top_k`, `tools`, `tool_choice` or `budget_tokens`; sends `thinking` and `output_config.effort` only when the tier sets them; returns text blocks only (thinking never returned, logged or stored); keeps the request ID; reports usage with cache and thinking tokens; `max_retries=0` so one `complete()` is one HTTP attempt; SDK pin `anthropic>=0.125,<1`.
9. **Types:** `LLMRequest` drops `temperature`, makes `max_tokens` optional (`None` = tier value; an explicit value above the tier raises, no silent clamp) and gains `data_classes`. `LLMResponse` gains `stop_reason`, `request_id`, `call_id`. `LLMProvider` gains optional `adapter_version`, `sdk_version` and local digest/quantization properties defaulting to `None`. Nothing else changes (D8: no tool calls, streaming or multi-turn).
10. **Config validation at load** (`LLMConfigError`): unknown keys rejected anywhere under `[llm]` and in tiers (so `temperature`, `top_p`, `top_k`, `budget_tokens`, `tool_choice`, `between_tools` and the legacy `provider`/`model`/`overrides` all fail); `thinking = "enabled"` is not a legal value; `thinking = "disabled"` rejected for `claude-opus-5-5`; `disabled` with effort `xhigh` or `max` rejected for `claude-haiku-5-5`; tier `max_tokens` above 4000 or the model maximum rejected; every task class must route to a defined tier; a hosted model needs catalog prices with `as_of` and source; the Haiku price-step guard.
11. **Legacy removal:** `LLMConfig.provider`, `model`, `overrides` and `LLMOverride` are deleted (owner answer Q-D), with the commented examples in both `default.toml` files.
12. **LLM API spend** within the daily ceiling needs no per-call approval; spend above it is refused, not escalated (owner answer Q-S). This sets the `docs/APPROVALS.md` threshold for LLM calls only; Q6 and Q19 stay open for everything else.
13. **Ledger link:** no `[P§25]` schema change. When an LLM output shaped an experiment decision, the experiment record's `notes` carries `llm_call_ids=<id>[,<id>]` and `decision` states the decision. Experiments never import `cv_agent.llm`.
14. **Local tier (D1, D12): none now.** Both of the owner's PCs, the Windows RTX 3050 and the Linux RTX 3060, are measured CV hosts (owner answer Q-V, 2026-11-12, D-091), and no LLM runs locally on either. The local tier and the second adapter for OpenAI-compatible endpoints stay plan-only: nothing is built or enabled, and a second adapter needs its own ADR (ADR-0022, httpx recommended) before slice A1. If a local tier is ever enabled it must not use either GPU (D1, D-074, [ADR-0018](ADR-0018-fp32-precision-control.md) §6). The gateway never starts, stops, unloads, installs or pulls a process; `keep_alive` may only be a request parameter.

### 3.1 What default-deny means in production today (stated plainly)

- The analyzer narrative (`NARRATIVE`) sends the raw user request, and `select_candidate` (`SELECTION`) sends a free-text `task_description`. Both are `PROJECT_DATA`.
- **Under default-deny, the strong tier and the NARRATIVE route therefore have no permitted production use** until either the owner allows `PROJECT_DATA` for hosted tiers or open question Q-O is resolved (restructure the selector prompt to fields only). Until then both routes stay `offline`.
- **Research extraction** (`graph/research.py`, `EXTRACTION → fast`) is the only call site that can qualify for the hosted tier (`PUBLIC_WEB` plus a topic-only `claim_query`). It has **no production caller** today (`perform_research` is used only by tests); a user-facing entry point is open question Q-P. D9 (switching extraction to the fast tier behind config) is therefore proven at config and test level only until Q-P is done.
- Until slice G5 lands, the legacy single-provider path is ungoverned. Do not set `[llm] provider` to a real provider before G5 (STATUS "Do not start yet").

### 3.2 Merge permission (D11) timing

The owner's D11 permission for Claude Code to open and merge the LLM-layer PRs with merge commits (recorded as D-090) **starts only after the owner has merged the D0 pull request** (the PR that carries this ADR). This D0 PR is merged by the owner. D11 keeps the D-085 conditions: merge commit only, CI green, no squash, rebase, force-push, branch deletion or direct commit to `main`.

## 4. Alternatives considered

| Alternative | For | Against | Verdict |
|---|---|---|---|
| JSONL call log plus counter file | Human-readable | No portable cross-process lock in the stdlib; read-sum-append races across two processes | Rejected; SQLite `BEGIN IMMEDIATE` (pattern already used by ADR-0004, ADR-0011) |
| Per-process budget | Trivial | Owner asked for per day for the whole agent (D3) | Rejected |
| Rolling 24 h window | No boundary burst | Harder to explain and query | Rejected; fixed-offset day |
| Tiers in `config/default.toml` | One config place | Puts provider and model strings outside the gateway (§3.8) | Rejected (Q-H) |
| `messages.count_tokens` before each call | Exact input count | Extra network call, latency and failure mode | Not now; bytes upper bound |
| Automatic downgrade to fast when budget is low | Keeps working | Silent behaviour change; forbidden by D3 and D-033(4) | Rejected |
| Return truncated text with a flag | Salvages output | Call sites parse JSON; partial output is a silent defect | Rejected (Q-J default) |
| openai SDK for the second adapter | Typed client | Cannot reach Ollama native `keep_alive`; a second vendor SDK | Deferred to ADR-0022; httpx recommended |

## 5. Interface

All stubs are **PROPOSED**: types and signatures only, no bodies. They are implemented in slices G1–G7.

```python
# PROPOSED — cv_agent/llm/policy.py
class TaskClass(str, Enum):
    EXTRACTION = "extraction"
    SELECTION = "selection"
    NARRATIVE = "narrative"
class DataClass(str, Enum):
    PUBLIC_WEB = "public_web"
    PROJECT_METADATA = "project_metadata"
    PROJECT_DATA = "project_data"
```

```python
# PROPOSED — cv_agent/llm/base.py (amended)
@dataclass(frozen=True)
class LLMRequest:
    prompt: str
    system: str | None = None
    max_tokens: int | None = None                       # None -> tier default; must be <= tier max
    data_classes: frozenset[DataClass] = frozenset()    # empty -> treated as {PROJECT_DATA}
    metadata: dict[str, Any] = field(default_factory=dict)
    # temperature: removed

@dataclass(frozen=True)
class LLMResponse:
    content: str                      # text blocks only; never thinking
    model: str
    provider: str
    usage: dict[str, int]             # prompt_tokens, completion_tokens, thinking_tokens, total_tokens
    stop_reason: str | None = None
    request_id: str | None = None
    call_id: str | None = None        # set by GovernedProvider
    metadata: dict[str, Any] = field(default_factory=dict)

class LLMProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...
    @property
    @abstractmethod
    def model_name(self) -> str: ...
    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse: ...
    @property
    def adapter_version(self) -> str | None: ...        # default None
    @property
    def sdk_version(self) -> str | None: ...            # default None
    @property
    def local_model_digest(self) -> str | None: ...     # default None
    @property
    def local_quantization(self) -> str | None: ...     # default None
```

```python
# PROPOSED — cv_agent/llm/errors.py
class LLMError(RuntimeError): ...
class LLMConfigError(LLMError): ...
class LLMCredentialError(LLMError): ...
class LLMStoreError(LLMError): ...
class LLMClockSkewError(LLMError): ...
class LLMDataClassNotAllowedError(LLMError):
    def __init__(self, task_class: TaskClass, tier: str, blocked: frozenset[DataClass]) -> None: ...
class LLMInputTooLargeError(LLMError): ...
class LLMBudgetExceededError(LLMError):
    def __init__(self, *, day_key: str, ceiling_usd: float, spent_usd: float,
                 call_worst_usd: float, resets_at_utc: str) -> None: ...
class LLMCallLimitError(LLMError): ...
class LLMCallError(LLMError):                     # base for errors after a call was sent
    call_id: str; tier: str; model: str; stop_reason: str | None
class LLMRequestError(LLMCallError): ...          # transport / HTTP status
class LLMTruncatedError(LLMCallError):
    thinking_only: bool; reason: Literal["max_tokens", "context_window"]
class LLMRefusalError(LLMCallError): ...
class LLMEmptyResponseError(LLMCallError): ...
class LLMUnexpectedStopError(LLMCallError): ...
```

```python
# PROPOSED — cv_agent/llm/catalog.py
ThinkingMode = Literal["adaptive", "disabled"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
@dataclass(frozen=True)
class PriceStep:
    up_to_input_tokens: int
    input_usd_per_mtok: float
    output_usd_per_mtok: float
@dataclass(frozen=True)
class ModelFacts:
    model: str; provider: str
    thinking_can_disable: bool
    thinking_disable_max_effort: Effort | None
    max_output_tokens: int
    price_steps: tuple[PriceStep, ...]
    prices_as_of: str; prices_source: str
@dataclass(frozen=True)
class TierSpec:
    name: str; provider: str; model: str; hosted: bool; max_tokens: int
    thinking: ThinkingMode | None = None
    effort: Effort | None = None
@dataclass(frozen=True)
class Catalog:
    tiers: Mapping[str, TierSpec]
    models: Mapping[str, ModelFacts]
def load_catalog() -> Catalog: ...                       # importlib.resources, validates shape
def price_for(facts: ModelFacts, input_tokens: int) -> PriceStep: ...
```

```python
# PROPOSED — cv_agent/config/settings.py (amended; no provider or model strings)
@dataclass(frozen=True)
class LLMBudgetConfig:
    daily_usd_ceiling: float = 5.0
    daily_call_limit: int = 100
    max_input_chars: int = 24_000
    max_output_tokens: int = 4_000
    day_boundary_utc_offset: str = "+06:00"
@dataclass(frozen=True)
class LLMPrivacyConfig:
    hosted_allowed_data_classes: tuple[str, ...] = ("PUBLIC_WEB", "PROJECT_METADATA")
@dataclass(frozen=True)
class LLMLogConfig:
    store_text: bool = False
@dataclass
class LLMConfig:
    routing: dict[str, str] = field(default_factory=lambda: {
        "extraction": "offline", "selection": "offline", "narrative": "offline"})
    budget: LLMBudgetConfig = field(default_factory=LLMBudgetConfig)
    privacy: LLMPrivacyConfig = field(default_factory=LLMPrivacyConfig)
    log: LLMLogConfig = field(default_factory=LLMLogConfig)
# LLMOverride, LLMConfig.provider/model/overrides: removed.
```

```python
# PROPOSED — cv_agent/llm/clock.py
class Clock(Protocol):
    def now_utc(self) -> datetime: ...
    def monotonic(self) -> float: ...
class SystemClock:
    def now_utc(self) -> datetime: ...
    def monotonic(self) -> float: ...
```

```python
# PROPOSED — cv_agent/llm/sqlite_store.py   (the only LLM module importing sqlite3)
@dataclass(frozen=True)
class CallRecord:                       # the D4 fields plus request_id (Q-L)
    call_id: str; request_id: str | None; ts_utc: str; task_class: str; tier: str; provider: str; model: str
    adapter_version: str | None; sdk_version: str | None
    local_model_digest: str | None; local_quantization: str | None
    max_tokens: int; thinking: str | None; effort: str | None
    prompt_sha256: str; response_sha256: str | None
    input_tokens: int; cache_creation_input_tokens: int; cache_read_input_tokens: int
    output_tokens: int; thinking_tokens: int
    stop_reason: str; latency_ms: int
    prompt_text: str | None = None; response_text: str | None = None   # opt-in only
@dataclass(frozen=True)
class Reservation:
    call_id: str; day_key: str; reserved_usd: float
class LLMCallStore:
    def __init__(self, path: Path, *, busy_timeout_s: float = 5.0) -> None: ...  # LLMStoreError if missing/corrupt
    @staticmethod
    def initialise(path: Path) -> None: ...                                      # refuses if file exists
    def reserve(self, *, call_id: str, now_utc: datetime, day_key: str, worst_usd: float,
                ceiling_usd: float, call_limit: int, skew_tolerance_s: float,
                prices_as_of: str) -> Reservation: ...
    def settle(self, reservation: Reservation, record: CallRecord, actual_usd: float | None) -> None: ...
    def spent_today(self, day_key: str) -> tuple[float, int]: ...
```

```python
# PROPOSED — cv_agent/llm/governed.py
class GovernedProvider(LLMProvider):
    def __init__(self, *, task_class: TaskClass, tier: TierSpec, facts: ModelFacts | None,
                 adapter: LLMProvider, store: LLMCallStore | None, budget: LLMBudgetConfig,
                 allowed_hosted: frozenset[DataClass], log: LLMLogConfig, clock: Clock) -> None: ...
    @property
    def provider_name(self) -> str: ...
    @property
    def model_name(self) -> str: ...
    @property
    def task_class(self) -> TaskClass: ...
    @property
    def tier_name(self) -> str: ...
    def complete(self, request: LLMRequest) -> LLMResponse: ...
def worst_case_usd(facts: ModelFacts, *, system: str | None, prompt: str, max_tokens: int,
                   framing_reserve_tokens: int = 512) -> float: ...
def day_key_for(ts_utc: datetime, utc_offset: str) -> str: ...
```

```python
# PROPOSED — cv_agent/llm/router.py
@dataclass(frozen=True)
class RouteInfo:
    task_class: TaskClass; tier: str; provider: str; model: str; hosted: bool
class LLMRouter:
    def for_task(self, task_class: TaskClass) -> LLMProvider: ...
    def routes(self) -> tuple[RouteInfo, ...]: ...
def build_router(config: LLMConfig, *, state_dir: Path | None, clock: Clock | None = None,
                 catalog: Catalog | None = None) -> LLMRouter: ...   # LLMConfigError on any invalid setting
```

```python
# PROPOSED — cv_agent/llm/anthropic_provider.py (amended)
ADAPTER_VERSION: str = "anthropic/2"
class AnthropicConfigError(LLMConfigError): ...
class AnthropicRequestError(LLMRequestError): ...
class AnthropicProvider(LLMProvider):
    PROVIDER_NAME: str = "anthropic"
    def __init__(self, model: str, *, thinking: ThinkingMode | None = None, effort: Effort | None = None,
                 api_key: str | None = None, client: Any | None = None,
                 max_retries: int = 0, timeout: float = 60.0) -> None: ...
    def complete(self, request: LLMRequest) -> LLMResponse: ...   # request.max_tokens must be int here
```

```python
# PROPOSED — cv_agent/graph/research.py (slice G7; reasoning layer)
def claim_query_from(topic_tags: tuple[str, ...], model_names: tuple[str, ...], metric: str) -> str: ...
```

```python
# PROPOSED — cv_agent/llm/registry.py
def get_provider(name: str, model: str, **adapter_options: Any) -> LLMProvider: ...
```

Credential stubs (`credentials.py`) are in [ADR-0021](ADR-0021-llm-credential-source.md) §5.

### 5.1 Call-log columns (D4 plus `request_id`)

`call_id`, `request_id` (the provider's request ID, owner answer Q-L; NULL when no response arrived), `ts_utc`, `task_class`, `tier`, `provider`, `model`, `adapter_version`, `sdk_version`, `local_model_digest`, `local_quantization`, `max_tokens`, `thinking`, `effort`, `prompt_sha256` (sha256 of canonical JSON `{"system","prompt"}`), `response_sha256`, `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`, `thinking_tokens`, `stop_reason`, `latency_ms`, and the opt-in `prompt_text`, `response_text` (NULL unless `[llm.log] store_text = true`). No key, no thinking text. Refusals by the privacy, input or budget checks happen before any send and are not call rows. The request ID is also kept in `LLMResponse`.

## 6. Consequences

- **Enables:** real calls on current models; bounded daily spend; an audit trail with hashes for `[P§25]`; privacy by default; task routing per `[P§20]`.
- **Makes harder:** every hosted call needs an initialised store inside a git checkout; changing a model is a PR to `catalog.toml`; outputs are not regenerable (no temperature), so reproducibility is by record (hashes), not regeneration; the strong tier and NARRATIVE route have no permitted production use yet (§3.1).
- **Costs (build, runtime, GPU, $):** about 1,500 lines over seven slices; no new runtime dependency; a few ms of SQLite work per call; no GPU; at most $5 per day. Worked worst cases at the 24,000-character cap: fast about $0.003 per call, strong about $0.18 per call (about 28 calls per day before the ceiling).
- **Migration / blast radius if reversed:** gateway-internal. Call sites keep `LLMProvider`; routing every class to `offline` restores today's behaviour.

## 7. Acceptance test

Per slice (each needs its own issue):

- G1: the adapter never sends `temperature`, `top_p`, `top_k`, `tools`, `tool_choice` or `budget_tokens`; a thinking-only `max_tokens` response raises `LLMTruncatedError(thinking_only=True)` and is never returned.
- G2: log rows have exactly the D4 columns plus `request_id`; no prompt text, no key bytes in the database.
- G3: the 101st call and an over-$5 call are refused with no adapter call; day rollover at 18:00 UTC; two processes never exceed the ceiling; Haiku step guard.
- G4: empty `data_classes` on a hosted tier raises before the budget; input over 24,000 characters raises.
- G5: Opus with thinking disabled and Haiku disabled with xhigh/max are rejected at load; no catalog strings outside `cv_agent/llm/`.
- G6: marker `live_llm` registered; live tests run only with that marker **and** `CV_AGENT_LIVE_LLM=1` (and never when `CI` is set); contract suite over the mock and the Anthropic adapter with a fake client; CI cannot reach a paid API.
- G7: research extraction goes through the fast tier behind config; the default config stays mock; `claim_query_from` rejects free text.
- Structural: the SDK import only in the adapter; no `os.environ` write in `cv_agent/llm/`; `sqlite3` only in `sqlite_store.py` files.

## 8. Revisit trigger

- The Anthropic SDK moves to 2.x.
- Prices change (the catalog `as_of` is older than 90 days, or a pricing announcement).
- The owner allows `PROJECT_DATA` for hosted tiers, or Q-O/Q-P are resolved.
- A local tier is proposed (ADR-0022); it must not use either measured GPU (Q-V).
- Hosted tiers are needed on a second machine (the budget store is per checkout, Q-G).
- Bangladesh adopts daylight saving time.
- A ledger record needs a typed LLM link.
- Any logged call's actual input exceeds the bytes-based estimate.

## 9. Not verified at drafting time

Whether Claude's tokenizer never yields more tokens than UTF-8 bytes; the real size of message framing (512 is a reserve); whether failed or timed-out requests are billed (counted conservatively); cache price multipliers (never sent, so an anomaly is settled at the larger of actual and reserved); the request-ID attribute on SDK error objects in 0.125; whether Haiku 5.5 rejects `temperature` (never sent).

## Amendment (2026-11-13): per-invocation CLI route override (D-102, issue #137)

Q58 is resolved with option (b). This amends §3 items 3-4 (task class to tier routing) and the §5 router interface by one caller-facing rule; nothing above is edited.

- `cv-agent research --live` (default off) resolves the EXTRACTION route to the `fast` tier for that one invocation. The CLI does this by passing the router a copy of the loaded `[llm]` config whose `routing["extraction"]` is the tier name `fast`. It is config data: the CLI names no provider, SDK or model string, and `build_router` validates it against the catalog like any other routing.
- Scope: the `research` command and the EXTRACTION task class only. No other command, task class or config file is affected. The packaged and project `default.toml` files stay all-`offline`, and without `--live` behaviour is unchanged (the offline default of this ADR stands).
- Budget, privacy, payload checks, credential lookup and the call log stay inside `GovernedProvider` and the router, unchanged. `[llm.privacy]` is unchanged; `PROJECT_DATA` stays blocked (D-094).
- With `--live` the CLI calls `router.for_task(TaskClass.EXTRACTION)` before the fetch, so a missing key (`LLMCredentialError`) or call log (`LLMStoreError`) refuses before any HTTP GET (Q57 for the live path). The router caches the built provider, so the later call reuses it.

Canon: `[P§20]`, `[P§24]`, `[P§34]`.
