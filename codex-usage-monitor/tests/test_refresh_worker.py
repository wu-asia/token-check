import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone
import unittest

from PySide6.QtWidgets import QApplication

from monitor.refresh_worker import RefreshController, RefreshWorker
from monitor.usage_model import DataSource, SnapshotStatus, UsageSnapshot


def snapshot() -> UsageSnapshot:
    return UsageSnapshot(
        timestamp=datetime.now(timezone.utc),
        five_hour_used=10, five_hour_remaining=90, five_hour_reset_at=None,
        weekly_used=20, weekly_remaining=80, weekly_reset_at=None,
        source=DataSource.OFFICIAL, verified=False,
        status=SnapshotStatus.PENDING_MANUAL_VERIFICATION,
    )


class RefreshControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_worker_returns_reader_snapshot(self) -> None:
        received: list[UsageSnapshot] = []
        worker = RefreshWorker(snapshot)
        worker.completed.connect(received.append)
        worker.run()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].five_hour_remaining, 90)

    def test_pause_resume_and_interval(self) -> None:
        controller = RefreshController(reader=snapshot, interval_ms=30_000)

        controller.start()
        self.assertFalse(controller.is_paused)
        controller.pause()
        self.assertTrue(controller.is_paused)
        controller.set_interval_ms(60_000)
        self.assertEqual(controller.interval_ms, 60_000)
        controller.start()
        self.assertFalse(controller.is_paused)
        controller.shutdown()
