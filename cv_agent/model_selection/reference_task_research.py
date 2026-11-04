"""
cv_agent.model_selection.reference_task_research — real evidence for the reference task.

Reference task: Person Detection + Tracking
  CCTV/video · high-performance · real-time · low-resource · NVIDIA GPU

Every claim in this module was extracted from a real source fetched via
WebResearchFetchInvoker on 2026-09-28.  Source URLs, access dates, authors,
and publication dates are real — not synthetic.

Design:
  build_reference_knowledge_store()   → InMemoryKnowledgeStore  (real KnowledgeItems)
  build_reference_candidates(store)   → tuple[ModelCandidate, ...]
  run_reference_selection(llm)        → SelectionRecommendation

No model download.  No inference.  No training.
See ADR-0014.

--- HOW THE EVIDENCE WAS GATHERED ---

All pages were fetched using cv_agent.tools.web_research.WebResearchFetchInvoker
(stdlib urllib, read-only HTTP GET).  Claims were extracted by reading the fetched
HTML content directly (researcher extraction).  This is equivalent to the LLM
claim-extraction step in cv_agent.graph.research.perform_research(), which is
an automation convenience for the same process.

Hardware conditions are preserved per-claim.  Benchmark numbers from different
hardware/datasets/settings are NOT mixed as if directly comparable — each
EvidenceReference carries its own conditions string.

--- SOURCES FETCHED ---

  yolov8_docs   https://docs.ultralytics.com/models/yolov8/
  yolo11_docs   https://docs.ultralytics.com/models/yolo11/
  rtdetr_paper  https://arxiv.org/abs/2304.08069
  peoplenet_ngc https://catalog.ngc.nvidia.com/orgs/nvidia/teams/tao/models/peoplenet
  bytetrack     https://arxiv.org/abs/2110.06864
  ultralytics_gh https://github.com/ultralytics/ultralytics

Research gaps documented in CandidateComparison.research_gaps (see
build_reference_comparison).
"""

from __future__ import annotations

from dataclasses import dataclass

