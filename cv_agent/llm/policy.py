"""
cv_agent.llm.policy — typed vocabulary for LLM routing and privacy (ADR-0020 §3 item 1, D-092).

Responsibility: name the task classes and data classes as enums so no free string stands in for
either ``[P§32]``, and hold the owner's default allow-set for hosted tiers. It holds no logic and
imports nothing from the gateway, so ``base`` and ``errors`` can both depend on it.
"""

from __future__ import annotations

from enum import Enum


class TaskClass(str, Enum):
    """What a call is for; slice G5 routes on it."""

    EXTRACTION = "extraction"
    SELECTION = "selection"
    NARRATIVE = "narrative"


class DataClass(str, Enum):
    """What a prompt contains; a call declares every class it carries."""

    PUBLIC_WEB = "public_web"
    PROJECT_METADATA = "project_metadata"
    PROJECT_DATA = "project_data"


# D-092 / ADR-0020 §3 item 7: hosted tiers receive public web content and project metadata only.
DEFAULT_HOSTED_ALLOWED: frozenset[DataClass] = frozenset({DataClass.PUBLIC_WEB, DataClass.PROJECT_METADATA})

# A request that declares nothing is treated as carrying the strictest class.
UNDECLARED_DATA_CLASSES: frozenset[DataClass] = frozenset({DataClass.PROJECT_DATA})
