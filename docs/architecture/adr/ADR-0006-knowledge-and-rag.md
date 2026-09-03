# ADR-0006: Knowledge & RAG Subsystem

- **Status:** Proposed
- **Date:** 2026-09-03
- **Layer:** knowledge / retrieval
- **Canon:** `[P§16]`, `[P§17]`, `[P§18]`, `[P§19]`, `[P§29.3]`, `[P§29.7]`, `[P§34]`
- **Supersedes / Superseded by:** —
- **Issue:** #TBD

## 1. Context

Computer vision engineering evolves too rapidly for an agent to rely solely on pretrained parametric memory `[P§16]`. Model architectures, framework APIs (TensorRT, DeepStream, PyTorch), edge hardware characteristics (NVIDIA Jetson families), and training recipes change continuously. Relying on static weights causes hallucinations, obsolete recommendations, and deployment failures `[P§29.4]`.

However, addressing this through unstructured web retrieval or indiscriminate document dumping introduces severe failure modes:
1. **Layer Leakage (`[P§19]`, `[P§34]`):** RAG is not the agent. If retrieval merges with reasoning or graph orchestration, the system becomes an uncontrolled prompt-stuffing pipeline (`[P§31]`). Retrieval must serve structured, evidence-weighted context to reasoning nodes, not dictate workflow decisions.
2. **Evidence Quality & Credibility Dilution (`[P§17]`, `[P§29.3]`):** Engineering blogs, vendor marketing, LinkedIn posts, arXiv preprints, and official documentation do not possess equal evidential value. Treating an unverified blog post or promotional claim with the same authority as peer-reviewed benchmarks or official release notes degrades engineering rigor.
3. **Missing Provenance & Stale Context (`[P§18]`, `docs/RESEARCH_POLICY.md`):** Storing claims without explicit metadata (source URL, author/org, publication date, retrieval timestamp, hardware conditions) makes citations unverifiable. Furthermore, knowledge degrades at different rates: framework versions become stale in weeks, while fundamental principles remain valid for years.
4. **Project Isolation & Storage Confusion (`D-013`, ADR-0004):** Project-specific learnings, experiment histories, and domain definitions belong in Project Memory (`.cv_agent/memory/`) and the Experiment Ledger (`experiments.sqlite`). In contrast, general CV engineering knowledge, external documentation, and research findings belong to the Knowledge subsystem. Conflating them destroys reproducibility and project isolation.

Phase 2 requires an explicit architectural specification defining knowledge ingestion, chunking, indexing, retrieval, credibility weighting, provenance tracking, and freshness boundaries.

## 2. Responsibility (`[P§34]`)

- **This owns:**
  - The definition and schema of knowledge documents, chunks, and metadata (`KnowledgeDocument`, `KnowledgeChunk`, `Provenance`).
  - Classification of knowledge sources and evidence weighting (`SourceClass`, `EvidenceWeight` per `[P§17]`).
  - Ingestion, sanitization, structural normalization, and chunking of external text, documentation, and research artifacts.
  - Hybrid indexing (dense vector embeddings and sparse lexical search) and index persistence scoped to the project workspace (`.cv_agent/knowledge/`).
  - Query analysis, retrieval execution, multi-factor re-ranking (similarity, credibility weight, freshness), and context assembly.
  - Staleness evaluation and freshness horizons per topic domain `[P§18]`.
  - The programmatic query interface (`KnowledgeRetriever`) consumed by orchestration and reasoning.
- **This does NOT own:**
  - Reasoning, decision logic, prompt synthesis, or CV problem decomposition → Reasoning Subsystem (ADR-0008) `[P§19]`, `[P§34]`;
  - Workflow graph execution, checkpointing, and human approval interrupts → Orchestration State Machine (ADR-0003) `[P§21]`, `[P§24]`;
  - Physical network fetching, HTTP requests, web scraping, or PDF extraction tools → Tools & MCP Layer (ADR-0005) `[P§22]`;
  - Low-level vector embedding generation and LLM inference → LLM Gateway (ADR-0002) `[P§20]`;
  - Git-tracked structured project memory (`.cv_agent/memory/`) and permanent experiment run metrics (`experiments.sqlite`) → Project Memory & Experiment Ledger (ADR-0004) `[P§25]`, `[P§33]`;
  - Procedural engineering recipes and domain workflows → Skills Subsystem (ADR-0007) `[P§23]`.
