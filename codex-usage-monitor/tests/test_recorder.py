from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtWidgets import QApplication

from monitor.history_database import HistoryDatabase
from monitor.history_recorder import HistoryRecorder
from monitor.settings import RecordingSettings, SettingsStore
from monitor.usage_model import DataSource, SnapshotStatus, UsageSnapshot


def snapshot(minute: int = 0) -> UsageSnapshot:
    return UsageSnapshot(
        timestamp=datetime(2026, 9, 22, 10, minute, tzinfo=timezone.utc),
        five_hour_used=34, five_hour_remaining=66,
        five_hour_reset_at=datetime(2026, 9, 22, 12, tzinfo=timezone.utc),
        weekly_used=57, weekly_remaining=43,
        weekly_reset_at=datetime(2026, 9, 25, 12, tzinfo=timezone.utc),
        source=DataSource.OFFICIAL, verified=False,
        status=SnapshotStatus.PENDING_MANUAL_VERIFICATION,
    )


class HistoryRecorderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_first_snapshot_records_once_and_gui_refresh_does_not_write_each_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = HistoryDatabase(root / "data" / "usage_history.db")
            store = SettingsStore(root / "config" / "settings.json")
            store.save_recording_settings(RecordingSettings(enabled=True, interval_minutes=5))
            recorder = HistoryRecorder(database, store)
            try:
                recorder.observe(snapshot())
                self.assertEqual(database.count_samples(), 1)

                recorder.observe(snapshot(1))  # A 30-second GUI refresh must not itself write history.
                self.assertEqual(database.count_samples(), 1)

                recorder.record_due()  # The independent history cadence records the newest real snapshot.
                self.assertEqual(database.count_samples(), 2)
            finally:
                recorder.shutdown()

    def test_custom_interval_and_enable_state_persist_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = HistoryDatabase(root / "usage_history.db")
            store = SettingsStore(root / "settings.json")
            recorder = HistoryRecorder(database, store)
            try:
                self.assertEqual(recorder.settings.interval_minutes, 5)
                recorder.set_interval_minutes(7)
                self.assertEqual(recorder.interval_ms, 7 * 60 * 1000)
                self.assertEqual(store.load_recording_settings().interval_minutes, 7)

                recorder.set_enabled(False)
                self.assertFalse(recorder.settings.enabled)
                self.assertFalse(recorder._timer.isActive())
                recorder.set_enabled(True)
                self.assertTrue(store.load_recording_settings().enabled)
            finally:
                recorder.shutdown()

    def test_initialization_writes_documented_default_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SettingsStore(root / "config" / "settings.json")
            recorder = HistoryRecorder(HistoryDatabase(root / "usage_history.db"), store)
            try:
                self.assertEqual(store.load_recording_settings(), RecordingSettings())
                self.assertTrue(store.path.is_file())
            finally:
                recorder.shutdown()
