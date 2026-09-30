"""
cv_agent.diagnosis — measurable failure-mode evidence from evaluation artifacts.

Responsibility: read evaluation artifacts from disk (predictions.json +
YOLO-format GT labels), compute typed failure-mode statistics, and return them
as a DetectionEvidence dataclass.

This module is deterministic, read-only, and requires no LLM, no downloads,
and no model re-runs. See ADR-0015.
"""

from cv_agent.diagnosis.evidence_collector import collect_detection_evidence
from cv_agent.diagnosis.models import DetectionEvidence

__all__ = ["collect_detection_evidence", "DetectionEvidence"]
