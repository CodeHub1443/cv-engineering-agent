"""
tests/test_evaluation_protocol.py — pins the evaluation-protocol decisions.

Q28 (accepted, D-067): standard mAP is computed at conf=0.001. The eval binding must default to it.
Q30 (OPEN): no operating point is chosen. The inference binding's 0.25 default is therefore
left unchanged, and this test pins it so that a change is a deliberate, reviewed act.
"""

from __future__ import annotations

import cv_agent.execution.jobs.runtimes.yolo_eval as yolo_eval
import cv_agent.execution.jobs.runtimes.yolo_inference as yolo_inference


def test_standard_map_protocol_threshold_is_0_001() -> None:
    # Q28 / D-067.
    assert yolo_eval.DEFAULT_CONF == 0.001


def test_inference_operating_point_default_is_unchanged_while_q30_open() -> None:
    # Q30 is OPEN. Changing this value is an owner decision, not a refactor.
    assert yolo_inference.DEFAULT_CONF == 0.25
