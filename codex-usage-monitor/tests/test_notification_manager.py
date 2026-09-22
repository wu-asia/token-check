from datetime import datetime, timedelta, timezone
import unittest

from monitor.notification_manager import NotificationManager
from monitor.usage_model import DataSource, SnapshotStatus, UsageSnapshot


def snapshot(remaining: int, reset_at: datetime) -> UsageSnapshot:
    return UsageSnapshot(
        timestamp=datetime.now(timezone.utc),
        five_hour_used=100 - remaining,
        five_hour_remaining=remaining,
        five_hour_reset_at=reset_at,
        weekly_used=None,
        weekly_remaining=None,
        weekly_reset_at=None,
        source=DataSource.OFFICIAL,
        verified=False,
        status=SnapshotStatus.PENDING_MANUAL_VERIFICATION,
    )


class NotificationManagerTests(unittest.TestCase):
    def test_threshold_notified_once_per_window(self) -> None:
        manager = NotificationManager()
        reset = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)

        first = manager.evaluate(snapshot(29, reset))
        second = manager.evaluate(snapshot(29, reset))
        ten_percent = manager.evaluate(snapshot(9, reset))

        self.assertEqual([item.threshold for item in first], [30])
        self.assertEqual(second, [])
        self.assertEqual([item.threshold for item in ten_percent], [10])

    def test_reset_clears_threshold_notification_state(self) -> None:
        manager = NotificationManager()
        reset = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
        manager.evaluate(snapshot(9, reset))

        after_reset = manager.evaluate(snapshot(9, reset + timedelta(hours=5)))

        self.assertEqual([item.threshold for item in after_reset], [30, 10])
