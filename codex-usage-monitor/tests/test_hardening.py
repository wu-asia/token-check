from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtWidgets import QApplication

from monitor.history_database import HistoryDatabase
from monitor.history_recorder import HistoryRecorder
from monitor.settings import SettingsStore
from monitor.usage_model import DataSource, SnapshotStatus, UsageSnapshot


class HardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def snapshot() -> UsageSnapshot:
        return UsageSnapshot(datetime.now(timezone.utc), 10, 90, None, 20, 80, None, DataSource.UNKNOWN, False, SnapshotStatus.UNAVAILABLE)

    def test_corrupt_database_does_not_crash_recorder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage_history.db"
            path.write_bytes(b"not a sqlite database")
            recorder = HistoryRecorder(HistoryDatabase(path), SettingsStore(Path(directory) / "settings.json"))
            try:
                recorder.observe(self.snapshot())
                self.assertIsNotNone(recorder.last_error)
            finally:
                recorder.shutdown()

    def test_locked_database_does_not_crash_recorder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage_history.db"
            database = HistoryDatabase(path); database.initialize()
            lock = sqlite3.connect(path)
            lock.execute("BEGIN EXCLUSIVE")
            recorder = HistoryRecorder(database, SettingsStore(Path(directory) / "settings.json"))
            try:
                recorder.observe(self.snapshot())
                self.assertIsNotNone(recorder.last_error)
            finally:
                lock.rollback(); lock.close(); recorder.shutdown()
