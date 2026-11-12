"""
cv_agent.llm.clock — the gateway's time source.

Responsibility: give the governed provider a wall clock (timezone-aware UTC) and a
monotonic clock behind one protocol, so tests inject a fake and nothing in the gateway
reads the system clock directly. ADR-0020 §5.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now_utc(self) -> datetime:
        """The current time as a timezone-aware UTC datetime."""
        ...

    def monotonic(self) -> float:
        """Seconds from a monotonic origin; only differences are meaningful."""
        ...


class SystemClock:
    """The real clock."""

    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()
