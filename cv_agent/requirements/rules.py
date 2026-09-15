"""
cv_agent.requirements.rules — Extensible field-detection and task-hypothesis rules.

Deliberately data, not a decision tree in code: `FIELD_DETECTORS` and
`TASK_HYPOTHESIS_RULES` are plain lists of small dataclasses. Adding a new
requirement field or a new candidate CV task component for a new domain
(audio, LiDAR, whatever comes later) means appending one entry to one of
these lists — never adding a branch to `analyzer.py`'s control flow. This is
the same pattern `cv_agent.skills.resolver` already uses for capability
matching (keyword-overlap over structured data, not nested conditionals).

The field/task sets below are a starting point derived from
`docs/PROJECT.md` §5 (the DISCOVER/DEFINE questions) and §6 (the lifecycle),
not an exhaustive or permanent list.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldDetector:
    """Recognizes whether the user's request states something for one field."""

    field_name: str
    trigger_terms: tuple[str, ...]
    """If any of these terms appear in the request, the field is treated as
    KNOWN — with the matched sentence/fragment as its value, not a
    reinterpretation of it."""
    why_it_matters: str
    """Shown when this field is unknown — the engineering consequence, not a
    generic prompt."""


FIELD_DETECTORS: tuple[FieldDetector, ...] = (
    FieldDetector(
        field_name="operational_objective",
        trigger_terms=("detect", "recognize", "identify", "classify", "track", "monitor", "count", "measure"),
        why_it_matters=(
            "Without a stated objective the system cannot know what counts as "
            "a true positive — [P§5]."
        ),
    ),
    FieldDetector(
        field_name="environment_context",
        trigger_terms=("indoor", "outdoor", "factory", "prison", "warehouse", "street", "retail", "store", "office", "parking"),
        why_it_matters=(
            "Lighting, occlusion, and camera placement patterns differ enough "
            "between environments to change the architecture — [P§9]."
        ),
    ),
    FieldDetector(
        field_name="camera_data",
        trigger_terms=("camera", "cctv", "fps", "resolution", "rtsp", "footage", "video", "stream"),
        why_it_matters=(
            "Frame rate, resolution, and stream protocol bound which "
            "architectures and latencies are even achievable — [P§9]."
        ),
    ),
    FieldDetector(
        field_name="deployment_target",
        trigger_terms=("jetson", "edge", "server", "cloud", "gpu", "cpu", "deploy", "on-prem", "onprem"),
        why_it_matters=(
            "Accuracy without a named deployment target is not a complete "
            "engineering answer — [P§13]."
        ),
    ),
    FieldDetector(
        field_name="latency_requirement",
        trigger_terms=("real-time", "realtime", "latency", "fps target", "response time", "immediately", "live"),
        why_it_matters=(
            "A model can be accurate and still fail the product if it can't "
            "hit the required FPS/latency on the target hardware — [P§12]."
        ),
    ),
    FieldDetector(
        field_name="accuracy_requirement",
        trigger_terms=("recall", "precision", "accuracy", "false positive", "false negative", "miss rate"),
        why_it_matters=(
            "Security/safety applications usually need an explicit "
            "recall/false-positive tolerance stated before any model choice "
            "— [P§12], [P§29.3]."
        ),
    ),
    FieldDetector(
        field_name="data_availability",
        trigger_terms=("dataset", "labeled", "labelled", "annotated", "footage available", "existing data", "no data", "collect data"),
        why_it_matters=(
            "Model/architecture choice and the DATA stage plan both depend on "
            "how much labeled data already exists — [P§7], [P§26]."
        ),
    ),
)


@dataclass(frozen=True)
class TaskHypothesisRule:
    """One candidate CV task component and the terms that suggest it."""

    task_component: str
    trigger_terms: tuple[str, ...]
    rationale_template: str
    """May reference {term} for the specific trigger term that matched."""


TASK_HYPOTHESIS_RULES: tuple[TaskHypothesisRule, ...] = (
    TaskHypothesisRule(
        task_component="person_detection",
        trigger_terms=("person", "people", "human", "worker", "intruder", "escape", "theft", "trespass"),
        rationale_template=(
            "Request mentions '{term}', which almost always requires locating "
            "people in the frame before anything else can be reasoned about."
        ),
    ),
    TaskHypothesisRule(
        task_component="object_tracking",
        trigger_terms=("track", "tracking", "follow", "across cameras", "re-identification", "reid"),
        rationale_template=(
            "'{term}' implies identity needs to persist across frames, not just "
            "per-frame detection."
        ),
    ),
    TaskHypothesisRule(
        task_component="zone_roi_reasoning",
        trigger_terms=("zone", "boundary", "perimeter", "restricted area", "entry", "exit", "fence", "wall"),
        rationale_template=(
            "'{term}' suggests the event is defined by *where* something "
            "happens, which needs zone/ROI definition, not just detection."
        ),
    ),
    TaskHypothesisRule(
        task_component="temporal_event_reasoning",
        trigger_terms=("sequence", "over time", "duration", "loitering", "escape", "before", "after"),
        rationale_template=(
            "'{term}' implies the event is defined across a time window, not a "
            "single frame — needs temporal/event-state logic."
        ),
    ),
    TaskHypothesisRule(
        task_component="action_recognition",
        trigger_terms=("climb", "climbing", "fight", "fighting", "fall", "falling", "run", "running", "steal", "stealing"),
        rationale_template=(
            "'{term}' names a specific physical action, which is action "
            "recognition, not plain object detection."
        ),
    ),
    TaskHypothesisRule(
        task_component="pose_estimation",
        trigger_terms=("pose", "posture", "gesture", "body position", "skeleton"),
        rationale_template=(
            "'{term}' implies body-keypoint/pose information beyond a "
            "bounding box."
        ),
    ),
    TaskHypothesisRule(
        task_component="camera_geometry",
        trigger_terms=("multi-camera", "multiple cameras", "calibration", "ground plane", "homography", "3d", "distance"),
        rationale_template=(
            "'{term}' implies spatial reasoning across or within camera views, "
            "which needs calibration/geometry, not just per-frame CV."
        ),
    ),
    TaskHypothesisRule(
        task_component="anomaly_detection",
        trigger_terms=("anomaly", "unusual", "suspicious", "abnormal", "deviation"),
        rationale_template=(
            "'{term}' implies the event isn't a fixed, learnable class but a "
            "deviation from normal — an anomaly-detection framing, not "
            "closed-set classification."
        ),
    ),
)