- **Why this responsibility does not belong elsewhere:**
  Reasoning needs factual context, but must not know embedding dimensions or BM25 formulas. Tools fetch raw bytes, but must not decide credibility or semantic relevance. Project Memory stores *what this specific project did*, while Knowledge stores *what is known about the wider computer vision engineering world*. Isolating Knowledge/RAG prevents prompt bloating, preserves reproducibility, and ensures strict evidential rigor.

## 3. Decision

We establish an explicit **Knowledge and Retrieval-Augmented Generation (RAG) Boundary** structured around dual knowledge mechanisms, strict source credibility classification, mandatory provenance tracking, topic-based freshness horizons, and workspace-contained hybrid indexing.

### 3.1. Architectural Conceptual Model

```text
                  Tools / MCP Layer (ADR-0005)
                  (web search, fetchers, loaders)
                               │
                               │ raw content & fetch metadata
                               ▼
                   ┌───────────────────────┐
                   │  Ingestion & Filter   │ ◄── Relevance Gate ([P§18])
                   │      Pipeline         │
                   └───────────┬───────────┘
                               │
                       chunk & attach metadata
                               │
                               ▼
                   ┌───────────────────────┐
                   │   Provenance & Date   │ ◄── Validation Gate:
                   │      Enforcement      │     Missing date/source rejected
                   └───────────┬───────────┘
                               │
                ┌──────────────┴──────────────┐
                ▼                             ▼
       Dense Embeddings               Lexical Tokens
       (via ADR-0002 Gateway)        (BM25 Inverted Index)
                │                             │
                └──────────────┬──────────────┘
                               ▼
                   ┌───────────────────────┐
                   │ Hybrid Vector Store   │ (.cv_agent/knowledge/)
                   │  & Document Archive   │
                   └───────────┬───────────┘
                               │
                               │ query
                               ▼
                   ┌───────────────────────┐
                   │  Knowledge Retriever  │
                   │ (similarity + weight  │ ◄── Evidence Weighting ([P§17])
                   │    + freshness)       │ ◄── Freshness Decay ([P§18])
                   └───────────┬───────────┘
                               │
                               │ verified context with citations
                               ▼
                     Reasoning Nodes (ADR-0008)
                     in Orchestration (ADR-0003)
```

### 3.2. Two Knowledge Mechanisms (`[P§16]`, `docs/RESEARCH_POLICY.md`)

The subsystem maintains an architectural separation between:
1. **Persistent Knowledge:** Curated, durable engineering information:
   - Fundamental CV principles and mathematical foundations;
   - Architecture documentation, sensor characteristics, and deployment guides;
   - Model zoo specifications and official framework documentation;
   - Canonical papers and benchmark datasets.
2. **Live Research:** Ephemeral, fast-moving ecosystem intelligence acquired on demand:
   - Recent library releases (YOLO versions, TensorRT updates, DeepStream patches);
   - Vendor announcements and Jetson hardware revisions;
   - Practitioner findings and emerging GitHub implementations;
   - Live research results are vetted against the 7-step pipeline (`[P§18]`) before ingestion into the persistent knowledge store.

### 3.3. Source Classes & Evidence Weighting Hierarchy (`[P§17]`, `docs/RESEARCH_POLICY.md`)

Every stored document and retrieved chunk MUST be tagged with an explicit `SourceClass`. Retrieval scoring scales relevance by an architectural `EvidenceWeight`:

