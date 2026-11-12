"""
cv_agent.llm.clock — the gateway's time source.

Responsibility: give the governed provider a wall clock (timezone-aware UTC) and a
monotonic clock behind one protocol, so tests inject a fake and nothing in the gateway
reads the system clock directly. ADR-0020 §5.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol

_OFFSET = re.compile(r"^([+-])(\d{2}):(\d{2})$")


def parse_utc_offset(text: str) -> timezone:
    """A fixed UTC offset written like ``+06:00``; ``ValueError`` for anything else."""
    match = _OFFSET.match(text)
    if match is None or int(match[2]) > 23 or int(match[3]) > 59:
        raise ValueError(f"UTC offset {text!r} must look like '+06:00'")
    delta = timedelta(hours=int(match[2]), minutes=int(match[3]))
    return timezone(-delta if match[1] == "-" else delta)


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
