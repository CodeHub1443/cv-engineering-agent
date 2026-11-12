# ADR-0023: Structured hosted payloads for SELECTION and NARRATIVE

- **Status:** Accepted (2026-11-12, owner; D-095)
- **Date:** 2026-11-12
- **Layer:** reasoning (LLM gateway mechanism + reasoning call sites); one knowledge-layer field (§3.4)
- **Canon:** `[P§19]`, `[P§20]`, `[P§24]`, `[P§29.3]`, `[P§32]`, `[P§34]`
- **Supersedes / Superseded by:** — . On acceptance this ADR amends [ADR-0020](ADR-0020-llm-gateway-v2.md) §3.1 and §5 (`LLMRequest`, `GovernedProvider`, call-log columns), [ADR-0014](ADR-0014-model-selection.md) §5 (selector input), [ADR-0008](ADR-0008-requirements-analysis.md) §3 (narrative source) and [ADR-0006](ADR-0006-knowledge-context-boundary.md) (`KnowledgeItem` gains `ingest`, §3.4). Those files are **not** edited by this PR (§6).
- **Issue:** #103
- **Decision record:** D-094 (owner answer to Q40, 2026-11-12)

## 1. Context

- ADR-0020 (Accepted, D-092) §3 item 7: privacy is default-deny. Hosted tiers accept `PUBLIC_WEB` and `PROJECT_METADATA` only. An empty `data_classes` counts as `PROJECT_DATA`. The check runs in `GovernedProvider._check_privacy` (`cv_agent/llm/governed.py:272-277`) and trusts the class the call site declares.
- Both SELECTION and NARRATIVE send user free text and declare `PROJECT_DATA` (§1.1), so the strong tier and the NARRATIVE route have no permitted hosted use (ADR-0020 §3.1).
- **Owner decision, 2026-11-12 (Q40, D-094):** keep `PROJECT_DATA` blocked for hosted tiers. Restructure the SELECTION and NARRATIVE prompts so that only structured fields are sent. The SELECTION payload may also carry public-web evidence claims, under the eligibility rule in §2.3. Track order after this: Q41 (research entry point), then the Phase 6 experiment loop.
- **Goal:** *no user-originated free text can reach a hosted tier* must hold **by construction** for SELECTION and NARRATIVE. The payload type decides the data class, not a label written by the caller.
- **Production reachability (verified 2026-11-12, origin/main `866ba72`):**
  - NARRATIVE is reachable. `CVAgent` wires `router.lazy_for_task(TaskClass.NARRATIVE)` into `RequirementsAnalyzer` (`cv_agent/runtime/agent.py:89`, `:114`), and the CLI prints the narrative (`cv_agent/__main__.py:208-211`).
  - SELECTION has **no production caller**. `select_candidate` is called only from `run_reference_selection` (`cv_agent/model_selection/reference_task_research.py:623`), which only tests use.

### 1.1 Inventory: what is sent today

Value classes: **CV** = closed vocabulary defined in code, **N** = numeric, **B** = boolean, **ID** = identifier, **FT** = free text. "User" means the string can originate from the user or caller.

**SELECTION** (`cv_agent/model_selection/selector.py`; template `:53-83`, formatting `:255-280`, request `:282-288`):

| Value in prompt | Source | Class |
|---|---|---|
| `Task: {task_description}` (`:274-275`) | `CandidateComparison.task_description`; caller-supplied (`reference_task_research.py` `TASK_DESCRIPTION`) | **FT, user** |
| `=== {candidate_id} (family: {model_family}) ===` (`:106`) | `ModelCandidate` | FT strings (caller-chosen IDs and names) |
| `Task support:` (`:107`) | `ModelCandidate.task_support` | FT tuple (e.g. `tao_fine_tuning`, not a vocabulary) |
| Strengths, limitations, compatibility constraints (`:109-117`) | `ModelCandidate` | FT, agent- or researcher-authored, **no provenance** |
| `[{source_class} / {evidence_weight}]` (`:97`) | `EvidenceReference` | CV (`SourceClass`, `EvidenceWeight`, `cv_agent/knowledge/models.py:14-25`) |
| Claim (truncated to 300 chars) (`:97`), `conditions` (`:99`) | `KnowledgeItem.claim` / `.conditions` via `EvidenceReference.from_knowledge_item` (`model_selection/models.py:57-70`) | FT, public web *by provenance only* |
| `source: {url}` (`:100`) | `Provenance.url` | FT |
| Research gaps (`:260-264`) | Code-generated (`selector.py:206-217`), embedding `candidate_id` and `model_family` | FT (embeds the FT above) |
| Conflicts (`:265-272`) | `ConflictNote.dimension`, `.note`, item IDs | FT |
| `candidate_id_list` (`:279`) | `candidate_id`s | FT |
| `data_classes` (`:287`) | Declared `{PROJECT_DATA}`; `max_tokens=1024` | — |

**NARRATIVE** (`cv_agent/requirements/analyzer.py:280-300`):

| Value in prompt | Source | Class |
|---|---|---|
| `Request: {request}` (`:293`) | The raw user request | **FT, user** |
| `Known fields`, `Unknown fields` (`:288-289`) | `RequirementField.name` | CV (`FIELD_DETECTORS`, `cv_agent/requirements/rules.py:36-94`, 7 names) |
| `Candidate task components` (`:290`) | `TaskHypothesis.task_component` | CV (`TASK_HYPOTHESIS_RULES`, `rules.py:107-173`, 8 names) |
| `Open questions: {n}` (`:297`) | `len(clarifications)` | N |
| `data_classes` (`:299`) | Declared `{PROJECT_DATA}`; `max_tokens=1024` | — |

### 1.2 Inventory: structured outputs already available upstream

