import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone
import unittest

from PySide6.QtWidgets import QApplication, QWidget

from monitor.usage_model import DataSource, SnapshotStatus, UsageSnapshot
from ui.tray import TrayController


class TrayControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = QWidget()
        self.events: list[object] = []
        self.tray = TrayController(
            self.window,
            on_open=lambda: self.events.append("open"),
            on_refresh=lambda: self.events.append("refresh"),
            on_pause_changed=lambda paused: self.events.append(paused),
            on_settings=lambda: self.events.append("settings"),
            on_exit=lambda: self.events.append("exit"),
        )

    def tearDown(self) -> None:
        self.tray.hide()
        self.window.close()

    def test_menu_and_tooltip(self) -> None:
        self.assertEqual(
            [action.text() for action in self.tray.menu.actions() if not action.isSeparator()],
            ["Open", "Refresh Now", "Pause Auto Refresh", "Settings", "Exit"],
        )
        item = UsageSnapshot(
            timestamp=datetime.now(timezone.utc),
            five_hour_used=34, five_hour_remaining=66, five_hour_reset_at=None,
            weekly_used=57, weekly_remaining=43, weekly_reset_at=None,
            source=DataSource.OFFICIAL, verified=False,
            status=SnapshotStatus.PENDING_MANUAL_VERIFICATION,
        )
        self.tray.update_snapshot(item)

        self.assertIn("5h: 66% remaining", self.tray.tray.toolTip())
        self.assertIn("Weekly: 43% remaining", self.tray.tray.toolTip())