| Source Class | Evidence Weight | Permitted Usage | Constraints / Caveats |
|---|---|---|---|
| `PEER_REVIEWED_RESEARCH` | 1.0 (High) | Algorithmic validity, baseline theory | May not reflect real-world edge deployment limits |
| `OFFICIAL_DOCUMENTATION` | 1.0 (High) | APIs, supported runtimes, official constraints | Verify against actual version; documentation can lag |
| `OFFICIAL_REPOSITORY` | 1.0 (High) | Concrete implementation, release notes | Read code/commits, not marketing READMEs |
| `REPUTABLE_BENCHMARK` | 0.9 (High) | Quantitative baseline comparisons | Method must be reproducible; hardware must be documented |
| `ENGINEERING_BLOG` | 0.6 (Medium) | Practical deployment tricks, failure modes | Discount vendor marketing claims `[P§29.3]` |
| `MODEL_ZOO_LEADERBOARD` | 0.6 (Medium) | Architecture candidate discovery | Benchmark numbers on public sets rarely match target data |
| `COMMUNITY_DISCUSSION` | 0.4 (Low-Med) | Known bugs, driver conflicts, edge frictions | Anecdotal; requires independent validation |
| `PROFESSIONAL_POST` | 0.2 (Signal Only)| Discovering that a technique exists | **Signal, not evidence (`[P§17]`)**. May inspire experiments; cannot justify architectural choices |

**The LinkedIn / Professional Post Invariant (`[P§17]`):**
Practical engineering knowledge (e.g., specific TensorRT layer fusions, YOLO loss tweaks) often appears first in public engineering posts. The agent may consume these as *discovery signals*, but they are assigned `EvidenceWeight.SIGNAL_ONLY`. A professional post can justify creating an experiment; it CANNOT serve as the evidential basis for selecting a model or claiming superiority over a baseline.

### 3.4. Mandatory Provenance & Rejection Invariant (`[P§18]`, `docs/RESEARCH_POLICY.md`)

Every stored knowledge item MUST contain complete `Provenance`:
- `source_url`: Canonical URI or file path;
- `source_class`: One of the formal `SourceClass` classifications;
- `author_or_organization`: Named creator, lab, or publisher;
- `published_date`: ISO-8601 date of publication;
- `retrieved_date`: ISO-8601 date when the agent fetched the item;
- `hardware_context`: Target hardware conditions if claims involve performance (e.g., Jetson Orin Nano, FP16, batch=1).

**Provenance Invariant:**
An ingestion candidate lacking a verified URL, publication date, or source class MUST be rejected by the store. Anonymous or un-dated documents cannot enter the knowledge base.

### 3.5. Topic Freshness Horizons & Temporal Decay (`[P§18]`, `docs/RESEARCH_POLICY.md`)

Information in computer vision depreciates over time. The Knowledge subsystem applies topic-specific staleness horizons:

```python
class TopicDomain(str, Enum):
    FRAMEWORK_API = "framework_api"  # TensorRT, PyTorch APIs: horizon = 30 days
    ECOSYSTEM_RELEASE = (
        "ecosystem_release"  # Model releases, versions: horizon = 60 days
    )
    HARDWARE_SPEC = (
        "hardware_spec"  # GPU compute caps, Jetson specs: horizon = 180 days
    )
    BENCHMARK_RESULT = "benchmark_result"  # SOTA numbers, speedups: horizon = 180 days
    CV_ALGORITHM = "cv_algorithm"  # Loss functions, architectures: horizon = 365 days
    CORE_PRINCIPLES = (
        "core_principles"  # Epipolar geometry, filtering: horizon = 1825 days
    )
```

When evaluating a retrieved chunk, the retrieval engine calculates a **Freshness Factor** ($F \in [0.0, 1.0]$):
$$F = \max\left(0.1, 1.0 - \frac{\text{age\_days}}{\text{staleness\_horizon\_days}}\right)$$
Chunks whose age significantly exceeds their domain horizon are penalized during ranking and annotated with a `STALE` warning in their citation block.

### 3.6. Hybrid Indexing & Workspace Isolation (`D-013`, `D-018`)

The Knowledge subsystem employs hybrid retrieval to ensure robust precision across technical tokens and semantic concepts:
1. **Dense Vector Search:** High-dimensional semantic embeddings generated exclusively via the LLM Gateway (`cv_agent.llm` / ADR-0002).
2. **Sparse Lexical Search:** Exact keyword indexing (BM25) over normalized tokens to ensure exact matches for library versions, function names, CUDA error codes, and model identifiers (e.g., `yolov8n-seg`, `cudaErrorMemoryAllocation`).
3. **Workspace Isolation (`D-013`):** All vector indices, document archives, and lexical metadata are strictly contained within `.cv_agent/knowledge/` in the active project workspace root. No global or multi-tenant database is assumed.

