# ADR-0008: Requirements understanding + CV task decomposition foundation

- **Status:** Accepted (retroactive — same allowance ADR-0001 and ADR-0007 used; no
  live GitHub issue tracker wired up yet)
- **Date:** 2026-09-15
- **Layer:** reasoning
- **Canon:** `[P§5]`, `[P§6]`, `[P§23]`, `[P§34]`
- **Supersedes / Superseded by:** —
- **Issue:** #TBD

## 1. Context

`docs/roadmap/ROADMAP.md` Phase 4 names this deliverable: "ADR-0008 reasoning
nodes... the elicitation workflow." `docs/PROJECT.md` §5 is explicit that the agent
must characterize the operational problem — asking targeted questions — before
naming a model, and §30 describes the product feel as PROJECT UNDERSTANDING → CV TASK
DECOMPOSITION. Until this ADR, nothing in the repo turned a natural-language request
into that structure; `cv_agent.skills.resolver.TaskResolver` (ADR-0007) matches a task
string to capabilities/skills but does not ask *what the task actually is* first.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** turning a natural-language CV request into known/unknown/assumed
  requirement fields, candidate CV task-component hypotheses with stated rationale,
  links into the existing capability registry, and targeted clarification questions
  (`cv_agent.requirements`).
- **This does NOT own:**
  - deciding which capability/skill to actually use → `TaskResolver` (ADR-0007),
    called by this module, not reimplemented;
  - asking the human the clarification questions and waiting for an answer → a future
    LangGraph interrupt node (`[P§21]`, not built);
  - executing anything → no execution boundary exists yet (`docs/state/STATUS.md`);
  - real LLM reasoning about ambiguous requests → the core extraction stays
    deterministic/rule-based; an LLM is wired in for an optional prose summary only,
    never as the source of a structured fact.
- **Why this responsibility does not belong to an existing component:** `TaskResolver`
  already has one job — matching a task string to capabilities/skills — and doing that
  well requires the string to already express what's needed. Folding "figure out what
  the user actually means" into the resolver would blur task-matching with
  problem-understanding, which are different questions at different points in
  `docs/PROJECT.md` §6's lifecycle (DISCOVER/DEFINE vs. later stages).

## 3. Decision

`cv_agent/requirements/`: a `RequirementsAnalysis` dataclass (known/unknown/assumed
`RequirementField`s, `TaskHypothesis`, `CapabilityLink`, `ClarificationQuestion`);
`rules.py` holding two flat, appendable lists (`FIELD_DETECTORS`,
`TASK_HYPOTHESIS_RULES`) instead of a decision tree in code — the same
data-over-control-flow pattern ADR-0007's resolver already established;
`RequirementsAnalyzer.analyze()`, deterministic keyword-driven extraction that calls
the existing `TaskResolver` for capability links (never bypasses it) and takes an
optional `LLMProvider` used only to generate `narrative_summary` prose. A field can
become `"assumed"` only via an explicit `assumptions` argument the *caller* supplies
— the analyzer never self-promotes an unknown field.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| LLM-only extraction (send the request to an LLM, parse structured JSON back) | Would handle phrasing this repo's keyword rules miss | No real provider is wired to anything but the mock (`cv_agent/llm/mock.py`), making this untestable/unauditable without network access; risks the LLM inventing a value for a genuinely unknown field, which is the exact failure mode `[P§35]` (silent invention) forbids | Rejected for this step; `RequirementsAnalyzer`'s constructor already accepts an `LLMProvider`, so a semantic extraction layer can be added later behind the same interface without a rewrite |
| One fixed if/elif decision tree keyed on problem type ("prison" -> ..., "factory" -> ...) | Simple to write for the two example problems in `docs/PROJECT.md` §5 | Explicitly forbidden by the task spec and by `[P§34]`; does not extend to a new CV domain without editing the analyzer's control flow | Rejected; used flat rule lists instead |
| Fold `RequirementField`/`TaskHypothesis` into `AgentState` (`cv_agent/graph/state.py`) directly | One less type layer | Couples a reasoning-layer concept to the orchestration state shape before any node actually consumes it; premature per `[P§21]`'s reasoning/orchestration separation | Rejected; `RequirementsAnalysis` stays a plain return value from `CVAgent.analyze_requirements()` until a LangGraph node needs to carry it in state |

## 5. Interface

```python
# module: cv_agent.requirements.models
InfoStatus = Literal["known", "unknown", "assumed"]

@dataclass(frozen=True)
class RequirementField:
    name: str
    status: InfoStatus
    value: str | None
    why_it_matters: str
    source: str = "user_request"

@dataclass(frozen=True)
class TaskHypothesis:
    task_component: str
    rationale: str
    trigger_terms: tuple[str, ...]
    confidence: float

@dataclass(frozen=True)
class CapabilityLink:
    task_component: str
    capability_id: str
    status: str
    matched_terms: tuple[str, ...]

@dataclass(frozen=True)
class ClarificationQuestion:
    question: str
    relates_to_field: str
    why_it_matters: str

@dataclass(frozen=True)
class RequirementsAnalysis:
    original_request: str
    problem_statement: str
    fields: tuple[RequirementField, ...]
    candidate_tasks: tuple[TaskHypothesis, ...]
    capability_links: tuple[CapabilityLink, ...]
    clarification_questions: tuple[ClarificationQuestion, ...]
    assumptions: tuple[str, ...]
    constraints: tuple[str, ...]
    risks: tuple[str, ...]
    narrative_summary: str | None = None
    llm_provider: str | None = None

# module: cv_agent.requirements.analyzer
class RequirementsAnalyzer:
    def __init__(self, task_resolver: TaskResolver, llm: LLMProvider | None = None) -> None: ...
    def analyze(self, request: str, *, assumptions: dict[str, str] | None = None) -> RequirementsAnalysis: ...
```

## 6. Consequences

- **Enables:** `python -m cv_agent analyze "<request>"` and `CVAgent.analyze_requirements()`
  producing a structured, evidence-tied requirements picture with clarification
  questions instead of a free-text guess; a concrete input type
  (`RequirementsAnalysis`) that a future DISCOVER/DEFINE LangGraph node can consume.
- **Makes harder:** nothing removed; purely additive.
- **Costs:** one new package (`cv_agent/requirements/`), ~450 lines, no new
  dependency, one `TaskResolver` dependency (already present).
- **Migration / blast radius if reversed:** contained — `CVAgent.analyze_requirements()`
  and the `analyze` CLI command are the only consumers; removing the package does not
  touch `TaskResolver`, `CapabilityRegistry`, or the LLM gateway.

## 7. Acceptance test

`tests/test_requirements.py` (field detection incl. known/unknown/assumed exclusivity
and no-fabrication guarantees, task-hypothesis generation with rationale, capability
integration that never claims `status == "available"`, clarification-question
coverage, determinism, LLM narrative isolation from fact fields) and
`tests/test_cli.py`'s `analyze` command tests (structured output, verbatim request
echo, and an explicit check that the skill fixture root is untouched by `analyze` —
i.e. no execution).

## 8. Revisit trigger

When a LangGraph DISCOVER/DEFINE node is built and needs `RequirementsAnalysis` (or
parts of it) folded into `AgentState`; when a real LLM provider is wired in and a
semantic (not just keyword) extraction path is wanted; or when a second CV domain
(e.g. audio, LiDAR) reveals that `FIELD_DETECTORS`/`TASK_HYPOTHESIS_RULES` need a
richer trigger mechanism than substring matching.
