"""Detect quota-window boundaries without deriving or inventing consumption."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from monitor.usage_model import UsageSnapshot


WindowName = Literal["five_hour", "weekly"]


@dataclass(frozen=True)
class WindowResetEvent:
    window: WindowName
    previous_reset_at: datetime
    current_reset_at: datetime


def detect_window_resets(previous: UsageSnapshot | None, current: UsageSnapshot) -> list[WindowResetEvent]:
    """Report only a changed authoritative reset timestamp; do not calculate deltas."""

    if previous is None:
        return []
    events: list[WindowResetEvent] = []
    for name, old_value, new_value in (
        ("five_hour", previous.five_hour_reset_at, current.five_hour_reset_at),
        ("weekly", previous.weekly_reset_at, current.weekly_reset_at),
    ):
        if old_value is not None and new_value is not None and old_value != new_value:
            events.append(WindowResetEvent(name, old_value, new_value))  # type: ignore[arg-type]
    return events
