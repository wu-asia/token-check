"""Non-blocking, timer-driven access to the Phase-3 usage reader."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from monitor.log_parser import unavailable_snapshot
from monitor.usage_model import UsageSnapshot
from monitor.usage_reader import read_usage


DEFAULT_REFRESH_INTERVAL_MS = 30_000


class RefreshWorker(QObject):
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


class RefreshController(QObject):
    """Owns a periodic timer and one in-flight worker at a time."""

    snapshot_ready = Signal(object)
    loading_changed = Signal(bool)
    paused_changed = Signal(bool)

    def __init__(
        self,
        reader: Callable[[], UsageSnapshot] = read_usage,
        interval_ms: int = DEFAULT_REFRESH_INTERVAL_MS,
    ) -> None:
        super().__init__()
        if interval_ms <= 0:
            raise ValueError("interval_ms must be positive")
        self._reader = reader
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.refresh_now)
        self._thread: QThread | None = None
        self._worker: RefreshWorker | None = None

    @property
    def interval_ms(self) -> int:
        return self._timer.interval()

    @property
    def is_paused(self) -> bool:
        return not self._timer.isActive()

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
            self.paused_changed.emit(False)

    def pause(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self.paused_changed.emit(True)

    def set_interval_ms(self, interval_ms: int) -> None:
        if interval_ms <= 0:
            raise ValueError("interval_ms must be positive")
        self._timer.setInterval(interval_ms)

    @Slot()
    def refresh_now(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        self.loading_changed.emit(True)
        self._thread = QThread(self)
        self._worker = RefreshWorker(self._reader)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.completed.connect(self._on_completed)
        self._worker.completed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._clear_worker)
        self._thread.start()

    @Slot(object)
    def _on_completed(self, snapshot: UsageSnapshot) -> None:
        self.snapshot_ready.emit(snapshot)
        self.loading_changed.emit(False)

    @Slot()
    def _clear_worker(self) -> None:
        self._worker = None
        self._thread = None

    def shutdown(self) -> None:
        self.pause()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
