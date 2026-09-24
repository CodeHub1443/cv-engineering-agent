# ADR-0012: Dataset Core — storage-agnostic manifests, immutable versions, recorded splits, leakage checks

- **Status:** Accepted (owner authorization to implement ROADMAP Phase 5a, 2026-09-24; implemented same session)
- **Date:** 2026-09-24
- **Layer:** memory (dataset subsystem)
- **Canon:** `[P§26]`, `[P§25]`, `[P§29.5]`, `[P§34]`, `[P§35]`
- **Supersedes / Superseded by:** —
- **Issue:** #59

## 1. Context

`docs/DATA.md` (derived from `[P§26]`) defines the dataset contract: every dataset has
a version and a manifest (rule 1); annotations are versioned independently of images
(rule 2); splits are recorded, not recomputed (rule 3); dataset mutation is
approval-gated (rule 4); a fixed list of manifest fields; five leakage checks that
"run before every split is accepted", with the result "recorded in the manifest"; a
class-definition discipline; and a per-version dataset card. `docs/roadmap/ROADMAP.md`
Phase 5 ("Data & baseline") is not started; `docs/architecture/OVERVIEW.md`'s
Dataset-subsystem row is "Planned — no code", and its design sequence places
`[P§26]` at step 4, before tools and knowledge. ROADMAP called the ADR number "TBD"
because ADR-0009…0011 were assigned in implementation order (OVERVIEW's numbering
note); ADR-0012 is the next free number.

Two things are deliberately **not** decided here:

- **`OPEN_QUESTIONS.md` Q10** (DVC / Git LFS / external object store) is open.
  `docs/DATA.md` ("Versioning mechanism") lists what a backend must support
  (content-addressed identity, cheap diffing, lineage, exact retrieval) and says the
  backend is "to be decided". This ADR ships no backend.
- **`docs/DATA.md` does not define the per-item attributes** the leakage checks read
  (segment, camera, subject, annotation round, supplied hash, timestamp), nor how a
  check is told which goal applies. §3 records the minimal interpretation made to
  make each specified check executable — `[P§35]`: the gap is named, not hidden.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** the typed, immutable dataset manifest (a dataset version), its
  recorded splits, the deterministic leakage checks that gate a split's acceptance,
  and the `DatasetStore` contract for keeping manifests.
- **This does NOT own:**
  - blob/data-file storage and the versioning backend — Q10, undecided; a future
    backend implements `DatasetStore`;
  - computing perceptual hashes or reading pixels — hashes are supplied by the caller;
  - acquisition, annotation, augmentation — not built (`[P§26]` scope beyond this ADR);
  - training or baseline execution — Training subsystem (ROADMAP Phase 5b/6);
  - experiment records — `cv_agent.experiments` (ADR-0011), which is not touched;
  - approvals for dataset mutation — `docs/APPROVALS.md`. This package exposes no
    mutating operation, so nothing here is gated.
- **Why this does not belong to an existing component:** project memory
  (ADR-0004) stores mutable project understanding; the ledger (ADR-0011) records
  experiment rows; knowledge (ADR-0006) stores provenance-gated claims. None owns
  data versions or split integrity, and OVERVIEW already lists "Dataset subsystem"
  as its own responsibility row.

## 3. Decision

Add `cv_agent/datasets/`, a standard-library-only leaf package. **`DatasetManifest`
is the dataset version**, identified by `(dataset_id, version)` — the terms
`docs/DATA.md` uses ("Every dataset has a version and a manifest"; manifest fields
`dataset_id`, `version`). It is a frozen dataclass whose sequences are tuples; it
validates every field at construction and **refuses to exist unless its split passes
all leakage checks**. The leakage report is computed by the constructor, stored in
the manifest (`leakage_report`, `init=False`), and cannot be supplied by a caller.
A change (e.g. relabeling, DATA rule 2) is a new manifest with a new `version` and a
`lineage` pointing at its parent — never an update.

Fields follow `docs/DATA.md` verbatim: `dataset_id`, `version`, `created`, `sources`,
class definitions (`classes`, each with mandatory edge cases), `class_distribution`,
split membership (`splits` over `items`), `split_policy`, `annotation_version`,
`annotation_guideline_reference`, `known_issues`, `lineage`, `license`,
`collection_conditions` (cameras, sites, times, lighting), and the dataset `card`.
`n_items` is a derived property so it cannot disagree with `items`.

**Interpretations made where `docs/DATA.md` is silent** (each is a `[P§35]` gap
named, not an invention presented as canon):