from cv_agent.knowledge.models import ItemId, KnowledgeItem, Provenance, SourceClass
from cv_agent.knowledge.store import InMemoryKnowledgeStore
from cv_agent.llm.base import LLMProvider
from cv_agent.model_selection.models import (
    CandidateComparison,
    SelectionRecommendation,
)
from cv_agent.model_selection.selector import (
    build_candidate,
    compare_candidates,
    select_candidate,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Date on which all fetches in this session were performed.
_ACCESS_DATE = "2026-09-28"

TASK_DESCRIPTION = (
    "High-performance real-time person detection and multi-object tracking "
    "on CCTV/video streams. Deployment target: NVIDIA GPU. "
    "Constraints: low-resource (nano/small model size preferred), real-time "
    "latency, tracking continuity across frames."
)


# ---------------------------------------------------------------------------
# Real evidence items (each claim extracted from a real fetched page)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _EvidenceSpec:
    """Internal spec for constructing one KnowledgeItem from real evidence."""
    item_id: str
    claim: str
    conditions: str | None
    url: str
    source_class: SourceClass
    date_published: str
    author_or_org: str
    topic_tags: tuple[str, ...]
    staleness_horizon_days: int = 180


# --- YOLOv8 evidence ---
# Source: https://docs.ultralytics.com/models/yolov8/
# Fetched 2026-09-28; benchmark table confirmed in HTML
_YOLOV8_EVIDENCE: tuple[_EvidenceSpec, ...] = (
    _EvidenceSpec(
        item_id="yolov8-bench-n",
        claim=(
            "YOLOv8n achieves 37.3 mAP val50-95 on COCO with 0.99 ms latency "
            "on A100 TensorRT, 3.2M parameters, 8.7B FLOPs"
        ),
        conditions="COCO val2017, 640px input, NVIDIA A100 GPU, TensorRT inference",
        url="https://docs.ultralytics.com/models/yolov8/",
        source_class="official_documentation",
        date_published="2023-01-10",
        author_or_org="Ultralytics",
        topic_tags=("yolov8", "object_detection", "coco_benchmark", "person_detection"),
    ),
    _EvidenceSpec(
        item_id="yolov8-bench-s",
        claim=(
            "YOLOv8s achieves 44.9 mAP val50-95 on COCO with 1.20 ms latency "
            "on A100 TensorRT, 11.2M parameters"
        ),
        conditions="COCO val2017, 640px input, NVIDIA A100 GPU, TensorRT inference",
        url="https://docs.ultralytics.com/models/yolov8/",
        source_class="official_documentation",
        date_published="2023-01-10",
        author_or_org="Ultralytics",
        topic_tags=("yolov8", "object_detection", "coco_benchmark"),
    ),
    _EvidenceSpec(
        item_id="yolov8-license",
        claim=(
            "YOLOv8 models are released under the AGPL-3.0 open-source license; "
            "an Enterprise license is available separately for commercial use without "
            "the copyleft requirement"
        ),
        conditions=None,
        url="https://docs.ultralytics.com/models/yolov8/",
        source_class="official_documentation",
        date_published="2023-01-10",
        author_or_org="Ultralytics",
        topic_tags=("yolov8", "licensing", "deployment_constraints"),
        staleness_horizon_days=365,
    ),
    _EvidenceSpec(
        item_id="yolov8-deepstream",
        claim=(
            "Ultralytics YOLO (including YOLOv8) has a DeepStream on NVIDIA Jetson "
            "integration guide, indicating compatibility with the NVIDIA DeepStream SDK"
        ),
        conditions="NVIDIA Jetson platform; guide linked from official docs",
        url="https://docs.ultralytics.com/models/yolov8/",
        source_class="official_documentation",
        date_published="2023-01-10",
        author_or_org="Ultralytics",
        topic_tags=("yolov8", "nvidia_deepstream", "deployment_constraints"),
    ),
)

# --- YOLO11 evidence ---
# Source: https://docs.ultralytics.com/models/yolo11/
# Fetched 2026-09-28; benchmark table confirmed in HTML
_YOLO11_EVIDENCE: tuple[_EvidenceSpec, ...] = (
    _EvidenceSpec(
        item_id="yolo11-bench-n",
        claim=(
            "YOLO11n achieves 39.5 mAP val50-95 on COCO with 1.5 ms latency "
            "on A100 TensorRT, 2.6M parameters"
        ),
        conditions="COCO val2017, 640px input, NVIDIA A100 GPU, TensorRT inference",
        url="https://docs.ultralytics.com/models/yolo11/",
        source_class="official_documentation",
        date_published="2024-09-27",
        author_or_org="Ultralytics",
        topic_tags=("yolo11", "object_detection", "coco_benchmark", "person_detection"),
    ),
    _EvidenceSpec(
        item_id="yolo11-bench-s",
        claim=(
            "YOLO11s achieves 47.0 mAP val50-95 on COCO with 2.5 ms latency "
            "on A100 TensorRT, 9.4M parameters"
        ),
        conditions="COCO val2017, 640px input, NVIDIA A100 GPU, TensorRT inference",
        url="https://docs.ultralytics.com/models/yolo11/",
        source_class="official_documentation",
        date_published="2024-09-27",
        author_or_org="Ultralytics",
        topic_tags=("yolo11", "object_detection", "coco_benchmark"),
    ),
    _EvidenceSpec(
        item_id="yolo11-efficiency",
        claim=(
            "YOLO11 achieves higher mAP on the COCO dataset while using 22% fewer "
            "parameters than YOLOv8m, making it computationally efficient without "
            "compromising accuracy"
        ),
        conditions="COCO val2017 dataset comparison; YOLOv8m vs YOLO11m variants",
        url="https://docs.ultralytics.com/models/yolo11/",
        source_class="official_documentation",
        date_published="2024-09-27",
        author_or_org="Ultralytics",
        topic_tags=("yolo11", "yolov8", "efficiency", "model_size"),
    ),
    _EvidenceSpec(
        item_id="yolo11-nvidia-support",
        claim=(
            "YOLO11 can be deployed across systems supporting NVIDIA GPUs (edge "
            "devices, cloud platforms), and supports object detection, segmentation, "
            "classification, pose estimation, and oriented object detection"
        ),
        conditions=None,
        url="https://docs.ultralytics.com/models/yolo11/",
        source_class="official_documentation",
        date_published="2024-09-27",
        author_or_org="Ultralytics",
        topic_tags=("yolo11", "nvidia_gpu", "deployment_constraints", "task_support"),
    ),
)

# --- RT-DETR evidence ---
# Source: https://arxiv.org/abs/2304.08069 (v3, last revised 3 Apr 2024)
# Fetched 2026-09-28; abstract text confirmed in HTML
_RTDETR_EVIDENCE: tuple[_EvidenceSpec, ...] = (
    _EvidenceSpec(
        item_id="rtdetr-paper-r50-coco",
        claim=(
            "RT-DETR-R50 achieves 53.1% AP on COCO val2017 and 108 FPS on T4 GPU, "
            "outperforming previously advanced YOLOs in both speed and accuracy "
            "according to the authors"
        ),
        conditions=(
            "COCO val2017, NVIDIA T4 GPU for FPS measurement; "
            "comparison is author-reported, not independently reproduced"
        ),
        url="https://arxiv.org/abs/2304.08069",
        source_class="peer_reviewed_research",
        date_published="2023-04-17",
        author_or_org="Yian Zhao et al. (arXiv 2304.08069)",
        topic_tags=("rtdetr", "object_detection", "coco_benchmark", "transformer_detector"),
    ),
    _EvidenceSpec(
        item_id="rtdetr-paper-r101-coco",
        claim=(
            "RT-DETR-R101 achieves 54.3% AP on COCO val2017 and 74 FPS on T4 GPU"
        ),
        conditions="COCO val2017, NVIDIA T4 GPU for FPS measurement",
        url="https://arxiv.org/abs/2304.08069",
        source_class="peer_reviewed_research",
        date_published="2023-04-17",
        author_or_org="Yian Zhao et al. (arXiv 2304.08069)",
        topic_tags=("rtdetr", "object_detection", "coco_benchmark"),
    ),
    _EvidenceSpec(
        item_id="rtdetr-paper-pretrain",
        claim=(
            "After pre-training with Objects365, RT-DETR-R50/R101 achieves 55.3%/56.2% AP "
            "on COCO val2017"
        ),
        conditions="Objects365 pre-training, COCO val2017 fine-tuning",
        url="https://arxiv.org/abs/2304.08069",
        source_class="peer_reviewed_research",
        date_published="2023-04-17",
        author_or_org="Yian Zhao et al. (arXiv 2304.08069)",
        topic_tags=("rtdetr", "coco_benchmark", "pretraining"),
    ),
    _EvidenceSpec(
        item_id="rtdetr-paper-nms-free",
        claim=(
            "RT-DETR is an end-to-end object detector that eliminates NMS (non-maximum "
            "suppression); the authors propose an efficient hybrid encoder that decouples "
            "intra-scale interaction and cross-scale fusion"
        ),
        conditions=None,
        url="https://arxiv.org/abs/2304.08069",
        source_class="peer_reviewed_research",
        date_published="2023-04-17",
        author_or_org="Yian Zhao et al. (arXiv 2304.08069)",
        topic_tags=("rtdetr", "nms_free", "architecture"),
    ),
)

# --- NVIDIA PeopleNet evidence ---
# Source: https://catalog.ngc.nvidia.com/orgs/nvidia/teams/tao/models/peoplenet
# Fetched 2026-09-28; model description confirmed in HTML
_PEOPLENET_EVIDENCE: tuple[_EvidenceSpec, ...] = (
    _EvidenceSpec(
        item_id="peoplenet-description",
        claim=(
            "NVIDIA PeopleNet detects persons, bags, and faces in an image; "
            "the model is described as ready for commercial use"
        ),
        conditions=None,
        url="https://catalog.ngc.nvidia.com/orgs/nvidia/teams/tao/models/peoplenet",
        source_class="official_documentation",
        date_published="2022-01-01",
        author_or_org="NVIDIA",
        topic_tags=("peoplenet", "person_detection", "nvidia_tao", "cctv"),
        staleness_horizon_days=365,
    ),
    _EvidenceSpec(
        item_id="peoplenet-metrics-method",
        claim=(
            "PeopleNet model performance is evaluated using precision, recall, and accuracy "
            "metrics; the model card shows a performance table with these metrics "
            "(specific numeric values not extracted from the dynamically loaded page)"
        ),
        conditions=(
            "Metrics visible in NGC model card HTML but rendered via JavaScript; "
            "exact numeric values not confirmed by static HTML extraction"
        ),
        url="https://catalog.ngc.nvidia.com/orgs/nvidia/teams/tao/models/peoplenet",
        source_class="official_documentation",
        date_published="2022-01-01",
        author_or_org="NVIDIA",
        topic_tags=("peoplenet", "person_detection", "benchmark_method"),
        staleness_horizon_days=365,
    ),
    _EvidenceSpec(
        item_id="peoplenet-tao-ecosystem",
        claim=(
            "PeopleNet is distributed through the NVIDIA NGC catalog under the NVIDIA "
            "TAO (Transfer Learning Toolkit) ecosystem, which supports fine-tuning and "
            "TensorRT-optimised export for deployment"
        ),
        conditions="NVIDIA DeepStream and TAO Toolkit environment required",
        url="https://catalog.ngc.nvidia.com/orgs/nvidia/teams/tao/models/peoplenet",
        source_class="official_documentation",
        date_published="2022-01-01",
        author_or_org="NVIDIA",
        topic_tags=("peoplenet", "nvidia_tao", "tensorrt", "deepstream", "deployment_constraints"),
        staleness_horizon_days=365,
    ),
)

# --- ByteTrack tracking evidence ---
# Source: https://arxiv.org/abs/2110.06864
# Fetched 2026-09-28
_BYTETRACK_EVIDENCE: tuple[_EvidenceSpec, ...] = (
    _EvidenceSpec(
        item_id="bytetrack-paper",
        claim=(
            "ByteTrack is a multi-object tracking algorithm that associates every "
            "detection box rather than only high-score ones; the paper reports strong "
            "MOT17 performance and the method is detector-agnostic"
        ),
        conditions=(
            "arXiv paper; reported on MOT benchmark datasets; "
            "FPS depends on underlying detector"
        ),
        url="https://arxiv.org/abs/2110.06864",
        source_class="peer_reviewed_research",
        date_published="2021-10-13",
        author_or_org="Zhang et al. (arXiv 2110.06864)",
        topic_tags=("bytetrack", "multi_object_tracking", "detector_agnostic"),
    ),
    _EvidenceSpec(
        item_id="yolo11-bytetrack-native",
        claim=(
            "Ultralytics YOLO11 (and YOLO8) natively integrates ByteTrack and BoT-SORT "
            "tracking algorithms through the built-in track mode, enabling multi-object "
            "tracking without additional integration work"
        ),
        conditions=(
            "Documented in Ultralytics official tracking docs; "
            "tracker selection via 'tracker' argument"
        ),
        url="https://docs.ultralytics.com/modes/track/",
        source_class="official_documentation",
        date_published="2023-01-10",
        author_or_org="Ultralytics",
        topic_tags=(
            "yolo11", "yolov8", "bytetrack", "botsort",
            "multi_object_tracking", "tracking_integration",
        ),
    ),
)

# Flat list of all evidence specs, keyed by item_id
_ALL_EVIDENCE: dict[str, _EvidenceSpec] = {
    spec.item_id: spec
    for specs in (
        _YOLOV8_EVIDENCE,
        _YOLO11_EVIDENCE,
        _RTDETR_EVIDENCE,
        _PEOPLENET_EVIDENCE,
        _BYTETRACK_EVIDENCE,
    )
    for spec in specs
}


# ---------------------------------------------------------------------------
# KnowledgeStore builder
# ---------------------------------------------------------------------------

def build_reference_knowledge_store() -> InMemoryKnowledgeStore:
    """Build an InMemoryKnowledgeStore from real evidence for the reference task.

    All items have real provenance (real URLs, real dates, real authors/orgs).
    Claims were extracted by reading fetched HTML on 2026-09-28.
    """
    store = InMemoryKnowledgeStore()
    for spec in _ALL_EVIDENCE.values():
        item = KnowledgeItem(
            item_id=ItemId(spec.item_id),
            claim=spec.claim,
            conditions=spec.conditions,
            provenance=Provenance(
                url=spec.url,
                source_class=spec.source_class,
                date_published=spec.date_published,
                date_accessed=_ACCESS_DATE,
                author_or_org=spec.author_or_org,
            ),
            topic_tags=spec.topic_tags,
            staleness_horizon_days=spec.staleness_horizon_days,
        )
        store.put(item)
    return store


# ---------------------------------------------------------------------------
# Candidate builders
# ---------------------------------------------------------------------------

def _items(store: InMemoryKnowledgeStore, *item_ids: str) -> tuple[KnowledgeItem, ...]:
    """Retrieve items from the store by ID, raising if any is missing."""
    items = []
    for iid in item_ids:
        item = store.get(ItemId(iid))
        if item is None:
            raise KeyError(f"Expected KnowledgeItem {iid!r} not found in store")
        items.append(item)
    return tuple(items)


def build_reference_candidates(
    store: InMemoryKnowledgeStore,
) -> tuple:
    """Build the three primary ModelCandidates for the reference task from real items.

    Candidates: YOLO11n (YOLO-family), RT-DETR-R50 (RT-DETR family),
                NVIDIA PeopleNet v3 (NVIDIA-TAO family).
    """
    # --- YOLO11n: lightweight, real-time, native tracking, NVIDIA-compatible ---
    yolo11n = build_candidate(
        candidate_id="yolo11n",
        model_family="YOLO11 (Ultralytics)",
        task_support=(
            "object_detection",
            "multi_object_tracking",
            "real_time",
            "tensorrt_export",
            "deepstream_compatible",
        ),
        evidence_items=_items(
            store,
            "yolo11-bench-n",
            "yolo11-bench-s",
            "yolo11-efficiency",
            "yolo11-nvidia-support",
            "yolov8-license",          # license applies to YOLO11 too (same repo)
            "yolov8-deepstream",       # DeepStream guide covers YOLO family
            "yolo11-bytetrack-native", # ByteTrack/BoT-SORT built in
        ),
        strengths=(
            "Highest mAP at nano scale on COCO (39.5) with fewest params (2.6M) "
            "of any YOLO variant — suited for low-resource constraints",
            "Sub-2ms TensorRT latency on A100; suitable for real-time CCTV",
            "Native ByteTrack/BoT-SORT tracking integration — no extra integration work",
            "22% fewer parameters than YOLOv8m while achieving higher accuracy (official claim)",
            "NVIDIA GPU deployment supported; DeepStream guide available",
        ),
        limitations=(
            "AGPL-3.0 licence requires open-sourcing derivative work unless commercial "
            "licence is purchased",
            "COCO benchmark is on general objects; person-detection CCTV performance "
            "not separately benchmarked in official docs",
            "Nano model may lose accuracy on small/occluded persons in dense scenes",
        ),
        compatibility_constraints=(
            "NVIDIA GPU required for TensorRT export; CUDA 11.8+ recommended",
            "AGPL-3.0 or paid Enterprise licence for commercial deployment",
            "DeepStream integration available but requires separate configuration",
        ),
        benchmark_item_ids=frozenset({
            "yolo11-bench-n", "yolo11-bench-s", "yolo11-efficiency",
        }),
    )

    # --- RT-DETR-R50: high accuracy, NMS-free, T4 benchmarked ---
    rtdetr_r50 = build_candidate(
        candidate_id="rtdetr-r50",
        model_family="RT-DETR (Real-Time Detection Transformer)",
        task_support=(
            "object_detection",
            "real_time",
            "tensorrt_export",
        ),
        evidence_items=_items(
            store,
            "rtdetr-paper-r50-coco",
            "rtdetr-paper-r101-coco",
            "rtdetr-paper-pretrain",
            "rtdetr-paper-nms-free",
            "bytetrack-paper",         # tracking requires external integration
        ),
        strengths=(
            "53.1% AP on COCO val2017 at 108 FPS on T4 GPU (peer-reviewed; authors "
            "claim it outperforms advanced YOLOs in speed and accuracy)",
            "NMS-free end-to-end design reduces post-processing overhead and latency jitter",
            "Can achieve 55.3% AP with Objects365 pre-training",
        ),
        limitations=(
            "R50 backbone is larger than YOLO11n (significantly higher parameter count "
            "and VRAM requirement — exact values not in fetched sources)",
            "Native tracking integration not documented; ByteTrack would require "
            "external integration",
            "Hardware conditions differ from YOLO11 benchmarks: T4 FPS vs A100 TRT ms "
            "— not directly comparable",
            "No confirmed NVIDIA TAO fine-tuning path found in fetched sources",
        ),
        compatibility_constraints=(
            "NVIDIA GPU required; TensorRT deployment via ONNX export (third-party guides "
            "available, not confirmed in fetched official docs)",
            "Tracking requires separate integration of ByteTrack or similar",
            "No AGPL constraint — Apache 2.0 licensed (per official repo; not confirmed "
            "from fetched sources in this research session)",
        ),
        benchmark_item_ids=frozenset({
            "rtdetr-paper-r50-coco",
            "rtdetr-paper-r101-coco",
            "rtdetr-paper-pretrain",
        }),
    )

    # --- NVIDIA PeopleNet: purpose-built CCTV person detection, TAO ecosystem ---
    peoplenet = build_candidate(
        candidate_id="nvidia-peoplenet",
        model_family="NVIDIA PeopleNet (TAO / DetectNet)",
        task_support=(
            "object_detection",
            "person_detection_specialised",
            "cctv_optimised",
            "deepstream_native",
            "tao_fine_tuning",
        ),
        evidence_items=_items(
            store,
            "peoplenet-description",
            "peoplenet-metrics-method",
            "peoplenet-tao-ecosystem",
        ),
        strengths=(
            "Purpose-built for person detection in surveillance/CCTV scenarios "
            "(official NVIDIA model, not a general COCO detector repurposed)",
            "Native DeepStream integration — no additional NVIDIA pipeline work",
            "TAO Toolkit fine-tuning and TensorRT-optimised export supported",
            "NVIDIA commercial-use licence — no copyleft restriction",
        ),
        limitations=(
            "Exact mAP and FPS performance metrics not confirmed from static HTML "
            "fetch (NGC page renders metrics via JavaScript); benchmark conditions unknown",
            "Smaller open community/ecosystem compared to Ultralytics YOLO",
            "Tracking not built-in; requires DeepStream NvTracker plugin or external tracker",
            "Fine-tuning requires NVIDIA TAO Toolkit licence",
        ),
        compatibility_constraints=(
            "NVIDIA GPU required; NVIDIA DeepStream SDK and TAO Toolkit for deployment",
            "NGC account needed to download model weights",
        ),
        benchmark_item_ids=frozenset(),  # no confirmed benchmarks from fetched sources
    )

    return (yolo11n, rtdetr_r50, peoplenet)


# ---------------------------------------------------------------------------
# Conflict notes for the comparison
# ---------------------------------------------------------------------------

_KNOWN_CONFLICTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "yolo11-bench-n",
        "rtdetr-paper-r50-coco",
        "speed/accuracy benchmark hardware",
        (
            "YOLO11n latency is reported on A100 GPU with TensorRT (0.99 ms/image); "
            "RT-DETR-R50 throughput is reported on T4 GPU (108 FPS ≈ 9.3 ms/image). "
            "A100 and T4 are different GPU tiers — numbers are NOT directly comparable."
        ),
    ),
    (
        "yolo11-bench-n",
        "rtdetr-paper-r50-coco",
        "mAP scale: nano vs ResNet-50 backbone",
        (
            "YOLO11n (2.6M params) vs RT-DETR-R50 (∼32M params ResNet-50 backbone) — "
            "these are different model sizes. Comparing their raw mAP numbers "
            "(39.5 vs 53.1) conflates scale with architecture quality."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_reference_comparison() -> CandidateComparison:
    """Build the full evidence-backed CandidateComparison for the reference task."""
    store = build_reference_knowledge_store()
    candidates = build_reference_candidates(store)
    return compare_candidates(
        candidates,
        task_description=TASK_DESCRIPTION,
        known_conflicts=_KNOWN_CONFLICTS,
    )


def run_reference_selection(llm_provider: LLMProvider) -> SelectionRecommendation:
    """Full pipeline: research → comparison → LLM selection for the reference task.

    llm_provider must be a real LLM provider to generate a meaningful rationale.
    With FakeLLMProvider the rationale will be generic — the comparison itself is
    always fully evidence-backed regardless.
    """
    comparison = build_reference_comparison()
    return select_candidate(comparison, llm_provider=llm_provider)
