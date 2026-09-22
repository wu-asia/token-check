from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest import TestCase
from unittest.mock import patch

import main
from monitor.usage_model import DataSource, SnapshotStatus, UsageSnapshot


def snapshot(**overrides: object) -> UsageSnapshot:
    values: dict[str, object] = {
        "timestamp": datetime(2026, 9, 22, 10, 25, 31, tzinfo=timezone.utc),
        "five_hour_used": 34,
        "five_hour_remaining": 66,
        "five_hour_reset_at": datetime(2026, 9, 22, 12, 43, tzinfo=timezone.utc),
        "weekly_used": 57,
        "weekly_remaining": 43,
        "weekly_reset_at": datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc),
        "source": DataSource.OFFICIAL,
        "verified": False,
        "status": SnapshotStatus.PENDING_MANUAL_VERIFICATION,
    }
    values.update(overrides)
    return UsageSnapshot(**values)  # type: ignore[arg-type]


class MainTests(TestCase):
    def test_status_renders_data_from_reader_snapshot(self) -> None:
        output = main.render_status(snapshot(), now=datetime(2026, 9, 22, 10, 25, tzinfo=timezone.utc))

        self.assertIn("Used:       34%", output)
        self.assertIn("Remaining:  43%", output)
        self.assertIn("Source:\nOfficial (unverified)", output)

    def test_unknown_values_render_na_not_zero_percent(self) -> None:
        output = main.render_status(
            snapshot(
                five_hour_used=None, five_hour_remaining=None, five_hour_reset_at=None,
                weekly_used=None, weekly_remaining=None, weekly_reset_at=None,
                source=DataSource.UNKNOWN, status=SnapshotStatus.UNAVAILABLE,
            ),
            now=datetime(2026, 9, 22, tzinfo=timezone.utc),
        )

        self.assertIn("Used:       N/A", output)
        self.assertIn("Reset in:   N/A", output)
        self.assertNotIn("0%", output)

    def test_reset_countdown_never_becomes_negative_across_midnight(self) -> None:
        now = datetime(2026, 9, 22, 23, 50, tzinfo=timezone.utc)

        self.assertEqual(main.format_reset_in(now + timedelta(minutes=25), now), "25m")
        self.assertEqual(main.format_reset_in(now - timedelta(minutes=1), now), "0m")
        self.assertEqual(main.format_reset_in(now + timedelta(days=3, hours=11), now), "3d 11h")

    def test_version_command(self) -> None:
        with patch("sys.stdout", new_callable=StringIO) as output:
            exit_code = main.main(["--version"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue().strip(), "Codex Usage Monitor 0.1.0")
