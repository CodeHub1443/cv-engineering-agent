# ADR-0002: LLM Gateway — provider abstraction and the first real adapter (Anthropic)

- **Status:** Accepted
- **Date:** 2026-09-23
- **Layer:** reasoning (LLM Gateway)
- **Canon:** `[P§19]`, `[P§20]`, `[P§21]`, `[P§24]`, `[P§29.8]`, `[P§34]`
- **Supersedes / Superseded by:** —
- **Issue:** #TBD

## 1. Context

This is the reserved ADR slot named by `docs/architecture/OVERVIEW.md`'s responsibility
table (`LLM Gateway → ADR-0002 (not yet written)`) and by `docs/roadmap/ROADMAP.md`
Phase 1's own stated exit test: *"Two different LLM providers are swappable by
configuration alone; `grep` finds no provider name outside the gateway."* `D-004`
fixed the design order as *registry → gateway → orchestration state → memory → ...* —
in practice orchestration (ADR-0003), memory (ADR-0004) and execution (ADR-0009/0010)
were all built first while the gateway stayed mock-only, an acknowledged sequencing
gap (`ROADMAP.md`, `STATUS.md`).

`cv_agent/llm/` already exists: `base.py` (`LLMProvider` ABC, `LLMRequest`,
`LLMResponse`), `mock.py` (`FakeLLMProvider`), `registry.py` (`register_provider()`,
`get_provider()`, `list_providers()`, pre-registering only `"mock"`). The **only**
existing call site is `cv_agent/requirements/analyzer.py`'s optional, mock-only
`narrative_summary` hook (ADR-0008, D-011) — deliberately never a source of fact.
Nothing in `cv_agent/graph/`, `cv_agent/execution/`, or `cv_agent/skills/` imports
`cv_agent.llm` at all. The approval/execution-integrity chain (ADR-0003 §10, ADR-0009
§14, issue #43/D-032) was inspected directly and has **zero** relationship to the LLM
layer — it gates `Skill → ExecutionBinding → ExecutionRuntime` invocations only,
never an `LLMProvider.complete()` call, and this ADR does not touch it.

`docs/state/STATUS.md` (dated 2026-09-22) listed "real LLM providers" under "Do not
start yet," and `docs/state/OPEN_QUESTIONS.md` Q7 ("Which LLM providers are actually
available with keys, and what is the routing policy per task class?") was open and
blocking. **Both are resolved by explicit owner decision (Tanvir, 2026-09-23,
recorded as D-033):** Anthropic is the first real provider, credentials are
available, routing is a single configured model with no automatic fallback. This ADR
implements exactly that scope — not a general multi-provider router, not RAG, not
autonomous training, none of which this decision touches.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** provider abstraction (the `LLMProvider` interface, unchanged),
  registration/selection of concrete adapters by name+model, the one real adapter
  (`AnthropicProvider`), and the credential/error-handling contract for that adapter.
- **This does NOT own:**
  - *what prompt is sent or why* — that is the calling reasoning node's job
    (`[P§20]`: "Prompts as business logic" is explicitly forbidden inside the
    gateway, per `OVERVIEW.md`'s responsibility table);
  - *orchestration* (retries across graph steps, workflow branching) — LangGraph
    (`[P§21]`), unchanged;
  - *knowledge/retrieval* (RAG, provenance of retrieved facts) — `[P§19]`, not
    started, unaffected by this ADR;
  - *approval or execution* — `cv_agent/execution/*`, ADR-0003 §10/ADR-0009 §14,
    completely untouched by this change; an `LLMProvider` has no path to invoke a
    skill, register a binding, or authorize anything;
  - *cost estimation or spend enforcement* — `docs/state/OPEN_QUESTIONS.md` Q19,
    still open, not resolved or worked around here (§6).
- **Why this responsibility does not belong to an existing component:** no other
  module can own "which concrete SDK a provider name maps to" without either
  hard-coding a provider name into reasoning/orchestration code (forbidden by
  `[P§20]`) or duplicating adapter logic per call site. The registry that already
  exists is the correct, single place; this ADR gives it its first real adapter
  rather than inventing a second selection mechanism.

## 3. Decision

Add one new adapter module, `cv_agent/llm/anthropic_provider.py`, implementing
`AnthropicProvider(LLMProvider)` against the real `anthropic` Python SDK
(`anthropic>=0.40,<1`, verified against the installed `0.125.0` — `Messages.create()`,
`Message`/`TextBlock`/`Usage` response shapes, and the `APIError` exception hierarchy
were read directly from the installed package, not assumed). The module
self-registers (`register_provider("anthropic", AnthropicProvider)`) at import time,
exactly like the existing `trt_perf_analysis.register()` opt-in pattern for skills —
but the import itself is **lazy**, triggered only from inside `registry.get_provider()`
when `name == "anthropic"` and no adapter is registered yet. This keeps `import
cv_agent.llm` (and every existing test) working with zero new hard dependency, while
making Anthropic auto-discoverable the moment it is actually requested — "clean
provider registration and selection" without a hard import cost for callers who never
ask for it.

`LLMConfig`/`load_config()` (`cv_agent/config/settings.py`) are **unchanged** — a
user selects the provider/model the same way as today, via
`[llm] provider = "anthropic"` / `model = "claude-sonnet-5"` in TOML (or a role
override). The **default stays `provider = "mock"`** — choosing Anthropic is opt-in
configuration, never a new default that would require credentials just to run the
existing test suite or CLI.

**Credentials are never carried by `AgentConfig`/TOML.** `AnthropicProvider` reads
`ANTHROPIC_API_KEY` directly from the process environment at construction time (a
constructor `api_key` keyword exists only for direct, explicit construction/testing —
never sourced from a config file). This is the smallest correct application of
`docs/APPROVALS.md`'s data/privacy rule and `CLAUDE.md`'s "no hard-coded API keys or
secrets": the secret lives in the environment, never in a git-tracked file, and the
existing `settings.py` docstring's "environment variable overrides are intentionally
deferred" gap is **not** touched — that gap is about overriding arbitrary config
*values* generically; the API key was never meant to flow through that path, the same
way the `anthropic` SDK's own client already expects `ANTHROPIC_API_KEY` by
convention.

**No automatic fallback.** `get_provider()` resolves exactly the requested name or
raises `ValueError`; nothing catches a construction or request failure and silently
tries a different provider or model. This is a explicit design constraint, not an
oversight — `docs/PROJECT.md` §20's task-complexity routing idea is real but is
**not** implemented here (single configured model only, per the owner decision); a
future router is out of scope and would be a new decision, not an extension of this
one.

`FakeLLMProvider` is untouched and remains the default — every existing test,
`RequirementsAnalyzer`'s narrative hook, and any caller not explicitly asking for
`"anthropic"` continues to work with zero credentials and zero network access.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Eagerly import `anthropic` at `cv_agent.llm.registry` module load | Simpler, no lazy-import indirection | Makes the SDK a hard dependency of every `import cv_agent.llm`, breaking any environment without it installed, including this repo's own CI if the extra were ever dropped | Rejected; lazy per-name import keeps the gateway's own import graph free of any concrete provider |
| A generic plugin-discovery mechanism (entry points / auto-scanning a directory) | More "extensible" in the abstract | No second provider exists yet to justify it; speculative generality `CLAUDE.md` §3.12 explicitly rejects | Rejected; a small literal name→module map is the smallest mechanism that is still "a clear path for adding additional providers later" |
| Multi-provider router with automatic fallback on failure | Matches `[P§20]`'s long-term vision (routing by task complexity/cost) | Explicitly not authorized by the owner decision this ADR implements ("single configured model; no automatic fallback"); would also need a cost/failure policy this project has no basis for inventing (Q19) | Rejected for this ADR; a future ADR amendment if/when a second provider and a routing policy are both authorized |
| Pass the API key through `AgentConfig`/TOML like `provider`/`model` | Symmetric with existing config fields | Would put a secret in a plain dataclass that `load_config()` reads from a file — directly contradicts `docs/APPROVALS.md` and `CLAUDE.md`'s "no hard-coded secrets," and risks a credential ending up in a committed config file | Rejected; credentials are environment-only, never config-file-sourced |
| Build a typed evidence-provenance wrapper around every `LLMResponse` (retrieved fact / measured result / tool output / inference / recommendation) | Directly matches this task's §E requirement's letter | No second consumer of `LLMResponse` exists yet beyond ADR-0008's narrative hook, which already enforces "prose, never fact" by convention (D-011); building a taxonomy type now, with one call site, is speculative generality ahead of the reasoning-layer work that would actually need it | Deferred — documented as a design rule (§6), not new code, until a second real reasoning node exists to validate the shape against |

## 5. Interface

```python
# module: cv_agent.llm.anthropic_provider  (new)

class AnthropicConfigError(RuntimeError): ...
class AnthropicRequestError(RuntimeError): ...

class AnthropicProvider(LLMProvider):
    PROVIDER_NAME: str = "anthropic"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,   # explicit override; NOT sourced from AgentConfig
        client: Any | None = None,    # test/DI seam; bypasses api_key entirely when given
        max_retries: int = 2,
        timeout: float = 60.0,
    ) -> None: ...

    @property
    def provider_name(self) -> str: ...
    @property
    def model_name(self) -> str: ...
    def complete(self, request: LLMRequest) -> LLMResponse: ...

# module: cv_agent.llm.registry  (amended)
_LAZY_ADAPTERS: dict[str, str]   # provider name -> adapter module to import on demand
def get_provider(name: str, model: str) -> LLMProvider: ...  # now attempts one lazy import
```

`LLMRequest`/`LLMResponse` (`cv_agent/llm/base.py`) are **unchanged** — already
sufficient: `LLMRequest.prompt`/`.system`/`.max_tokens`/`.temperature`/`.metadata` map
directly onto `anthropic.Anthropic().messages.create(...)`'s `messages`/`system`/
`max_tokens`/`temperature`; `LLMResponse.content`/`.model`/`.provider`/`.usage`/
`.metadata` map from the real `Message`/`Usage` response shape (`usage.input_tokens`/
`.output_tokens`; `stop_reason` carried in `.metadata`).

## 6. Consequences

- **Enables:** a real, network-calling LLM completion path exists and is selectable
  by configuration alone (`provider = "anthropic"`), with `FakeLLMProvider` untouched
  as the safe default — `ROADMAP.md` Phase 1's exit test ("two providers swappable by
  config alone") is now demonstrable.
- **Makes harder:** nothing existing — no interface changed, no existing call site
  touched, no existing test's behavior changed.
- **Costs:** one new module (`cv_agent/llm/anthropic_provider.py`), a small addition
  to `registry.py` (the lazy-adapter map), a new dev/optional dependency
  (`anthropic>=0.40,<1`), and a new test file.
- **Design rules established, not enforced by new types (documentation, not code):**
  (a) *Evidence provenance* (§E) — an `LLMResponse` is architecturally
  inference/recommendation-class evidence; no caller may represent it as a retrieved
  fact, measured result, or tool output. ADR-0008/D-011's `narrative_summary` rule is
  the existing concrete instance; any future reasoning node consuming
  `AnthropicProvider` output must follow the same rule. (b) *Deterministic-first
  escalation* (§B) — a reasoning node should call the gateway only when a
  deterministic mechanism (rules, registries, validators, profilers) cannot reliably
  resolve the task; this ADR adds no new call site, so no existing deterministic
  workflow gains an LLM call. (c) *Proposal/control boundary* (§D) — unaffected by
  construction: `LLMProvider` has no reference to `SkillExecutor`,
  `ExecutionBindingRegistry`, or any approval state; there is no code path by which an
  `LLMResponse` can execute or authorize anything.
- **Explicitly NOT built, stated rather than hidden (per this task's own scope
  limits):**
  - **No call/iteration budget or monetary-cost enforcement.** `docs/APPROVALS.md`'s
    "External API spend above threshold" gate has no numeric threshold
    (`OPEN_QUESTIONS.md` Q6, still `TBD`) and no cost-estimation mechanism
    (`OPEN_QUESTIONS.md` Q19, still open) — inventing either here would be exactly
    the silent invention `[P§35]` forbids. `LLMRequest.max_tokens` remains the one
    real, enforced limit (passed straight through to the Anthropic API, which
    enforces it) — there is no monetary budget enforced anywhere, and no code claims
    otherwise.
  - **No multi-provider routing policy.** Q7's "routing policy per task class" half
    is intentionally not answered beyond "one model, no fallback" — a real routing
    policy needs at least a second provider to make a meaningful decision between.
  - **No engineering feedback-loop node** (§G's Plan→Execute→Measure→Validate→
    Reason→Iterate). This ADR ships the gateway only; wiring `AnthropicProvider` into
    a graph node that consumes real execution/validation results is "real workflow
    integration," downstream of this ADR in the project's own stated phase order.
- **Migration / blast radius if reversed:** contained — deleting
  `cv_agent/llm/anthropic_provider.py` and the lazy-adapter-map entry restores the
  exact pre-ADR state; nothing else references the module by name.

## 7. Acceptance test

`tests/test_llm_anthropic.py`:
- `AnthropicProvider` is a subclass of `LLMProvider`; `provider_name`/`model_name`
  report correctly.
- Missing `ANTHROPIC_API_KEY` (env cleared, no `api_key`/`client` override) raises
  `AnthropicConfigError` before any network attempt.
- An injected fake client (`client=...`) lets `complete()` run deterministically, with
  no real network call and no real credentials, returning a correctly-mapped
  `LLMResponse` (content, usage, provider, model).
- Each of `AuthenticationError`, `RateLimitError`, `APIConnectionError`, and a generic
  `APIStatusError`/`APIError` raised by the injected fake client is caught and
  re-raised as `AnthropicRequestError` with an informative, credential-free message.
- `get_provider("anthropic", "claude-sonnet-5")` succeeds once `ANTHROPIC_API_KEY`
  is set (via a fake client monkeypatched onto the lazily-imported module, or a
  cleared-env negative case), and `"mock"` continues to work unmodified.
- Structural test: `anthropic` (the third-party package) is imported by exactly one
  module in `cv_agent` — `cv_agent.llm.anthropic_provider` — mirroring ADR-0004's
  `sqlite3`-confinement test pattern, enforcing "individual skills and workflows must
  not call Anthropic directly."
- No test in the suite requires real network access or a real API key (CI has
  neither); `tests/test_llm_mock.py` and every other existing test remain unmodified
  and passing.

## 8. Revisit trigger

- When a second real provider is authorized — at that point the "no automatic
  fallback" and "single configured model" constraints become live decisions to
  revisit, not defaults to keep.
- When `OPEN_QUESTIONS.md` Q6/Q19 are resolved (approval thresholds, a real
  cost-estimation mechanism) — call/iteration/spend limits become implementable
  without inventing the numbers this ADR deliberately left alone.
- When a reasoning node other than ADR-0008's narrative hook first consumes
  `AnthropicProvider` output for something closer to a real decision — at that point
  the evidence-provenance design rule (§6a) should be reconsidered as an enforced
  type, not just a documented convention.

## 9. Revision — model identifier corrected during PR review (2026-09-24)

The initial implementation (PR #52) configured `claude-sonnet-4-5` — asked and
confirmed explicitly with the owner before implementation, not invented, per §1's
original decision. PR review (Tanvir) flagged this before merge: Anthropic's own
documentation states that for any model **before the 4.6 generation**, the undated
API alias "is a convenience pointer that resolves to the dated ID" — meaning
`claude-sonnet-4-5` was never a pinned identifier, and the actual dated snapshot
behind it is `claude-sonnet-4-5-20250929` (confirmed present in the installed
`anthropic` SDK's own `ModelParam` type literal).

Investigating further (fetched `platform.claude.com/docs/en/models/overview`
directly) surfaced a larger fact the review comment itself hadn't raised: **Claude
Sonnet 4.5 is now a legacy model**, superseded in the current lineup by **Claude
Sonnet 5** (`claude-sonnet-5`). Critically, for models in the 4.6+ generation
(which includes Sonnet 5), Anthropic states *"every Claude model ID is a pinned
snapshot, including the dateless IDs... Dateless IDs are their own pinned snapshot;
the alias row repeats them"* — i.e. `claude-sonnet-5` has no drift problem at all;
it is already a fully pinned identifier by Anthropic's own design, with no dated
suffix to track.

Given a choice between (a) staying on the legacy Sonnet 4.5 family pinned to its
dated snapshot, or (b) moving to the current-generation Sonnet 5 family, which
solves the exact pinning concern more durably and has a longer committed retirement
horizon, the owner chose (b). **Corrected: the configured model is `claude-sonnet-5`**
everywhere this ADR, `cv_agent/llm/anthropic_provider.py`'s docstring,
`config/default.toml`'s example, and `tests/test_llm_anthropic.py` reference one —
this file's body text above reads `claude-sonnet-5` directly rather than carrying a
stale reference forward, since the ADR was still an open, unmerged PR at the time of
correction (§1's original decision text is preserved above for provenance; this
section documents why it changed). No interface, adapter logic, or test *shape*
changed — only the literal model-ID string used throughout. See `docs/state/
DECISIONS.md` D-034 for the recorded correction (D-033 itself is left unedited,
per this project's append-only decision-ledger convention).
