"""Minimal PySide6 window backed exclusively by Phase-3 UsageReader data."""

from __future__ import annotations

import math
import sys
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from PySide6.QtCore import Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from monitor.notification_manager import NotificationManager
from monitor.history_database import HistoryDatabase
from monitor.history_recorder import HistoryRecorder
from monitor.refresh_worker import DEFAULT_REFRESH_INTERVAL_MS, RefreshController
from monitor.settings import SettingsStore
from monitor.usage_model import DataSource, SnapshotStatus, UsageSnapshot
from monitor.usage_reader import read_usage
from ui.tray import TrayController
from ui.history_window import HistoryWindow


class SnapshotRecorder(Protocol):
    """The narrow history dependency used by the UI."""

    def observe(self, snapshot: UsageSnapshot) -> None: ...

    def shutdown(self) -> None: ...


def _percent(value: int | None) -> str:
    return f"{value}%" if value is not None else "N/A"


def _reset_at(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "N/A"
    local_value = value.astimezone()
    return local_value.strftime("%H:%M") if local_value.date() == now.astimezone().date() else local_value.strftime("%Y-%m-%d %H:%M")


def _reset_in(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "N/A"
    total_minutes = math.ceil(max(0, int((value - now).total_seconds())) / 60)
    days, minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    parts = [f"{days}d"] if days else []
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def _state_label(snapshot: UsageSnapshot) -> str:
    if snapshot.status in {SnapshotStatus.UNAVAILABLE, SnapshotStatus.MALFORMED, SnapshotStatus.STALE}:
        return "Unable to read usage"
    if snapshot.source is DataSource.ESTIMATED:
        return "Estimated"
    if snapshot.verified:
        return "Verified"
    return "Available"


class UsageSection(QGroupBox):
    def __init__(self, title: str) -> None:
        super().__init__(title)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.used = QLabel("Used: N/A")
        self.remaining = QLabel("Remaining: N/A")
        self.reset_at = QLabel("Reset: N/A")
        self.reset_in = QLabel("Reset in: N/A")

        layout = QVBoxLayout(self)
        layout.addWidget(self.progress)
        for label in (self.used, self.remaining, self.reset_at, self.reset_in):
            layout.addWidget(label)

    def set_values(self, used: int | None, remaining: int | None, reset_at: datetime | None, now: datetime) -> None:
        if remaining is None:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.progress.setFormat("N/A")
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(remaining)
            self.progress.setFormat(f"{remaining}% remaining")
        self.used.setText(f"Used: {_percent(used)}")
        self.remaining.setText(f"Remaining: {_percent(remaining)}")
        self.reset_at.setText(f"Reset: {_reset_at(reset_at, now)}")
        self.reset_in.setText(f"Reset in: {_reset_in(reset_at, now)}")


class MainWindow(QMainWindow):
    """Resizable window with RefreshController, tray, and threshold alerts."""

    def __init__(
        self,
        reader: Callable[[], UsageSnapshot] = read_usage,
        refresh_interval_ms: int = DEFAULT_REFRESH_INTERVAL_MS,
        history_recorder: SnapshotRecorder | None = None,
    ) -> None:
        super().__init__()
        self._allow_exit = False
        self._history_window: HistoryWindow | None = None
        self._notifications = NotificationManager()
        # History has its own five-minute default timer and never drives UI refresh.
        self._history_recorder = history_recorder or HistoryRecorder(HistoryDatabase(), SettingsStore())
        self._refresh_controller = RefreshController(reader, refresh_interval_ms)
        self._refresh_controller.snapshot_ready.connect(self._apply_snapshot)
        self._refresh_controller.loading_changed.connect(self._set_loading)
        self._refresh_controller.paused_changed.connect(self._sync_pause_action)

        self.setWindowTitle("Codex Usage Monitor")
        self.setMinimumWidth(380)
        self.resize(460, 420)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(QLabel("Codex Usage Monitor"))
        self.five_hour = UsageSection("5-hour")
        self.weekly = UsageSection("Weekly")
        layout.addWidget(self.five_hour)
        layout.addWidget(self.weekly)

        details = QFormLayout()
        self.last_updated = QLabel("Loading")
        self.data_source = QLabel("Loading")
        self.status = QLabel("Loading")
        details.addRow("Last updated:", self.last_updated)
        details.addRow("Data source:", self.data_source)
        details.addRow("Status:", self.status)
        layout.addLayout(details)

        actions = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.history_button = QPushButton("History")
        self.history_button.clicked.connect(self.open_history)
        actions.addStretch()
        actions.addWidget(self.history_button)
        actions.addWidget(self.refresh_button)
        layout.addLayout(actions)
        self.setCentralWidget(central)

        self._tray = TrayController(
            self,
            on_open=self.open_window,
            on_refresh=self.refresh,
            on_pause_changed=lambda paused: self.set_auto_refresh_enabled(not paused),
            on_settings=self.show_settings,
            on_exit=self.exit_application,
        )
        self._tray.show()
        self._set_loading(True)
        self._refresh_controller.start()

    @property
    def auto_refresh_paused(self) -> bool:
        return self._refresh_controller.is_paused

    def set_auto_refresh_enabled(self, enabled: bool) -> None:
        self._refresh_controller.start() if enabled else self._refresh_controller.pause()

    def set_refresh_interval_seconds(self, seconds: int) -> None:
        self._refresh_controller.set_interval_ms(seconds * 1000)

    @Slot(bool)
    def _sync_pause_action(self, paused: bool) -> None:
        self._tray.set_paused(paused)

    @Slot(bool)
    def _set_loading(self, loading: bool) -> None:
        self.refresh_button.setEnabled(not loading)
        if loading:
            self.status.setText("Loading")

    @Slot()
    def refresh(self) -> None:
        self._refresh_controller.refresh_now()

    @Slot(object)
    def _apply_snapshot(self, snapshot: UsageSnapshot) -> None:
        now = datetime.now().astimezone()
        self.five_hour.set_values(snapshot.five_hour_used, snapshot.five_hour_remaining, snapshot.five_hour_reset_at, now)
        self.weekly.set_values(snapshot.weekly_used, snapshot.weekly_remaining, snapshot.weekly_reset_at, now)
        self.last_updated.setText(snapshot.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S"))
        self.data_source.setText(snapshot.source.value + (" (unverified)" if not snapshot.verified else ""))
        self.status.setText(_state_label(snapshot))
        self._history_recorder.observe(snapshot)
        self._tray.update_snapshot(snapshot)
        for notification in self._notifications.evaluate(snapshot):
            self._tray.notify(notification)

    @Slot()
    def open_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @Slot()
    def open_history(self) -> None:
        if self._history_window is None:
            self._history_window = HistoryWindow()
        self._history_window.show()
        self._history_window.raise_()
        self._history_window.activateWindow()

    @Slot()
    def show_settings(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Refresh Settings")
        layout = QFormLayout(dialog)
        interval = QSpinBox(dialog)
        interval.setRange(5, 3600)
        interval.setSuffix(" seconds")
        interval.setValue(self._refresh_controller.interval_ms // 1000)
        layout.addRow("Refresh interval:", interval)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_refresh_interval_seconds(interval.value())

    @Slot()
    def exit_application(self) -> None:
        self._allow_exit = True
        self.close()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._allow_exit:
            self.hide()
            event.ignore()
            return
        self._refresh_controller.shutdown()
        self._history_recorder.shutdown()
        self._tray.hide()
        event.accept()


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    window.refresh()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
