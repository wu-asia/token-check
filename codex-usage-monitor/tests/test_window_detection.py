from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from monitor.usage_model import DataSource, SnapshotStatus, UsageSnapshot
from monitor.window_detection import detect_window_resets


def snapshot(remaining: int, reset_at: datetime) -> UsageSnapshot:
    return UsageSnapshot(
        timestamp=reset_at - timedelta(minutes=1),
        five_hour_used=100 - remaining, five_hour_remaining=remaining, five_hour_reset_at=reset_at,
        weekly_used=50, weekly_remaining=50,
        weekly_reset_at=datetime(2026, 9, 25, tzinfo=timezone.utc),
        source=DataSource.OFFICIAL, verified=False,
        status=SnapshotStatus.PENDING_MANUAL_VERIFICATION,
    )


class WindowDetectionTests(unittest.TestCase):
    def test_remaining_five_to_one_hundred_is_a_reset_event_not_negative_usage(self) -> None:
        old_reset = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
        new_reset = old_reset + timedelta(hours=5)

        events = detect_window_resets(snapshot(5, old_reset), snapshot(100, new_reset))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].window, "five_hour")
        self.assertEqual(events[0].previous_reset_at, old_reset)
        self.assertEqual(events[0].current_reset_at, new_reset)

    def test_same_reset_time_is_not_a_reset_event(self) -> None:
        reset_at = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
        self.assertEqual(detect_window_resets(snapshot(5, reset_at), snapshot(4, reset_at)), [])
