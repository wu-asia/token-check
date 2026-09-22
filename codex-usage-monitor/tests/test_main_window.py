import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta, timezone
import unittest

from PySide6.QtWidgets import QApplication

from monitor.usage_model import DataSource, SnapshotStatus, UsageSnapshot
from monitor.refresh_worker import RefreshWorker
from ui.main_window import MainWindow


class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow(reader=lambda: self.snapshot())

    def tearDown(self) -> None:
        self.window._allow_exit = True
        self.window.close()

    @staticmethod
    def snapshot(**overrides: object) -> UsageSnapshot:
        values: dict[str, object] = {
            "timestamp": datetime(2026, 9, 22, 10, tzinfo=timezone.utc),
            "five_hour_used": 34,
            "five_hour_remaining": 66,
            "five_hour_reset_at": datetime(2026, 9, 22, 12, tzinfo=timezone.utc),
            "weekly_used": 57,
            "weekly_remaining": 43,
            "weekly_reset_at": datetime(2026, 9, 25, 12, tzinfo=timezone.utc),
            "source": DataSource.OFFICIAL,
            "verified": False,
            "status": SnapshotStatus.PENDING_MANUAL_VERIFICATION,
        }
        values.update(overrides)
        return UsageSnapshot(**values)  # type: ignore[arg-type]

    def test_available_snapshot_updates_progress_and_labels(self) -> None:
        self.window._apply_snapshot(self.snapshot())

        self.assertEqual(self.window.five_hour.progress.value(), 66)
        self.assertEqual(self.window.five_hour.progress.format(), "66% remaining")
        self.assertEqual(self.window.status.text(), "Available")

    def test_unknown_snapshot_shows_na_not_zero_percent(self) -> None:
        self.window._apply_snapshot(self.snapshot(
            five_hour_used=None, five_hour_remaining=None, five_hour_reset_at=None,
            weekly_used=None, weekly_remaining=None, weekly_reset_at=None,
            source=DataSource.UNKNOWN, status=SnapshotStatus.UNAVAILABLE,
        ))

        self.assertEqual(self.window.five_hour.progress.format(), "N/A")
        self.assertEqual(self.window.five_hour.used.text(), "Used: N/A")
        self.assertEqual(self.window.status.text(), "Unable to read usage")

    def test_reader_failure_produces_unavailable_snapshot(self) -> None:
        received: list[UsageSnapshot] = []

        def failing_reader() -> UsageSnapshot:
            raise RuntimeError("unavailable")

        worker = RefreshWorker(failing_reader)
        worker.completed.connect(received.append)
        worker.run()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].status, SnapshotStatus.UNAVAILABLE)
        self.assertIsNone(received[0].five_hour_used)

    def test_window_can_be_resized(self) -> None:
        self.window.resize(720, 520)

        self.assertEqual(self.window.size().width(), 720)
        self.assertEqual(self.window.size().height(), 520)

    def test_threshold_notifications_rearm_after_reset(self) -> None:
        notified: list[object] = []
        self.window._tray.notify = notified.append  # type: ignore[method-assign]
        reset = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)

        self.window._apply_snapshot(self.snapshot(
            five_hour_used=71, five_hour_remaining=29, five_hour_reset_at=reset,
        ))
        self.window._apply_snapshot(self.snapshot(
            five_hour_used=91, five_hour_remaining=9, five_hour_reset_at=reset,
        ))
        self.window._apply_snapshot(self.snapshot(
            five_hour_used=91, five_hour_remaining=9, five_hour_reset_at=reset + timedelta(hours=5),
        ))

        self.assertEqual([item.threshold for item in notified], [30, 10, 30, 10])


if __name__ == "__main__":
    unittest.main()