| Output | Location | Class | Admissible in a hosted payload? |
|---|---|---|---|
| `RequirementField.name` | `requirements/models.py:27-40` | CV | Yes |
| `RequirementField.status` | `InfoStatus`, `models.py:23` | CV (`known`/`unknown`/`assumed`) | Yes |
| `RequirementField.value` | `_extract_sentence` (`analyzer.py:48-54`) or caller assumption (`:144-153`) | **FT, user** | **No** |
| Matched trigger term for a known field | `_find_matches` (`analyzer.py:44-45`, used at `:133-141`) | CV (`FieldDetector.trigger_terms`) | Yes, but **not retained today**; only the first match picks the sentence (§7, S3) |
| `RequirementField.why_it_matters` | `rules.py` static text | Code text | Not needed (locally derivable) |
| `RequirementField.source` | `"user_request"`/`"caller_assumption"` | CV in practice (typed as `str`) | Yes, as an enum |
| `TaskHypothesis.task_component`, `.trigger_terms` | `models.py:44-59`, `analyzer.py:168-184` | CV | Yes |
| `TaskHypothesis.confidence` | `analyzer.py:174` | N in [0, 1] | Yes (bounded `RATIO`) |
| `TaskHypothesis.rationale` | Template plus a CV term | Code text | Not needed |
| `CapabilityLink.capability_id` | Registry JSON | ID | Only if the registry is the packaged one. `registry_path` is user-configurable (`cv_agent/config/settings.py:116-162`) |
| `CapabilityLink.status` | `CapabilityStatus`, `capabilities/registry.py:39` | CV | Yes |
| `CapabilityLink.matched_terms`, `SkillLink.matched_terms` | Overlap of tokenized query (which contains the user request, `analyzer.py:198`) with registry or skill tokens (`skills/resolver.py:41`, `:185`, `:215`, `:232`) | Registry/skill tokens | **No in v1** (see §9) |
| `SkillLink.skill_id` | Discovered `SKILL.md` on user-configured roots (`skills/models.py:41`) | ID from the user's filesystem | **No** (counts and booleans only) |
| `SkillLink.declared`, `.executable` | `requirements/models.py:96-110` | B | Yes |
| `ClarificationQuestion` | Template text plus a CV field name | Code text | Count and field names only |
| `clarification_answers` | Become `assumptions` (`graph/workflow.py:163-164`) | **FT, user** | **No** |
| `RequirementsAnalysis.constraints` | `analyzer.py:253-259`, embeds field values | **FT, user** | **No** |
| `RequirementsAnalysis.risks` | `analyzer.py:261-276`, static text keyed by field | Code text | Field names only |
| `RequirementsAnalysis.original_request`, `problem_statement` | `analyzer.py:112-113` | **FT, user** | **No** |
| `SelectionConfidence` | `model_selection/models.py:18-23` | CV | Response side only |
| `SourceClass`, `EvidenceWeight` | `knowledge/models.py:14-25` | CV | Yes |
| `KnowledgeItem.claim`, `.conditions` | `knowledge/models.py:91-98` | FT, public web | Only through `PublicClaim` (§2.3) |
| `HostProfile` (`os`, `gpu_available`, `gpu_vendor`, `driver_version`, `vram_mb`) | `cv_agent/execution/host.py:22-34` | CV-ish, B, N | Not used in v1. It describes the agent's own host, not the deployment target |

**Absent today (verified 2026-11-12):**
- a catalog of CV model families (the only catalog is the LLM `cv_agent/llm/catalog.toml`);
- any numeric extraction of fps, latency, camera count or recall targets from the request;
- a typed deployment-target or hardware field for the *deployment* platform.

## 2. Definitions

### 2.1 PROJECT_METADATA, for payload purposes

A hosted payload is **PROJECT_METADATA** iff every leaf value is one of the following:

