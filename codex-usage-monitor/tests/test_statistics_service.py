from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from monitor.exemption_rules import ExemptionStore
from monitor.history_database import HistoryDatabase
from monitor.statistics_service import StatisticsQuery, StatisticsRange, StatisticsService


class StatisticsServiceTests(unittest.TestCase):
    def test_reset_does_not_create_negative_usage_and_exemptions_are_optional(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage_history.db"
            database = HistoryDatabase(path); database.initialize()
            start = datetime.now(timezone.utc) - timedelta(hours=1)
            reset_a, reset_b = start + timedelta(minutes=30), start + timedelta(hours=5, minutes=30)
            rows = [
                (start.isoformat(), 70, 30, reset_a.isoformat(), 40, 60, reset_a.isoformat(), "Official", 0, "available", start.isoformat()),
                ((start + timedelta(minutes=10)).isoformat(), 80, 20, reset_a.isoformat(), 45, 55, reset_a.isoformat(), "Official", 0, "available", start.isoformat()),
                ((start + timedelta(minutes=20)).isoformat(), 5, 95, reset_b.isoformat(), 3, 97, reset_b.isoformat(), "Official", 0, "available", start.isoformat()),
                ((start + timedelta(minutes=30)).isoformat(), 15, 85, reset_b.isoformat(), 7, 93, reset_b.isoformat(), "Official", 0, "available", start.isoformat()),
            ]
            connection = sqlite3.connect(path)
            try:
                connection.executemany("INSERT INTO usage_samples (timestamp, five_hour_used, five_hour_remaining, five_hour_reset_at, weekly_used, weekly_remaining, weekly_reset_at, source, verified, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
                connection.commit()
            finally:
                connection.close()
            store = ExemptionStore(path); store.exclude_samples([2])
            service = StatisticsService(path, store)
            query = StatisticsQuery(range=StatisticsRange.HOURS_24)
            excluded = service.calculate(query)
            included = service.calculate(StatisticsQuery(range=StatisticsRange.HOURS_24, include_exempt=True))
            self.assertEqual(included.five_hour.usage_delta, 20)
            self.assertGreaterEqual(excluded.exempt_sample_count, 1)
            self.assertEqual(included.five_hour.window_count, 2)
