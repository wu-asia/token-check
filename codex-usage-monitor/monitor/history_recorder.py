"""Independent, timer-based history recording driven by already-read snapshots."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import QObject, QTimer

from monitor.history_database import HistoryDatabase
from monitor.settings import RecordingSettings, SettingsStore
from monitor.usage_model import UsageSnapshot
from monitor.window_detection import WindowResetEvent, detect_window_resets


class HistoryRecorder(QObject):
    """Records at startup and then on its own cadence, never on every GUI refresh."""

    def __init__(self, database: HistoryDatabase, settings_store: SettingsStore) -> None:
        super().__init__()
        self._database = database
        self._settings_store = settings_store
        self._settings = settings_store.load_recording_settings()
        # Ensure the documented default configuration exists; it contains no credentials.
        self._settings_store.save_recording_settings(self._settings)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.record_due)
        self._latest_snapshot: UsageSnapshot | None = None
        self._last_recorded_snapshot: UsageSnapshot | None = None
        self._record_on_next_snapshot = self._settings.enabled
        self.reset_events: list[WindowResetEvent] = []
        self.last_error: str | None = None
        self._apply_timer_state()

    @property
    def settings(self) -> RecordingSettings:
        return self._settings

    @property
    def interval_ms(self) -> int:
        return self._timer.interval()

    def observe(self, snapshot: UsageSnapshot) -> None:
        """Accept a real result from the GUI refresh controller; never calls a reader."""

        if self._latest_snapshot is not None:
            self.reset_events.extend(detect_window_resets(self._latest_snapshot, snapshot))
        self._latest_snapshot = snapshot
        if self._settings.enabled and self._record_on_next_snapshot:
            self._record(snapshot)
            self._record_on_next_snapshot = False

    def record_due(self) -> None:
        """Write only a newer snapshot, avoiding made-up points while the app is idle."""

        if not self._settings.enabled or self._latest_snapshot is None:
            return
        if self._last_recorded_snapshot is self._latest_snapshot:
            return
        self._record(self._latest_snapshot)

    def set_enabled(self, enabled: bool) -> None:
        self._settings = RecordingSettings(enabled=enabled, interval_minutes=self._settings.interval_minutes)
        self._settings_store.save_recording_settings(self._settings)
        self._record_on_next_snapshot = enabled
        self._apply_timer_state()
        if enabled and self._latest_snapshot is not None:
            self._record(self._latest_snapshot)
            self._record_on_next_snapshot = False

    def set_interval_minutes(self, interval_minutes: int) -> None:
        self._settings = RecordingSettings(enabled=self._settings.enabled, interval_minutes=interval_minutes)
        self._settings_store.save_recording_settings(self._settings)
        self._apply_timer_state()

    def shutdown(self) -> None:
        self._timer.stop()

    def _record(self, snapshot: UsageSnapshot) -> bool:
        try:
            self._database.record_snapshot(snapshot)
        except (OSError, sqlite3.Error) as error:
            self.last_error = str(error)
            return False
        self.last_error = None
        self._last_recorded_snapshot = snapshot
        return True

    def _apply_timer_state(self) -> None:
        self._timer.setInterval(self._settings.interval_minutes * 60 * 1000)
        if self._settings.enabled:
            self._timer.start()
        else:
            self._timer.stop()