### 3.7. The 7-Step Research Pipeline Execution (`[P§18]`)

Live research queries execute through a rigid pipeline:
1. **Find:** Targeted query dispatched to external search/retrieval tools (via ADR-0005).
2. **Relevance Gate:** Evaluates whether retrieved content directly addresses the immediate CV task or query. Irrelevant content is immediately discarded without storage.
3. **Credibility Assignment:** Categorizes content into its formal `SourceClass`.
4. **Extract:** Extracts specific claims, parameters, hardware configurations, and measurements.
5. **Provenance Tagging:** Binds author, URL, publication date, and retrieval timestamp.
6. **Freshness Assessment:** Assigns topic domain and evaluates age against the staleness horizon.
7. **Context Delivery:** Transmits structured context with citation payloads to the reasoning layer.

### 3.8. Boundary Between Knowledge and Project Memory (ADR-0004)

To prevent data duplication and architectural drift:
- **Project Memory (ADR-0004):** Stores *internal operational truth*. It contains Git-tracked architectural summaries (`.cv_agent/memory/`), the task decomposition, baseline selections, and immutable benchmark numbers recorded on target hardware (`experiments.sqlite`).
- **Knowledge Subsystem (ADR-0006):** Stores *external engineering knowledge*. It contains external library documentation, paper excerpts, general CV formulas, and external benchmark reports.
- **Cross-Layer Invariant:** When reasoning evaluates external literature against internal baselines, it queries ADR-0006 for literature claims and ADR-0004 for project measurements. The Knowledge subsystem never writes to `experiments.sqlite`.

## 4. Proposed Interface Contracts (Phase 2 Implementation Target)

*(Note: These interfaces represent the proposed type contracts for Phase 2 implementation. They do not exist in the repository today).*