1. **An enum member** of a Python `Enum` declared in code.
2. **A `VocabToken`**, a member of a registered `Vocabulary` whose `origin` is `code` (a literal tuple in a `cv_agent` module, e.g. `FIELD_DETECTORS` trigger terms) or `packaged_resource` (loaded through `importlib.resources` from the installed package, with its sha256 recorded).
3. **A bounded number** (`Quantity`): a finite `float` or `int` with a `Unit` enum and the bounds declared on the schema field. NaN, ±inf and out-of-bounds values are rejected.
4. **A bool.**
5. **A bounded count** (`int`, 0 ≤ n ≤ the field's declared maximum).
6. **An opaque ordinal** assigned locally at build time (`C1…Cn` for candidates, `E1…En` for evidence) and mapped back locally after the call.

**Forbidden in a PROJECT_METADATA payload:**
- any `str` leaf that is not a `VocabToken`;
- any string originating from the user or caller, including the raw request, `task_description`, caller assumption values, clarification answers and notes;
- file names and paths;
- URLs;
- client, site or person names;
- free-text notes of any author.

### 2.2 Edge cases

| Case | Rule |
|---|---|
| `other` enum value | Legal as an enum member. It **never** has a companion text field: a schema with no `str` leaves has nowhere to put "other: …". An `OTHER` member means "a value outside the vocabulary was seen"; the value itself stays local. |
| Unit strings | Units are a `Unit` enum fixed on the **schema field** (`ms`, `fps`, `mb`, `w`, `px`, `count`, `ratio`), never parsed from or carried in data. A number arriving with a unit string is converted locally or dropped. |
| IDs that embed user text | Never sent: `candidate_id`, discovered `skill_id`, capability IDs from a non-packaged `registry_path`, experiment IDs, dataset versions, file stems. They are replaced by ordinals (§2.1 item 6) or reduced to counts. A registry ID is admissible only as a `VocabToken` of a `packaged_resource` vocabulary. |
| Site-type trigger terms (`prison`, `warehouse`, `factory`) | Admissible. They are code-defined vocabulary words (`rules.py:47`), not names of a site. |
| Caller assumptions | Status `assumed` is admissible. The value is not. If the value, lower-cased, is itself a member of that field's trigger vocabulary, the token is admissible (§3.5). |
| Model family names | Not sent in v1 (no vocabulary exists). The `PublicClaim` texts name models where the public source does. |
| Vocabulary growth | Adding a term to `FIELD_DETECTORS` or `TASK_HYPOTHESIS_RULES` changes the vocabulary version. The payload header carries every vocabulary version it uses. |

### 2.3 PUBLIC_WEB evidence: `PublicClaim` eligibility (normative)

Public-web text enters a hosted payload **only** as a `PublicClaim`, and **only** `PublicClaim.from_item` creates one. The eligibility checks belong to the builder, not the caller. An ineligible item is **excluded** (dropped and counted in `claims_excluded`), never sent and never escalated to an error the caller could catch and retry with text.

**A `KnowledgeItem` is eligible iff all of the following hold:**

1. **It is a `KnowledgeItem` with a `Provenance` instance.** An object with no provenance, or with a provenance of another type, is excluded.
2. **Its URL is a public web URL.** `Provenance.url` parses as an absolute URL with:
   - scheme `http` or `https`;
   - no userinfo;
   - a host that is a DNS name containing at least one dot;
   - a host that is not an IP literal;
   - a host other than `localhost`;
   - a host that does not end in `.local`, `.localhost`, `.internal`, `.lan`, `.home.arpa`, `.corp` or `.intranet`.

   `file:`, `data:`, relative and schemeless URLs are excluded. (The existing fetcher already accepts only http and https: `cv_agent/tools/web_research.py:130-136`.)
3. **Its `SourceClass` is in `WEB_SOURCE_CLASSES`**, an explicit allowlist (a frozenset in the payload module, not derived from `SourceClass`):
   - `peer_reviewed_research`
   - `official_documentation`
   - `official_repository_or_release_notes`
   - `reputable_benchmark`
   - `engineering_blog`
   - `community_discussion`
   - `model_zoo_or_leaderboard`

   **Excluded:** `professional_post` (weight `signal_not_evidence`, `knowledge/models.py:37`: not evidence for a selection, and the class most likely to carry personal names). **Excluded by default:** any `SourceClass` added later, for example one for user documents, until an ADR amends this list.
4. **Its `ingest` is `WEB_FETCH` or `CURATED_REFERENCE`** (§3.4). `PROJECT_INPUT` and `UNSPECIFIED` (the default) are excluded. So an item created from any project input path is excluded by the builder whatever its URL or source class says.

**Text rule:**
- The claim text is `KnowledgeItem.claim` **verbatim**, truncated to at most **300 characters** (`_MAX_CLAIM_CHARS`, today `selector.py:42`).
- It is never re-composed, re-worded, joined with `conditions`, or concatenated with any other input.
- `conditions` is a separate `PublicClaim` field, also verbatim, truncated to at most **150 characters**.
- `url`, `author_or_org` and the dates are **not** sent; the claim is cited by its ordinal `E<n>`.

**Caps (proposed):**

| Cap | Value | Rationale |
|---|---|---|
| Characters per claim / per `conditions` | 300 / 150 | The claim cap is unchanged from today (`selector.py:42`). The longest reference claim is 220 characters. |
| **N**: claims per candidate | **10** | The reference comparison has 7, 5 and 3 items per candidate (counted 2026-11-12 from `build_reference_comparison()`), so 10 leaves headroom. Today's cap of 20 (`selector.py:41`) does not fit the M budget for more than one candidate. |
| **M**: claims per payload | **30** | Worst case per serialised claim: 300 (claim) + 150 (conditions) + about 100 (keys, ordinal, enums) = about 550 characters. 30 × 550 = 16,500 characters, plus template (≤ 3,000) and structured fields (≤ 2,000), is ≤ 21,500 characters: under the 24,000-character input cap (ADR-0020 §3 item 5) with about 2,500 characters of margin. Typical claims are about 300 to 350 characters, so the usual payload is near 15,000. The strong-tier worst case stays at or below ADR-0020's $0.18 per call. |

**Size guard:** if a rendered payload would still exceed `max_input_chars`, the builder drops claims from the end of the deterministic order below until it fits, and counts them in `claims_omitted`. A payload is never truncated mid-claim, and the gateway's input check (ADR-0020 §3 item 5) still applies.

**Deterministic choice when a cap binds:**
1. benchmark evidence first;
2. then `EvidenceWeight` from high to `low_medium`;
3. then `item_id` in lexical order.

The number of dropped items is sent as `claims_omitted` (per candidate and per payload). Each excluded item is counted in `claims_excluded`, with a closed reason enum: `no_provenance`, `non_public_url`, `source_class_not_allowed`, `ingest_not_allowed`.

**Data class derivation:** a payload with at least one `PublicClaim` carries `{PROJECT_METADATA, PUBLIC_WEB}`; without one it carries `{PROJECT_METADATA}`.

## 3. Decision

Hosted SELECTION and NARRATIVE calls carry a **typed, versioned payload** built only by the gateway's payload builder. The builder accepts only the leaf kinds in §2.1 and the `PublicClaim` kind in §2.3, and rejects every other `str`. `GovernedProvider` derives the data classes from the payload type and **refuses** a hosted SELECTION or NARRATIVE request that has no payload. The call-site label is not consulted for these task classes.

### 3.1 Ownership

| Part | Owner | Module |
|---|---|---|
| Leaf kinds, schema registry, builder, rendering, derivation | Gateway | `cv_agent/llm/payload.py` (new) |
| Requirements vocabularies, `RequirementsView`, `NarrativePayloadV1`, template narrative | Requirements (reasoning) | `cv_agent/requirements/structured.py` (new) |
| `SelectionPayloadV1`, ordinal mapping, clarification gate | Model selection (reasoning) | `cv_agent/model_selection/selection_payload.py` (new) |
| `KnowledgeItem.ingest` | Knowledge | `cv_agent/knowledge/models.py` (amended) |

Boundary test `[P§34]`:
- The gateway owns *what may leave the process*. That is the same responsibility as the privacy check it already owns (ADR-0020 §2), so the mechanism goes there.
- Domain schemas stay with their owners, so the gateway never learns CV vocabulary (`[P§19]`; `CLAUDE.md` §3.7).
- The selector gets one narrow boundary exception, importing `cv_agent.requirements.structured.RequirementsView` only, enforced by an AST test (the ADR-0019 §2 pattern). Today its boundary is `knowledge.models` and `llm.base` only (`selector.py:15-16`).

### 3.2 Rules

1. **Structured-only task classes:** `STRUCTURED_ONLY = {SELECTION, NARRATIVE}`. A hosted request for one of these without `payload` raises `LLMUnstructuredRequestError`. This happens before the input check, the budget reservation and any network I/O, so no call row is written (ADR-0020 §5.1).
2. **When `payload` is set:**
   - `prompt` and `system` must be empty;
   - `data_classes` must be empty;
   - the outbound `(system, prompt)` is `render(payload)`;
   - the effective data classes are `payload.data_classes`.

   A caller cannot widen or narrow them. Any violation raises `LLMPayloadMisuseError`.
3. **Templates are schema constants.** `SYSTEM` and `INSTRUCTIONS` are `ClassVar[str]` string literals on the registered schema class; an AST test enforces this. The only variable part of a rendered prompt is the canonical JSON body. Candidate ordinal lists live in the body, not in the template.
4. **Schema registration** (`@register_schema`) validates annotations at import:
   - allowed leaves are `Enum` subclasses, `VocabToken`, `Quantity`, `bool`, `int`, `PublicClaim`, nested registered frozen dataclasses, and `tuple[...]` of these, with a declared maximum length;
   - `str`, `Any`, `dict`, `list`, `object` and unions containing them are rejected;
   - registration is allowed only from modules on an allowlist (the two schema modules above), and the registry is sealed after import.
5. **Unstructured task classes** (EXTRACTION) are unchanged: label-based, as in ADR-0020. See §9 (Q41).
6. **Offline parity:** `FakeLLMProvider` renders a payload request through the same `render()`, so mock and hosted see byte-identical `(system, prompt)`.

### 3.3 NARRATIVE: decision

**What the user loses when the narrative is built from structure instead of their words:**
- their own wording and emphasis;
- site specifics (a named site, a camera brand);
- numbers (camera count, fps, latency budgets), because no numeric extractor exists;
- negation: the keyword detectors match `outdoor` inside "not outdoor" (`analyzer.py:44-45`). An LLM reading free text might notice that; a structured payload repeats the detector's reading.

The narrative was never a source of fact (ADR-0008 §3; `requirements/models.py:146-150`), and `original_request` and `problem_statement` still hold the user's words locally. The loss is presentational, not factual.

| | (a) LLM narrative from `NarrativePayloadV1` (fast tier) | (b) Deterministic template, offline |
|---|---|---|
| Information content | Same fields as (b); may add fluent cross-field phrasing | Same fields |
| Determinism and tests | Nondeterministic (no temperature, ADR-0020 §6); content not golden-testable | Deterministic; golden-testable |
| Cost and latency | One governed call, a log row, about $0.0005 worst case on Haiku, network latency | None |
| Failure modes | Truncation, refusal, budget refusal, missing key on the second PC | None |
| Risk of invented facts | Possible (prose over enums) | None |

**Recommendation: (b).** The deterministic template becomes the default narrative.
- `RequirementsAnalysis` gains `narrative_source: Literal["template", "llm"] | None`.
- `NarrativePayloadV1` is still defined and implemented, so (a) stays available.
- Switching NARRATIVE to `fast` needs the owner to choose (a), answering Q39, plus a D-entry.

`[P§34]`: prefer the smaller system; the LLM call adds cost and failure modes without new information.

### 3.4 Knowledge layer: `ingest`

`KnowledgeItem` gains `ingest: IngestPath = IngestPath.UNSPECIFIED`, with `IngestPath {WEB_FETCH, CURATED_REFERENCE, PROJECT_INPUT, UNSPECIFIED}`. Writers must set it explicitly; an AST test requires `ingest=` on every `KnowledgeItem(` construction in `cv_agent/`.

**Known writers today (to be confirmed by the S4 inventory, §7):**
- `cv_agent/graph/research.py:390-408` (`perform_research`, after an http(s) fetch): sets `WEB_FETCH`.
- `cv_agent/model_selection/reference_task_research.py:398-412` (curated reference evidence): sets `CURATED_REFERENCE`.

`ingest` is set by the knowledge writer, never by the LLM call site. The URL, source-class and provenance checks (§2.3) are structural and run in the builder regardless.

### 3.5 SELECTION: decision

**Signal kept:**
- every eligible public claim (the main signal, unchanged in content);
- task components with their confidence;
- per field: status and matched trigger terms (for example `deployment_target: [jetson, edge]`, `latency_requirement: [real-time]`, `environment_context: [outdoor]`);
- per candidate: benchmark-evidence present, compatibility evidence present, claim counts by source class;
- conflicts as `(E<i>, E<j>, ConflictDimension)`.

**Signal lost:**

| Lost item | Assessment |
|---|---|
| `task_description` specifics | Lost |
| Strengths, limitations and compatibility prose | No provenance, so dropping it is consistent with `[P§29.3]` |
| Model family names | The claims name them |
| URLs | Cited by ordinal instead |
| Conflict note prose | Replaced by `ConflictDimension`: `hardware`, `model_scale`, `dataset`, `metric_definition`, `input_resolution`, `precision`, `other` |
| Numeric targets | Lost until a v2 schema adds `Quantity` fields fed by a deterministic extractor or by typed clarification answers |

**Judgement:** this is enough signal for a *proposal*. `SelectionRecommendation.is_proposal` stays invariant True (`model_selection/models.py:169-176`), and the response is still validated locally: ordinal → `candidate_id`, confidence enum. Whether Opus ranks as well on structure as on prose is **not assumed**: §7's route-switch gate requires a recorded comparison.

**Required fields:** `operational_objective`, `deployment_target` and `latency_requirement`, each with at least one admissible trigger token, plus at least one task component.

**If a required field is unknown, or has no admissible token:**
1. `select_candidate` returns a typed `SelectionNeedsClarification(fields)`. It does not call the LLM.
2. The graph routes to the existing `clarify` interrupt (ADR-0003; `cv_agent/graph/workflow.py:163-164`).
3. Answers become `assumptions` as today. Their text stays local; the field's trigger vocabulary is re-matched against the answer locally, and only matched tokens become admissible.
4. If after the bounded clarify loop (ADR-0003 §9) a required field still has no admissible token, the run stays local: no hosted call, and the recommendation is `confidence="insufficient_evidence"` with a local note.

Free text is **never** sent as a fallback.

## 4. Alternatives considered

| Alternative | For | Against | Verdict |
|---|---|---|---|
| **(A) Structured-field payloads, built only by a typed builder; data class derived from the payload type** | A guarantee by construction that tests can check exhaustively (no `str` leaf can exist); deterministic hashes for `[P§25]`; no new dependency | Loses wording, numbers and negation context (§3.3, §3.5); needs vocabulary upkeep | **Chosen** (owner direction, D-094) |
| **(B) Local free-text redaction** (NER model or regex scrubbing before send) | Keeps most wording | Recall below 100% fails **open and silently**: an unredacted site name, client code or person name leaves the process. Unknown entity types (internal site codes, camera IDs) are invisible to NER. Needs a heavy dependency with model weights (a new `[P§34]` boundary). Cannot be proven exhaustively, only sampled. Still a heuristic label | Rejected |
| **(C) Per-project opt-in to `PROJECT_DATA` for hosted tiers** | Full signal; small change (a config value plus a D-entry, ADR-0020 §3 item 7) | Sends user wording to a third party; rejected by the owner on 2026-11-12 | Rejected for now. **Revisit trigger:** the owner wants user wording to reach a hosted tier **and** the provider's data-retention terms for the account have been verified and recorded with a date; **or** the §7 comparison shows structured selection is inadequate against owner judgement |
| **(D) Deterministic ranker, no LLM for SELECTION** | Free, reproducible, no privacy question | Cannot weigh conflicting prose claims; the comparison table must still be read by someone | Kept as the **baseline** in the §7 SELECTION gate and as the fallback |
| **(E) Status quo: call-site labels only** | No work | Not by construction: any call site can mislabel free text as `PROJECT_METADATA` | Rejected |

## 5. Interface

All stubs are **PROPOSED**: types and signatures only, no bodies. They are implemented in slices S1 to S5 (§7).

```python
# PROPOSED — cv_agent/llm/payload.py   (gateway-owned; imports only stdlib, llm.policy, knowledge.models)
class Unit(str, Enum):
    MS = "ms"; FPS = "fps"; MB = "mb"; W = "w"; PX = "px"; COUNT = "count"; RATIO = "ratio"

VocabOrigin = Literal["code", "packaged_resource"]

@dataclass(frozen=True)
class Vocabulary:
    name: str                     # e.g. "requirement_field", "trigger:deployment_target", "task_component"
    version: str                  # sha256 of the sorted members (first 12 hex)
    members: frozenset[str]
    origin: VocabOrigin
    def token(self, value: str) -> "VocabToken": ...          # PayloadFieldError if value not in members

@dataclass(frozen=True)
class VocabToken:                 # issued only by Vocabulary.token (module-private token)
    vocabulary: str
    value: str

@dataclass(frozen=True)
class Quantity:
    value: float
    unit: Unit                    # must equal the unit declared on the schema field

@dataclass(frozen=True)
class FieldBounds:                # attached via dataclasses.field(metadata={"bounds": FieldBounds(...)})
    minimum: float | None = None
    maximum: float | None = None
    max_items: int | None = None  # required for every tuple field
    unit: Unit | None = None
    vocabulary: str | None = None # required for every VocabToken field

class IngestPath(str, Enum):      # PROPOSED — lives in cv_agent/knowledge/models.py (§3.4); re-exported here
    WEB_FETCH = "web_fetch"; CURATED_REFERENCE = "curated_reference"
    PROJECT_INPUT = "project_input"; UNSPECIFIED = "unspecified"

class ExclusionReason(str, Enum):
    NO_PROVENANCE = "no_provenance"; NON_PUBLIC_URL = "non_public_url"
    SOURCE_CLASS_NOT_ALLOWED = "source_class_not_allowed"; INGEST_NOT_ALLOWED = "ingest_not_allowed"

WEB_SOURCE_CLASSES: frozenset[str] = frozenset({
    "peer_reviewed_research", "official_documentation", "official_repository_or_release_notes",
    "reputable_benchmark", "engineering_blog", "community_discussion", "model_zoo_or_leaderboard",
})                                # professional_post excluded; new SourceClass values excluded by default
MAX_CLAIM_CHARS: int = 300
MAX_CONDITIONS_CHARS: int = 150
MAX_CLAIMS_PER_CANDIDATE: int = 10    # N
MAX_CLAIMS_PER_PAYLOAD: int = 30      # M

@dataclass(frozen=True)
class PublicClaim:                # issued only by PublicClaim.from_item (module-private token)
    ordinal: int                  # E<n>, assigned by the builder
    claim: str                    # KnowledgeItem.claim verbatim, <= MAX_CLAIM_CHARS
    conditions: str | None        # KnowledgeItem.conditions verbatim, <= MAX_CONDITIONS_CHARS
    source_class: str             # member of WEB_SOURCE_CLASSES
    evidence_weight: str          # EvidenceWeight
    is_benchmark: bool
    @classmethod
    def from_item(cls, item: object, *, ordinal: int, is_benchmark: bool
                  ) -> "PublicClaim | ExclusionReason": ...   # never raises for ineligibility; excludes

def select_claims(items: Sequence[tuple[object, bool]], *, per_candidate: int, start_ordinal: int
                  ) -> tuple[tuple[PublicClaim, ...], int, Mapping[ExclusionReason, int]]: ...
    # -> (claims, omitted_count, excluded_counts); deterministic order per §2.3

class PayloadSchema(Protocol):
    SCHEMA_ID: ClassVar[str]
    SCHEMA_VERSION: ClassVar[int]
    TASK_CLASS: ClassVar[TaskClass]
    SYSTEM: ClassVar[str]         # string literal (AST-checked)
    INSTRUCTIONS: ClassVar[str]   # string literal (AST-checked)

def register_schema(cls: type[T]) -> type[T]: ...   # validates annotations; allowlisted modules only; sealed after import
def register_vocabulary(vocab: Vocabulary) -> Vocabulary: ...

@dataclass(frozen=True)
class HostedPayload:              # issued only by build_payload (module-private token, the D-081 M2 pattern)
    schema_id: str
    schema_version: int
    task_class: TaskClass
    vocabulary_versions: Mapping[str, str]
    body_json: str                # canonical: sort_keys, separators=(",", ":"), ensure_ascii=False
    payload_sha256: str           # sha256 of body_json
    data_classes: frozenset[DataClass]   # {PROJECT_METADATA} | {PROJECT_METADATA, PUBLIC_WEB}

def build_payload(instance: PayloadSchema) -> HostedPayload: ...  # PayloadFieldError on any illegal leaf
def render(payload: HostedPayload) -> tuple[str, str]: ...        # (system, prompt): schema constants + body_json

STRUCTURED_ONLY: frozenset[TaskClass] = frozenset({TaskClass.SELECTION, TaskClass.NARRATIVE})
```

```python
# PROPOSED — cv_agent/llm/base.py (amended)
@dataclass
class LLMRequest:
    prompt: str = ""                     # must be "" when payload is set
    system: str | None = None            # must be None when payload is set
    max_tokens: int | None = None
    data_classes: frozenset[DataClass] = frozenset()   # must be empty when payload is set
    payload: HostedPayload | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

```python
# PROPOSED — cv_agent/llm/errors.py (additions)
class LLMUnstructuredRequestError(LLMError):     # hosted STRUCTURED_ONLY request without payload
    def __init__(self, task_class: TaskClass, tier: str) -> None: ...
class LLMPayloadMisuseError(LLMError): ...       # payload plus prompt/system/data_classes
class PayloadFieldError(ValueError): ...         # builder/schema rejection (raised before any request exists)
```

```python
# PROPOSED — cv_agent/llm/governed.py (amended behaviour; signature unchanged)
class GovernedProvider(LLMProvider):
    def complete(self, request: LLMRequest) -> LLMResponse: ...
    # order: structured-only guard -> payload misuse -> render -> privacy on payload.data_classes
    #        -> caps -> budget -> adapter -> stop policy -> log (payload_schema, payload_sha256)
```

```python
# PROPOSED — cv_agent/llm/sqlite_store.py (amended)
@dataclass(frozen=True)
class CallRecord:
    ...                                   # ADR-0020 §5.1 columns, unchanged
    payload_schema: str | None = None     # "<schema_id>/<version>", NULL for unstructured calls
    payload_sha256: str | None = None
class LLMCallStore:
    @staticmethod
    def migrate(path: Path) -> None: ...  # ADD COLUMN (nullable) only; refuses a missing file; idempotent
# A store without the two columns fails closed with LLMStoreError and the hint `cv-agent llm-log migrate`.
```

```python
# PROPOSED — cv_agent/requirements/structured.py
class FieldSource(str, Enum):
    USER_REQUEST = "user_request"; CALLER_ASSUMPTION = "caller_assumption"

@dataclass(frozen=True)
class FieldView:
    name: VocabToken                     # vocabulary "requirement_field"
    status: InfoStatusEnum               # KNOWN | UNKNOWN | ASSUMED
    source: FieldSource
    terms: tuple[VocabToken, ...]        # vocabulary "trigger:<field>"; never the field value

@dataclass(frozen=True)
class TaskView:
    component: VocabToken                # vocabulary "task_component"
    confidence: Quantity                 # Unit.RATIO, 0..1

@dataclass(frozen=True)
class RequirementsView:
    fields: tuple[FieldView, ...]
    tasks: tuple[TaskView, ...]
    capability_links: int; capability_links_available: int
    skill_links: int; skill_links_executable: int; skill_links_declared: int
    open_questions: int
    risk_fields: tuple[VocabToken, ...]

def structured_view(analysis: RequirementsAnalysis) -> RequirementsView: ...
def render_template_narrative(view: RequirementsView) -> str: ...   # recommended default, §3.3 (b)

@register_schema
@dataclass(frozen=True)
class NarrativePayloadV1:
    SCHEMA_ID = "narrative"; SCHEMA_VERSION = 1; TASK_CLASS = TaskClass.NARRATIVE
    SYSTEM = "..."; INSTRUCTIONS = "..."      # literals, fixed in S3
    view: RequirementsView
```

```python
# PROPOSED — cv_agent/model_selection/selection_payload.py
class ConflictDimension(str, Enum):
    HARDWARE = "hardware"; MODEL_SCALE = "model_scale"; DATASET = "dataset"
    METRIC_DEFINITION = "metric_definition"; INPUT_RESOLUTION = "input_resolution"
    PRECISION = "precision"; OTHER = "other"

@dataclass(frozen=True)
class CandidateBlock:
    ordinal: int                          # C<n>, 1..8
    task_support: tuple[VocabToken, ...]  # "task_component" members only; others counted
    task_support_unrecognised: int
    claims: tuple[PublicClaim, ...]       # <= MAX_CLAIMS_PER_CANDIDATE
    claims_omitted: int
    claims_excluded: int
    has_benchmark_evidence: bool
    has_compatibility_evidence: bool

@dataclass(frozen=True)
class ConflictRef:
    first: int; second: int               # claim ordinals E<n>
    dimension: ConflictDimension

@register_schema
@dataclass(frozen=True)
class SelectionPayloadV1:
    SCHEMA_ID = "selection"; SCHEMA_VERSION = 1; TASK_CLASS = TaskClass.SELECTION
    SYSTEM = "..."; INSTRUCTIONS = "..."      # literals, fixed in S4
    requirements: RequirementsView
    candidates: tuple[CandidateBlock, ...]    # 1..8; total claims <= MAX_CLAIMS_PER_PAYLOAD
    conflicts: tuple[ConflictRef, ...]
    claims_omitted_total: int

@dataclass(frozen=True)
class SelectionNeedsClarification:
    missing_fields: tuple[str, ...]       # field names (CV), for the clarify interrupt

def build_selection_payload(comparison: CandidateComparison, requirements: RequirementsView
                            ) -> tuple[SelectionPayloadV1, Mapping[int, str]] | SelectionNeedsClarification: ...
    # Mapping: candidate ordinal -> candidate_id, kept local
```

```python
# PROPOSED — cv_agent/model_selection/selector.py (amended signature)
def select_candidate(comparison: CandidateComparison, *, requirements: RequirementsView,
                     llm_provider: LLMProvider) -> SelectionRecommendation | SelectionNeedsClarification: ...
# ConflictNote gains `dimension_kind: ConflictDimension` (the free-text `dimension`/`note` stay local).
```

```python
# PROPOSED — cv_agent/knowledge/models.py (amended)
@dataclass(frozen=True)
class KnowledgeItem:
    ...                                    # unchanged fields
    ingest: IngestPath = IngestPath.UNSPECIFIED
```

## 6. Consequences

- **Enables:**
  - the guarantee that no user-originated free text reaches a hosted tier holds by construction for SELECTION and NARRATIVE;
  - the strong tier gets a permitted use once the §7 gate is met;
  - payload hashes and schema versions in the call log (`[P§25]`).
- **Makes harder:**
  - vocabulary upkeep (adding a trigger term changes a vocabulary version and the golden payloads);
  - schema changes need a version bump;
  - narratives lose the user's wording (§3.3);
  - selection loses prose and numbers until a v2 schema (§3.5);
  - the owner's existing call-log store needs `cv-agent llm-log migrate` once.
- **Costs (build, runtime, GPU, $):**
  - about 1,450 lines over five slices (§7);
  - no new dependency;
  - runtime: microseconds of validation per call;
  - no GPU;
  - $0 until a route is switched. The worst case per hosted SELECTION call is at or below ADR-0020's strong-tier $0.18.
- **Migration / blast radius if reversed:** routing every class back to `offline` restores today's behaviour. Reverting S3 restores the LLM narrative path. The payload columns are nullable.
- **Risks:**
  - keyword-detector negation misreads are carried into the payload;
  - `ingest` is a writer-set enum. The AST test and the S4 writer inventory bound it, but a future writer that sets `WEB_FETCH` wrongly would pass. The URL and source-class checks still apply;
  - public claims are third-party text and could contain anything a public page contains. That is the `PUBLIC_WEB` class ADR-0020 already allows;
  - EXTRACTION stays label-based (§9).
- **Amended ADRs:** on acceptance of ADR-0023, the acceptance PR adds an "Amended by ADR-0023" note to [ADR-0020](ADR-0020-llm-gateway-v2.md), [ADR-0014](ADR-0014-model-selection.md) and [ADR-0008](ADR-0008-requirements-analysis.md). It also adds one to [ADR-0006](ADR-0006-knowledge-context-boundary.md), for the `KnowledgeItem.ingest` field (§3.4). **None of those files is edited in this PR.**

## 7. Acceptance tests and implementation slices

### 7.1 Acceptance criteria

1. **Golden payloads:**
   - `tests/golden/llm_payloads/selection_v1.json` and `narrative_v1.json` hold the canonical body plus `payload_sha256` for the reference comparison and three fixed requirement inputs;
   - a shape change without a `SCHEMA_VERSION` bump fails;
   - a vocabulary change updates `vocabulary_versions` and the goldens in the same PR.
2. **Canary/fuzz suite** (`tests/test_llm_payload_canary.py`):
   - Marker strings (`CANARY-<hex>`) are injected into every free-text input: the request, `task_description`, caller assumption values, clarification answers, strengths, limitations, compatibility constraints, `ConflictNote.dimension` and `.note`, `candidate_id`, `model_family`, discovered `skill_id` and skill paths, and capability IDs from a non-packaged `registry_path`.
   - Seeds come from stdlib `random` with fixed seeds (no new dependency).
   - Both task classes run through (i) the offline mock and (ii) a hosted `GovernedProvider` with a recording fake adapter and a temporary store.
   - **Assert:** no marker appears in any outbound `system` or `prompt`, nor in the call-log row (including `store_text = true`).
3. **Canary through the knowledge path** (same suite): marker strings are seeded into `KnowledgeItem.claim` and `.conditions` for these cases:
   - (a) an item with `ingest=PROJECT_INPUT`;
   - (b) an item with `ingest=UNSPECIFIED`;
   - (c) an object with no provenance;
   - (d) an item whose `SourceClass` is not allowlisted (`professional_post`);
   - (e) items with URLs `file:///…`, `http://10.0.0.5/…`, `http://intranet/…`, `https://cam.site.local/…` and `https://user:pw@example.com/…`.

   Each must be excluded and counted under the right `ExclusionReason`, and its markers must never appear in any outbound request. A control item (`WEB_FETCH`, `https://docs.example.org/…`, `official_documentation`) **is** sent verbatim, truncated at 300 characters.
4. **Builder rejections:** a `str` annotation at registration; a bare `str` leaf; an out-of-vocabulary token; NaN, ±inf and out-of-bounds `Quantity` values; a wrong unit; a tuple over `max_items`; a registration from a non-allowlisted module; a registration after seal. Each raises `PayloadFieldError`.
5. **Caps:** a comparison with 12 eligible claims for one candidate sends 10 (`claims_omitted=2`). A comparison with 40 eligible claims sends 30. The order follows §2.3.
6. **Structured-only guard:** a hosted SELECTION or NARRATIVE request without a payload raises `LLMUnstructuredRequestError` with no adapter call, no reservation and no call row. Payload plus `prompt`, `system` or `data_classes` raises `LLMPayloadMisuseError`.
7. **Derivation:** the effective data classes equal `payload.data_classes` whatever the caller passes; a payload with no `PublicClaim` carries no `PUBLIC_WEB`.
8. **Call log:** rows carry `payload_schema` (`selection/1`, `narrative/1`) and `payload_sha256`, equal to the golden hash. Both are NULL for EXTRACTION. An un-migrated store fails closed with the migrate hint.
9. **Mock/offline parity:** for the same payload, the mock and the recording hosted adapter receive byte-identical `(system, prompt)`.
10. **Clarification gate:** an unknown `deployment_target` yields `SelectionNeedsClarification(("deployment_target",))` with no LLM call. After a clarification answer whose text holds no trigger term, there is still no hosted call and the result is `insufficient_evidence`.
11. **Structural (AST):**
    - `SYSTEM` and `INSTRUCTIONS` are literals;
    - every `KnowledgeItem(` in `cv_agent/` passes `ingest=`;
    - the selector imports only `knowledge.models`, `llm.base`, `llm.policy`, `llm.payload` and `requirements.structured.RequirementsView`;
    - no provider or model string outside `cv_agent/llm/`.

### 7.2 Slices (each ≤ about 400 lines including tests; each with its own issue)

| Slice | Content | Lines (approx.) |
|---|---|---|
| **S1** | `llm/payload.py` (leaf kinds, vocabularies, schema registry, builder, render, `PublicClaim` with the §2.3 eligibility); `LLMRequest.payload`; governed guard and derivation; new errors; `FakeLLMProvider` render parity; criteria 4, 6, 7, 9, plus the `PublicClaim` unit cases of criterion 3 | 380 |
| **S2** | Call-log `payload_schema`/`payload_sha256`; `LLMCallStore.migrate`; `cv-agent llm-log migrate`; criterion 8 | 200 |
| **S3** | `RequirementField` retains matched trigger terms; requirements vocabularies registered; `RequirementsView`, `structured_view`; `NarrativePayloadV1`; template narrative and `narrative_source`; the analyzer stops sending the raw request; narrative golden; NARRATIVE part of criterion 2 | 350 |
| **S4** | **Required first step: a KnowledgeStore writer inventory** listing every `KnowledgeStore.put` and `KnowledgeItem(` construction in `cv_agent/` with file:line and the `ingest` value it sets. **The S4 PR must include that table.** Then `KnowledgeItem.ingest`; `SelectionPayloadV1`, `CandidateBlock`, `ConflictRef`, `ConflictDimension`; the ordinal mapping; the clarification gate; the `select_candidate` signature; the boundary exception; selection golden; criteria 5, 10 | 400 |
| **S5** | The full cross-path canary/fuzz suite (criteria 2 and 3 end to end) and the structural tests (criterion 11) | 150 |

**Order:** S1 → S2 → S3 → S4 → S5. S3 and S4 depend on S1. S5 runs last so it covers both call sites.

### 7.3 Route switches (owner decisions; `[llm.routing]` PRs with a D-entry each)

- **NARRATIVE → `fast`:** only if the owner chooses (a) over the recommended (b) (§3.3), which answers Q39, after S1 to S3 and S5 are merged.
- **SELECTION → `strong`:** only when **all** of the following hold:
  - S4 and S5 are merged;
  - a production caller of `select_candidate` exists (none today);
  - **a recorded comparison exists**: on the reference tasks, the structured-payload Opus ranking set against the deterministic ranker (Alternative D), with the owner's judgement recorded (as an experiment or decision record with the `llm_call_ids` link of ADR-0020 §3 item 13).

  Then an owner D-entry switches the route. **Until then the strong tier stays `offline`.**
- `[llm.privacy] hosted_allowed_data_classes` is **not** changed by any slice. `PROJECT_DATA` stays blocked (D-094).

## 8. Revisit trigger

- A new free-text input reaches either call site (a new request field, a notes field, a new analyzer input).
- A `SourceClass` for user-supplied documents is proposed, or any `KnowledgeStore` writer outside the S4 inventory appears.
- A deterministic numeric extractor or typed clarification answers exist: schema v2 with `Quantity` fields.
- **Q41 lands**: a user-facing research command gives EXTRACTION a user entry point. Re-evaluate moving EXTRACTION to a payload schema (§9).
- The owner revisits Alternative (C), or the provider's data-retention terms change.
- The §7.3 comparison shows structured selection is inadequate against owner judgement.
- A payload ever exceeds the input cap at N = 10 and M = 30 (the caps would need revising).

## 9. EXTRACTION and Q41

A parallel session is building a user-facing research command (Q41) that calls `perform_research`. That gives EXTRACTION a user entry point. **EXTRACTION stays label-based in this ADR**, and that remains acceptable for these reasons:
- The only project-derived text in an extraction request is the claim query. It must be built by `claim_query_from` (`cv_agent/graph/research.py:178-190`), which admits single identifier tokens only: letters, digits, `. _ / + : -`, no spaces or newlines, at most 64 characters, enforced by `_token` (`:169-175`).
- The rest of the request is the fetched URL and fetched public page text (`PUBLIC_WEB`). The request declares `{PUBLIC_WEB, PROJECT_METADATA}` (`research.py:307`).
- The residual risks are named:
  - an identifier token can still spell a site or client code (for example `acme_site3`);
  - the fetched URL is caller-supplied.

  Both are bounded: one token or one URL, never a sentence. Q41's command must use `claim_query_from` (STATUS "Next actions", D-093).

"Q41 lands" is a revisit trigger (§8) for moving EXTRACTION to a payload schema built by the same builder, with the URL reduced to a public-host check as in §2.3.

## 10. Not verified at drafting time

- **Resolver tokens:** the exact token origin of `CapabilityLink.matched_terms` and `SkillLink.matched_terms` (an overlap of query and registry or skill tokens, `skills/resolver.py:41`, `:185`). They are excluded in v1 for that reason.
- **Payload size:** the token count of the canonical JSON compared with today's prose prompt. The character budget in §2.3 is an estimate, not a measurement.
- **Selection quality:** whether Opus selection quality on structure alone matches its quality on prose. Deliberately **not assumed**: the §7.3 gate requires the measured comparison.
- **Hostname rule:** whether the reserved-suffix list in §2.3 rule 2 covers every private naming scheme the owner uses. The rule is conservative (a dotted public DNS name is required), but an intranet host with a public-looking name would pass.

Whether every `KnowledgeItem` path is truly public-web is **not** left unverified here: the KnowledgeStore writer inventory is a required first step of slice S4, and the S4 PR must include it (§7.2).
