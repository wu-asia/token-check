"""Qt system-tray presentation for snapshots and notification messages."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon, QWidget

from monitor.notification_manager import UsageNotification
from monitor.usage_model import UsageSnapshot


class TrayController:
    def __init__(
        self,
        window: QWidget,
        *,
        on_open: Callable[[], None],
        on_refresh: Callable[[], None],
        on_pause_changed: Callable[[bool], None],
        on_settings: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        icon: QIcon = window.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(icon, window)
        self.menu = QMenu(window)
        self.open_action = self.menu.addAction("Open")
        self.refresh_action = self.menu.addAction("Refresh Now")
        self.pause_action = self.menu.addAction("Pause Auto Refresh")
        self.pause_action.setCheckable(True)
        self.settings_action = self.menu.addAction("Settings")
        self.menu.addSeparator()
        self.exit_action = self.menu.addAction("Exit")
        self.tray.setContextMenu(self.menu)
        self.tray.setToolTip("Codex Usage\n5h: N/A\nWeekly: N/A")

        self.open_action.triggered.connect(on_open)
        self.refresh_action.triggered.connect(on_refresh)
        self.pause_action.toggled.connect(on_pause_changed)
        self.settings_action.triggered.connect(on_settings)
        self.exit_action.triggered.connect(on_exit)

    def show(self) -> None:
        self.tray.show()

    def hide(self) -> None:
        self.tray.hide()

    def set_paused(self, paused: bool) -> None:
        self.pause_action.blockSignals(True)
        self.pause_action.setChecked(paused)
        self.pause_action.blockSignals(False)

    def update_snapshot(self, snapshot: UsageSnapshot) -> None:
        five = f"{snapshot.five_hour_remaining}%" if snapshot.five_hour_remaining is not None else "N/A"
        weekly = f"{snapshot.weekly_remaining}%" if snapshot.weekly_remaining is not None else "N/A"
        self.tray.setToolTip(f"Codex Usage\n5h: {five} remaining\nWeekly: {weekly} remaining")

    def notify(self, notification: UsageNotification) -> None:
        self.tray.showMessage(
            notification.title,
            notification.message,
            QSystemTrayIcon.MessageIcon.Information,
            10_000,
        )

    @staticmethod
    def quit_application() -> None:
        QApplication.quit()