```python
# module: cv_agent.knowledge.types (Proposed — Phase 2 implementation target)

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, NewType, Protocol, runtime_checkable

DocumentId = NewType("DocumentId", str)
ChunkId = NewType("ChunkId", str)


class SourceClass(str, Enum):
    """Evidential hierarchy of knowledge sources per [P§17] and docs/RESEARCH_POLICY.md."""

    PEER_REVIEWED_RESEARCH = "peer_reviewed_research"
    OFFICIAL_DOCUMENTATION = "official_documentation"
    OFFICIAL_REPOSITORY = "official_repository"
    REPUTABLE_BENCHMARK = "reputable_benchmark"
    ENGINEERING_BLOG = "engineering_blog"
    MODEL_ZOO_LEADERBOARD = "model_zoo_leaderboard"
    COMMUNITY_DISCUSSION = "community_discussion"
    PROFESSIONAL_POST = "professional_post"  # Signal only; never evidence ([P§17])


class TopicDomain(str, Enum):
    """Domain categorization determining freshness horizons."""

    FRAMEWORK_API = "framework_api"  # Horizon: ~30 days
    ECOSYSTEM_RELEASE = "ecosystem_release"  # Horizon: ~60 days
    HARDWARE_SPEC = "hardware_spec"  # Horizon: ~180 days
    BENCHMARK_RESULT = "benchmark_result"  # Horizon: ~180 days
    CV_ALGORITHM = "cv_algorithm"  # Horizon: ~365 days
    CORE_PRINCIPLES = "core_principles"  # Horizon: ~1825 days


@dataclass(frozen=True)
class Provenance:
    """Mandatory provenance metadata required for every stored knowledge item."""

    source_url: str
    source_class: SourceClass
    author_or_organization: str
    published_date: str  # ISO-8601 YYYY-MM-DD
    retrieved_date: str  # ISO-8601 YYYY-MM-DD
    hardware_context: str | None = None
    citation_title: str = ""


@dataclass(frozen=True)
class KnowledgeChunk:
    """Discrete, searchable text segment with attached provenance."""

    chunk_id: ChunkId
    document_id: DocumentId
    content: str
    provenance: Provenance
    topic_domain: TopicDomain
    chunk_index: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeDocument:
    """Complete ingested document before or during chunking."""

    document_id: DocumentId
    title: str
    raw_content: str
    provenance: Provenance
    topic_domain: TopicDomain
    chunks: tuple[KnowledgeChunk, ...] = ()


@dataclass(frozen=True)
class ScoredCitation:
    """Retrieved chunk bundled with relevance, credibility, and freshness metrics."""

    chunk: KnowledgeChunk
    relevance_score: float  # Raw similarity [0.0, 1.0]
    evidence_weight: float  # Multiplier from SourceClass [0.2, 1.0]
    freshness_factor: float  # Freshness decay [0.1, 1.0]
    composite_score: float  # Final ranked score
    is_stale: bool = False


@dataclass(frozen=True)
class RetrievalRequest:
    """Structured retrieval query dispatched by reasoning nodes."""

    query: str
    top_k: int = 5
    topic_filter: TopicDomain | None = None
    min_evidence_weight: float = 0.0
    require_hardware_context: bool = False


@dataclass(frozen=True)
class RetrievalResponse:
    """Ranked context citations returned to the calling reasoning node."""

    query: str
    citations: tuple[ScoredCitation, ...]
    total_candidates: int
    warning_messages: tuple[str, ...] = ()


@runtime_checkable
class KnowledgeIngester(Protocol):
    """Protocol for ingesting, validating, chunking, and indexing external documents."""

    def ingest(self, document: KnowledgeDocument) -> tuple[ChunkId, ...]:
        """Validate provenance and ingest document into hybrid index.

        Raises ValueError if provenance is incomplete or un-dated.
        """
        ...


@runtime_checkable
class KnowledgeRetriever(Protocol):
    """Protocol for querying the knowledge base with composite score ranking."""

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        """Execute hybrid search, compute composite ranking, and return citations."""
        ...
```

## 5. Normalized Failure Taxonomy

The Knowledge subsystem categorizes failures into distinct operational types:

### A. Ingestion & Validation Failures
1. **`MISSING_PROVENANCE`:** Document rejected because URL, publication date, or source class is absent `[P§18]`.
2. **`UNVERIFIED_SOURCE`:** Document rejected because source identity or origin domain cannot be confirmed.
3. **`IRRELEVANT_CONTENT`:** Content discarded at the ingestion relevance gate before storage.
4. **`DUPLICATE_DOCUMENT`:** Content already indexed with identical provenance hash.

### B. Index & Storage Failures
5. **`EMBEDDING_GENERATION_FAILED`:** LLM Gateway failed to produce dense vector representation.
6. **`STORE_CORRUPTED`:** Index storage in `.cv_agent/knowledge/` failed integrity check.
7. **`WORKSPACE_CONTAINMENT_BREACH`:** Storage path resolution pointed outside project workspace `[D-013]`.

### C. Retrieval & Ranking Failures
8. **`ZERO_MATCHES`:** Query produced zero chunks meeting minimum similarity threshold.
9. **`STALE_CONTEXT_WARNING`:** All retrieved matches exceed their topic staleness horizon.
10. **`INSUFFICIENT_EVIDENCE_WEIGHT`:** Matches found but rejected because they fail the query's minimum evidence threshold (e.g. only professional posts found when high-evidence documentation was required).

## 6. Alternatives Considered

