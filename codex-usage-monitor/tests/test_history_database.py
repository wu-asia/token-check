from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from monitor.history_database import HistoryDatabase
from monitor.usage_model import DataSource, SnapshotStatus, UsageSnapshot


def unknown_snapshot() -> UsageSnapshot:
    return UsageSnapshot(
        timestamp=datetime(2026, 9, 22, 10, tzinfo=timezone.utc),
        five_hour_used=None, five_hour_remaining=None, five_hour_reset_at=None,
        weekly_used=None, weekly_remaining=None, weekly_reset_at=None,
        source=DataSource.UNKNOWN, verified=False, status=SnapshotStatus.UNAVAILABLE,
    )


class HistoryDatabaseTests(unittest.TestCase):
    def test_records_unknown_fields_as_sql_null_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = HistoryDatabase(Path(directory) / "data" / "usage_history.db")
            row_id = database.record_snapshot(unknown_snapshot())

            connection = sqlite3.connect(database.path)
            try:
                row = connection.execute(
                    "SELECT five_hour_used, five_hour_remaining, five_hour_reset_at, "
                    "weekly_used, weekly_remaining, weekly_reset_at, source, verified, status "
                    "FROM usage_samples WHERE id = ?",
                    (row_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(row, (None, None, None, None, None, None, "Unknown", 0, "unavailable"))

    def test_creates_required_table_and_counts_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = HistoryDatabase(Path(directory) / "usage_history.db")
            database.initialize()

            connection = sqlite3.connect(database.path)
            try:
                columns = {item[1] for item in connection.execute("PRAGMA table_info(usage_samples)")}
            finally:
                connection.close()

            self.assertTrue({
                "id", "timestamp", "five_hour_used", "five_hour_remaining", "five_hour_reset_at",
                "weekly_used", "weekly_remaining", "weekly_reset_at", "source", "verified", "status", "created_at",
            }.issubset(columns))
            self.assertEqual(database.count_samples(), 0)
