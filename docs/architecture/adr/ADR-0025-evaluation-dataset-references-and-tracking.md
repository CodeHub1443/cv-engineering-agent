# ADR-0025: Evaluation dataset references and tracking measurement

- **Status:** Proposed
- **Date:** 2026-11-16
- **Layer:** cross-cutting (datasets, experiments)
- **Canon:** `[P§12]`, `[P§15]`, `[P§25]`, `[P§32]`, `[P§34]`
- **Supersedes / Superseded by:** —
- **Issue:** #168

## 1. Context

D-043 (person detection and tracking on video, NVIDIA GPU) is unfinished: detection on video frames and tracking are both unmeasured `[P§12]`. The measured path assumes COCO: the wrapper, the recorder and `verify_run` hard-code COCO paths, counts and the "coco-val2017" name; `detection_metrics.py:127` silently drops label lines that are not 5 columns; `dataset_version` is a free string (`evaluation_records.py:656`). Labels are not fingerprinted (Q69), so two runs on different labels can look like-for-like `[P§25]`. Decisions D-122 to D-126 fix the video dataset policy, the baseline configuration and the tracking metrics. The evidence and sources are in `docs/experiments/D043-video-research.md`.

## 2. Responsibility `[P§34]`

- **This owns:** a typed, immutable reference to one evaluation dataset version, its label fingerprint, and the measurement contract (metric keys, frame ids, ignore rule) for tracking.
- **This does NOT own:**
  - dataset manifests, splits and leakage checks: ADR-0012 (`DatasetManifest`);
  - measuring and recording: experiments (ADR-0017);
  - format converters (MOTChallenge, VIRAT): dataset ingestion (issues I6, I7);
  - acceptance rules: ADR-0019 (issue I10).
- **Why not an existing component:** `DatasetManifest` is too heavy (it requires items, splits and a leakage check at construction, `manifest.py:75-123`), and experiments must not know which bytes make up a dataset. Dataset identity already belongs to datasets (ADR-0012 §3, key `(dataset_id, version)`). This adds one type and one function there, not a subsystem.

## 3. Decision

1. **`EvalDatasetRef`** is a frozen dataclass in `cv_agent/datasets/eval_ref.py` with `dataset_id: DatasetId` (a NewType of str) and `version` (the same key as ADR-0012 `[P§32]`), the layout (`images_dir`, `labels_dir`, `list_file`), `target_class`, optional `ignore_classes`, `expected_images`, `expected_instances`, `label_digest`, `spec_sha256` and `ledger_label`.
2. **Spec file.** One JSON spec per dataset at `<dataset_root>/eval_dataset_ref.json`, never in code. The loader rejects unknown or missing keys.
3. **`label_digest`** is sha256 over UTF-8 bytes. Images are ordered lexicographically by stem only. Each image contributes its stem, a newline, then its label lines sorted, whitespace-normalised and newline-joined. An empty label file contributes the stem only; a missing label file contributes the stem plus `<none>`. This closes the Q69 design; I3 implements it and I4 records and compares it.
   - **`spec_sha256`** is sha256 of the raw bytes of `eval_dataset_ref.json`. It is a field of `EvalDatasetRef` and **must be recorded in the run notes** `[P§25]`.
