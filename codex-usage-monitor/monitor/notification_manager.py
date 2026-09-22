"""Notification threshold logic without Qt or Codex-reading dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from monitor.usage_model import SnapshotStatus, UsageSnapshot


@dataclass(frozen=True)
class UsageNotification:
    title: str
    message: str
    window: str
    threshold: int


class NotificationManager:
    """Emit at most one alert per window/threshold until that window resets."""

    THRESHOLDS = (30, 10)

    def __init__(self) -> None:
        self._notified: set[tuple[str, int]] = set()
        self._reset_at: dict[str, datetime] = {}

    def evaluate(self, snapshot: UsageSnapshot) -> list[UsageNotification]:
        if snapshot.status in {SnapshotStatus.UNAVAILABLE, SnapshotStatus.MALFORMED, SnapshotStatus.STALE}:
            return []
        alerts: list[UsageNotification] = []
        windows = (
            ("5h", snapshot.five_hour_remaining, snapshot.five_hour_reset_at),
            ("Weekly", snapshot.weekly_remaining, snapshot.weekly_reset_at),
        )
        for name, remaining, reset_at in windows:
            if remaining is None or reset_at is None:
                continue
            if self._reset_at.get(name) != reset_at:
                self._notified = {entry for entry in self._notified if entry[0] != name}
                self._reset_at[name] = reset_at
            for threshold in self.THRESHOLDS:
                key = (name, threshold)
                if remaining < threshold and key not in self._notified:
                    self._notified.add(key)
                    alerts.append(UsageNotification(
                        title="Codex Usage",
                        message=f"{name}: {remaining}% remaining (below {threshold}%)",
                        window=name,
                        threshold=threshold,
                    ))
        return alerts
