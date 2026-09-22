"""Minimal PySide6 window backed exclusively by Phase-3 UsageReader data."""

from __future__ import annotations

import math
import sys
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from monitor.log_parser import unavailable_snapshot
from monitor.usage_model import DataSource, SnapshotStatus, UsageSnapshot
from monitor.usage_reader import read_usage


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


class RefreshWorker(QObject):
    """Runs the existing reader away from the Qt event loop."""

    completed = Signal(object)

    def __init__(self, reader: Callable[[], UsageSnapshot]) -> None:
        super().__init__()
        self._reader = reader

    @Slot()
    def run(self) -> None:
        try:
            snapshot = self._reader()
        except Exception:
            snapshot = unavailable_snapshot(datetime.now().astimezone())
        self.completed.emit(snapshot)


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
            # Do not display an empty numeric bar as a real 0% remaining value.
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
    """A resizable main window with manual refresh and optional refresh timer."""

    def __init__(self, reader: Callable[[], UsageSnapshot] = read_usage, refresh_interval_ms: int = 30_000) -> None:
        super().__init__()
        self._reader = reader
        self._thread: QThread | None = None
        self._worker: RefreshWorker | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(refresh_interval_ms)
        self._timer.timeout.connect(self.refresh)

        self.setWindowTitle("Codex Usage Monitor")
        self.setMinimumWidth(380)
        self.resize(460, 420)

        central = QWidget()
        layout = QVBoxLayout(central)
        title = QLabel("Codex Usage Monitor")
        layout.addWidget(title)
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
        actions.addStretch()
        actions.addWidget(self.refresh_button)
        layout.addLayout(actions)
        self.setCentralWidget(central)
        self._set_loading()

    def set_auto_refresh_enabled(self, enabled: bool) -> None:
        """Reserved auto-refresh interface; disabled by default."""
        self._timer.start() if enabled else self._timer.stop()

    def _set_loading(self) -> None:
        self.refresh_button.setEnabled(False)
        self.status.setText("Loading")

    @Slot()
    def refresh(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        self._set_loading()
        self._thread = QThread(self)
        self._worker = RefreshWorker(self._reader)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.completed.connect(self._apply_snapshot)
        self._worker.completed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._clear_worker)
        self._thread.start()

    @Slot(object)
    def _apply_snapshot(self, snapshot: UsageSnapshot) -> None:
        now = datetime.now().astimezone()
        self.five_hour.set_values(
            snapshot.five_hour_used, snapshot.five_hour_remaining, snapshot.five_hour_reset_at, now
        )
        self.weekly.set_values(snapshot.weekly_used, snapshot.weekly_remaining, snapshot.weekly_reset_at, now)
        self.last_updated.setText(snapshot.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S"))
        source = snapshot.source.value + (" (unverified)" if not snapshot.verified else "")
        self.data_source.setText(source)
        self.status.setText(_state_label(snapshot))
        self.refresh_button.setEnabled(True)

    @Slot()
    def _clear_worker(self) -> None:
        self._worker = None
        self._thread = None


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    window.refresh()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
