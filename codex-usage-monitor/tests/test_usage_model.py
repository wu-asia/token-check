from datetime import datetime, timezone
import unittest

from monitor.usage_model import DataSource, SnapshotStatus, UsageSnapshot


class UsageSnapshotTests(unittest.TestCase):
    def test_zero_is_preserved_as_a_real_value(self) -> None:
        snapshot = UsageSnapshot(
            timestamp=datetime.now(timezone.utc),
            five_hour_used=0, five_hour_remaining=100, five_hour_reset_at=None,
            weekly_used=None, weekly_remaining=None, weekly_reset_at=None,
            source=DataSource.OFFICIAL, verified=False,
            status=SnapshotStatus.PENDING_MANUAL_VERIFICATION,
        )
        self.assertEqual(snapshot.five_hour_used, 0)
        self.assertIsNone(snapshot.weekly_used)

    def test_unknown_is_not_represented_by_an_invalid_percentage(self) -> None:
        with self.assertRaises(ValueError):
            UsageSnapshot(
                timestamp=datetime.now(timezone.utc),
                five_hour_used=-1, five_hour_remaining=None, five_hour_reset_at=None,
                weekly_used=None, weekly_remaining=None, weekly_reset_at=None,
                source=DataSource.UNKNOWN, verified=False, status=SnapshotStatus.UNAVAILABLE,
            )


if __name__ == "__main__":
    unittest.main()