| Alternative | Evidence For | Evidence Against | Why Not Chosen |
|---|---|---|---|
| **Relying solely on LLM parametric memory** | Zero storage overhead; no ingestion pipeline; simple. | Hallucinates library versions and APIs; static weights lag CV developments `[P§16]`. | Violates `[P§16]` and `docs/RESEARCH_POLICY.md`. |
| **Direct web search without credibility weighting** | Large volume of candidate answers; easy to query. | Professional posts and vendor blogs treated equally with official documentation and reproducible benchmarks; no verification. | Violates `[P§17]`, `[P§29.3]`, and `[P§31]`. |
| **Ingesting everything into a global multi-tenant vector database** | Single shared cache across projects. | Leaks proprietary project context; violates single-project workspace isolation `[D-013]`. | Incompatible with single-project workspace containment `[D-013]`. |
| **Merging Knowledge with Project Memory** | Single store for all information. | Mixes general CV literature with project experiment metrics; breaks immutable experiment ledger `[P§25]`, `[P§33]`. | Violates `[P§34]` layer boundaries and ADR-0004. |
| **Pure semantic dense search without lexical BM25** | Excellent conceptual matching. | Fails on exact technical strings, model tags (e.g., `yolov8x6`), and CUDA error codes. | Hybrid search is mandatory for technical CV precision. |

## 7. Consequences

### Positive
- **Grounded Technical Reasoning (`[P§16]`, `[P§19]`):** The agent reasons from current, verified documentation rather than obsolete training weights.
- **Evidence Hierarchy Enforced (`[P§17]`):** Professional posts and community anecdotes remain discovery signals; only high-evidence benchmarks and documentation justify architecture decisions.
- **Auditability & Provenance (`[P§18]`):** Every assertion made by reasoning can be traced to a specific URL, date, and author.
- **Strict Boundary Integrity (`[P§34]`):** RAG serves context to reasoning; it does not dictate orchestration, execute tools, or contaminate the experiment ledger.

### Negative / Costs
- **Ingestion Friction:** Documents missing dates or provenance cannot be indexed and are discarded.
- **Storage Overhead:** Requires maintaining local hybrid vector and BM25 indices under `.cv_agent/knowledge/`.
- **Latency:** Hybrid retrieval and re-ranking add latency to reasoning cycles.

## 8. Acceptance Criteria

1. **Mandatory Provenance Verification:** Attempting to ingest a `KnowledgeDocument` lacking a publication date, author/organization, or source class raises `MISSING_PROVENANCE` and rejects the item.
2. **Evidence Weighting Applied:** Retrieving items computes composite ranking that strictly multiplies semantic similarity by the declared `SourceClass` evidence weight.
3. **LinkedIn Signal Isolation:** Items categorized as `PROFESSIONAL_POST` receive an evidence weight $\le 0.2$ and are flagged as `signal_only` in retrieval responses.
4. **Topic Staleness Decay:** Chunks whose age exceeds their domain staleness horizon are assigned a penalized freshness factor and marked with `is_stale = True`.
5. **Single-Project Workspace Containment:** All knowledge storage, embeddings, and indices reside strictly within `.cv_agent/knowledge/` in the repository root `[D-013]`.
6. **Gateway Separation:** Embedding generation delegates exclusively to the LLM Gateway (`ADR-0002`); the Knowledge subsystem does not import vendor LLM SDKs directly.
7. **Memory Subsystem Separation:** The Knowledge subsystem does not write to `.cv_agent/memory/` or `experiments.sqlite` (ADR-0004).

## 9. References

- `[P§16]` External knowledge: persistent knowledge and live research
- `[P§17]` Evidence weighting and why LinkedIn matters as a signal, not evidence
- `[P§18]` Monitoring ecosystem sources and the 7-step research pipeline
- `[P§19]` RAG's role: RAG provides knowledge, LLM provides reasoning, Tools provide execution
- `[P§20]` LLM Gateway provider abstraction
- `[P§22]` MCP's role as standardized tool boundary
- `[P§25]` Experiment-driven development and reproducibility
- `[P§29.3]` Evidence over hype: quantitative comparison or no claim
- `[P§29.7]` Current knowledge: continuously update ecosystem understanding
- `[P§34]` Architecture boundary test: what does this own, and why not elsewhere?
- `docs/RESEARCH_POLICY.md` Authoritative research and evidence policy
- `ADR-0001` Capability Model
- `ADR-0002` LLM Gateway and Provider Abstraction
- `ADR-0003` Orchestration State Machine, Checkpointing, and Approvals
- `ADR-0004` Project Memory and Experiment Ledger Persistence
- `ADR-0005` Tools and MCP Execution Boundary
- `D-013` Single-project workspace containment