| Gap | What was decided | Why |
|---|---|---|
| Item attributes | `DatasetItem`: `item_id` (opaque: id or content hash), `segment_id`, `camera_id`, `annotation_round`, optional `timestamp`, `subject_ids`, `perceptual_hash` | The minimum each specified check reads |
| Which goal applies | `SplitPolicy` declares `camera_goal`, `time_order`, `subject_isolation`, `allow_mixed_annotation_guidelines`, `max_hamming_distance` | DATA: "state which goal applies"; "not mixed silently"; subject check applies "for Re-ID or tracking tasks" |
| Annotation round → guideline | `AnnotationRound(round_id, guideline_ref)` list on the manifest | "labeled in one round with a different guideline" needs the mapping |
| Near-duplicate tolerance | Hamming distance on supplied hex hashes; default `0` (identical only) | DATA names a "perceptual-hash sweep" but no tolerance; a looser value is a recorded, explicit choice, not a default |
| Unverifiable input | Missing timestamp (when time order is declared), missing hash, `subject_ids` unknown (when isolation is required), hash width mismatch, mixed naive/aware timestamps → a finding, status `failed` | Fail closed; DATA requires the checks run before a split is accepted |
| Time boundary | `max(earlier) < min(later)` strictly; an equal instant is overlap | Ambiguity resolved conservatively |
| Not applicable | camera (`same_cameras`), subject (isolation off) reported as `not_applicable`, visibly | The recorded report shows what was and was not checked |

**Leakage checks** (`check_leakage`, pure, order-independent, findings sorted):

1. `temporal` — a video segment in more than one split; and, if `time_order` is
   declared, split time ranges must not overlap in the declared order.
2. `camera` — a camera in more than one split when the goal is generalizing to new cameras.
3. `subject` — a subject in more than one split when isolation is required.
4. `annotation_round` — items labeled under more than one guideline unless the policy
   explicitly allows mixing; undeclared rounds are a finding.
5. `near_duplicate` — items in different splits whose supplied hashes are within the
   declared Hamming threshold. Same-split duplicates are not leakage. No hash is
   ever computed.

**`DatasetStore`** is a `Protocol`: `put_manifest`, `get_manifest`, `list_versions`.
Contract: never overwrite an existing `(dataset_id, version)`; a `lineage` parent must
already be stored under the same `dataset_id`; a failed put changes nothing; `get`
returns `None` for an unknown key; `list_versions` is in storage order.
`InMemoryDatasetStore` is the reference implementation: instance-local state, not
durable, no path/file/database concept, no factory that would imply a backend default.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Choose a backend (DVC/LFS/object store) now | DATA lists backend requirements | Q10 is open and owner-scoped; ADR-0005/0006 shipped boundary-only for the same reason | Would silently decide Q10 |
| Compute perceptual hashes in-package | Enables a real sweep | Needs an image dependency and pixel access; explicitly excluded; changes the trust boundary | Hashes are supplied; a computing tool is a separate, later decision |
| Separate `DatasetVersion` and `DatasetManifest` classes | Mirrors "version and manifest" as two nouns | DATA's manifest fields *include* `version`; two types invite drift and a place to forge a report | One type; identity is `(dataset_id, version)` |
| Report attached after construction / caller-supplied | Lets callers keep leaky splits for inspection | A manifest could carry a forged or absent report | Constructor computes and enforces; `check_leakage()` is public for inspection without raising |
| Add `list_datasets()` / a registry | Convenient discovery | An unrequested registry is exactly the invention forbidden here; no requirement in DATA | Only per-dataset `list_versions` |
| Persist to SQLite like memory/ledger | Precedent (Q8, Q16) | Those were owner decisions; Q10 is not | Would pre-decide Q10 |

## 5. Interface

Public surface of `cv_agent.datasets` (see the package for signatures): value types
`ClassDefinition`, `ClassCount`, `Lineage`, `CollectionConditions`, `DatasetCard`,
`AnnotationRound`, `DatasetItem`, `DatasetSplit`, `SplitPolicy`; `DatasetManifest`
(`n_items`, `split_of()`, `leakage_report`); `check_leakage()`, `LeakageReport`,
`CheckResult`, `LeakageFinding`, `LeakageError`; `DatasetStore`, `DatasetStoreError`,
`InMemoryDatasetStore`.

## 6. Consequences

- **Enables:** Phase 5b (baseline) and later training can name an immutable,
  leakage-checked `(dataset_id, version)`; the ledger's `dataset_version` can later be
  cross-checked against a real manifest (ADR-0011 named that as awaiting this).
- **Makes harder:** every dataset needs a supplied hash per item and the attributes
  above — strict by design (fail closed); relaxing it is a deliberate later change.
- **Costs:** ~1,030 lines of source and ~790 of tests, no dependency, no runtime cost beyond O(n²) hash comparison
  across splits (acceptable for manifests; a backend may index later).
- **Migration / blast radius if reversed:** none — nothing imports the package.

## 7. Acceptance test

`tests/test_datasets.py`: valid and invalid manifests; frozen versions and a store that
rejects overwrite; recorded splits; a clean split passes; one deliberately leaky
synthetic fixture per check fails (and a maximally leaky fixture fails all five);
reports are identical for shuffled input; store round-trip, lineage rule and
fail-closed puts; structural tests that the package imports only the standard library
and itself (no other `cv_agent` layer, no third-party/image/backend module). 88 tests.

## 8. Revisit trigger

- Q10 is answered → add a backend module implementing `DatasetStore`; this ADR stays.
- A perceptual-hash producer is chosen → wire it *outside* this package; the check still
  takes supplied hashes.
- The owner decides the strict hash/attribute requirement is too heavy for a real
  dataset → relax deliberately, recorded here.
- The first real dataset shows `DatasetItem` needs another attribute for a check.
- `cv_agent.experiments` cross-validation of `dataset_version` is built (needs a decision
  on which layer owns the reference).