4. **COCO compatibility.** The COCO spec's `ledger_label` renders the existing string `coco-val2017-5k (val2017.txt sha256 {list_sha256})` byte for byte, so old ledger rows still pass `acceptance.py:173`. The digest and `spec_sha256` go in the notes. When both sides have a digest, the like-for-like gate also compares digests (I4).
5. **Boundary test `[P§34]`.** This adds a new import direction, **experiments → datasets**, and only to `cv_agent.datasets.eval_ref`. Today `cv_agent/experiments` imports nothing from datasets. datasets still never imports experiments (`_FORBIDDEN_PREFIXES` in `tests/test_datasets.py` is unchanged). A separate "video evaluation" subsystem is rejected: it would duplicate experiments.
6. **Frame ids.** `id = sequence_index × 10^6 + frame_number`. Both are 1-based, so **every video frame id is at least 10^6**, and a sequence holds at most 999,999 frames. Stems are zero-padded decimals, so the integer `image_id` check (`_check_predictions_shape`) and stem keying stay unchanged. A mapping file is kept for TrackEval.
7. **Ignore classes (detection scoring).** For MOT-format data, classes 7 (static person), 8 (distractor) and 12 (reflection) are neutral, and GT boxes with consider flag 0 are ignored; only the target class counts as GT. Target-class GT matching runs **first**; only the predictions left unmatched are then tested against ignore boxes at IoU ≥ 0.5 and, if matched, discarded (MOT16 paper §4.1.3, arXiv 1603.00831, accessed 2026-11-16). **Tracking metrics use TrackEval's own preprocessing, not this rule.**
8. **Fail-closed label parsing.** A label line whose column count differs from the one the spec declares raises; it is never skipped silently. I6 replaces the silent skip at `detection_metrics.py:127`.
9. **Tracking metric keys** in `val_metrics`: `tracking/HOTA`, `tracking/DetA`, `tracking/AssA`, `tracking/IDF1`, `tracking/MOTA`, `tracking/IDSW`, `tracking/Frag`. HOTA is primary (D-125). End-to-end FPS is a system metric; VRAM is recorded and compared as peak minus idle (Q71, D-125).
10. **TrackEval** (MIT) is the reference implementation `[P§15]`. It is pinned to a git commit as an optional `tracking` extra, installed on the Linux PC only, never imported by the core package or CI. Risk: older TrackEval uses `np.float`, which breaks on numpy ≥ 1.24; I8 verifies the pinned commit and falls back to `py-motmetrics` (IDF1, MOTA only) if needed.
11. **Trackers** run through Ultralytics with a pinned tracker yaml whose sha256 is recorded. ByteTrack is the baseline; its determinism is **untested until R3** (D-125). A tracker is its own variable and each candidate needs owner approval.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Reuse `DatasetManifest` as the reference | Same key | Needs items, splits and leakage at construction (`manifest.py:75-123`) | Too heavy |
| Keep `dataset_version` a free string | No code change | No label fingerprint; Q69 stays open | Not like-for-like safe |
| A "video evaluation" subsystem | Clean slate | Duplicates the experiments path | `[P§34]` |
| Reimplement HOTA/IDF1 | No dependency | TrackEval is the official HOTA implementation (MIT) | CLAUDE.md §3.9 |

## 5. Interface

```python
# module: cv_agent.datasets.eval_ref  (stubs; bodies raise NotImplementedError)
DatasetId = NewType("DatasetId", str)
class EvalDatasetRefError(ValueError): ...
@dataclass(frozen=True, kw_only=True)
class EvalDatasetRef:
    dataset_id: DatasetId; version: str
    images_dir: str; labels_dir: str; list_file: str
    target_class: int; expected_images: int; expected_instances: int
    ledger_label: str; spec_sha256: str
    ignore_classes: tuple[int, ...] = (); label_digest: str | None = None
    def render_ledger_label(self, *, list_sha256: str) -> str: ...
def load_eval_dataset_ref(spec_path: Path) -> EvalDatasetRef: ...
def compute_label_digest(ref: EvalDatasetRef, dataset_root: Path) -> str: ...
```

## 6. Consequences

- **Enables:** I3 to I10 (a dataset-agnostic measured path, video detection, tracking).
- **Makes harder:** nothing for COCO, which keeps its exact label (rule 4).
- **Costs:** one optional extra (I8); no GPU, no runtime cost in I1.
- **Blast radius if reversed:** the type has no callers until I4; reversal before then is deleting one module.

## 7. Acceptance test

- I1: `tests/test_eval_ref.py` (module imports, types frozen, `spec_sha256` frozen, defaults).
- I3: `test_eval_ref.py` also covers the digest (empty and missing label files, order independence, COCO label string).
- I6: a 6-column label file raises; unmatched predictions on ignore boxes are discarded after GT matching.
- I8: TrackEval on a synthetic fixture gives HOTA 1.0 for perfect tracking.

## 8. Revisit trigger

- TrackEval fails on the pinned numpy.
- The first non-MOT format needs another layout.
- A sequence exceeds 999,999 frames, or a dataset's native image ids collide with ids of 10^6 or more.
- VIRAT format verification (D-123) shows a layout this reference cannot describe.
- A determinism check at R3 shows ByteTrack is not deterministic (the acceptance rule then needs measured spread).
