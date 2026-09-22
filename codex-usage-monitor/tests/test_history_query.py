from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from monitor.history_database import HistoryDatabase
from monitor.history_query import HistoryQuery, HistoryQueryService, HistoryRange


def make_database(root: Path, count: int = 5_000) -> HistoryDatabase:
    database = HistoryDatabase(root / "data" / "usage_history.db")
    database.initialize()
    base = datetime.now(timezone.utc) - timedelta(minutes=count)
    rows = []
    for index in range(count):
        timestamp = base + timedelta(minutes=index)
        five_reset = timestamp.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        weekly_reset = timestamp.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=7)
        rows.append((
            timestamp.isoformat(), index % 101, 100 - (index % 101), five_reset.isoformat(),
            (index * 2) % 101, 100 - ((index * 2) % 101), weekly_reset.isoformat(),
            "Official", 0, "pending_manual_verification", timestamp.isoformat(),
        ))
    connection = sqlite3.connect(database.path)
    try:
        connection.executemany(
            "INSERT INTO usage_samples (timestamp, five_hour_used, five_hour_remaining, five_hour_reset_at, "
            "weekly_used, weekly_remaining, weekly_reset_at, source, verified, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows,
        )
        connection.commit()
    finally:
        connection.close()
    return database


class HistoryQueryTests(unittest.TestCase):
    def test_large_database_is_paginated_and_chart_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = make_database(Path(directory))
            service = HistoryQueryService(database.path)
            query = HistoryQuery(range=HistoryRange.DAYS_7)

            page = service.fetch_page(query, page=0, page_size=100)
            chart = service.fetch_chart_rows(query, limit=500)

            self.assertGreater(page.total_rows, 100)
            self.assertEqual(len(page.rows), 100)
            self.assertLessEqual(len(chart), 500)
            self.assertEqual(len(page.rows[0]), 10)  # hidden ID plus the nine visible table values

    def test_window_and_source_filters_do_not_return_unrelated_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = make_database(Path(directory), count=10)
            service = HistoryQueryService(database.path)
            page = service.fetch_page(HistoryQuery(range=HistoryRange.THIS_FIVE_HOUR, source="Official"), page=0)

            self.assertGreater(len(page.rows), 0)
            reset_values = {row[4] for row in page.rows}
            self.assertEqual(len(reset_values), 1)
            self.assertTrue(all(row[8] == "Official" for row in page.rows))

    def test_csv_export_streams_current_scope_selected_rows_and_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = make_database(Path(directory), count=10)
            service = HistoryQueryService(database.path)
            page = service.fetch_page(HistoryQuery(range=HistoryRange.DAYS_30), page=0)
            selected = [int(page.rows[0][0]), int(page.rows[1][0])]

            selected_stream = io.StringIO()
            self.assertEqual(service.export_rows(selected_stream, None, selected), 2)
            self.assertEqual(len(selected_stream.getvalue().splitlines()), 3)

            all_stream = io.StringIO()
            self.assertEqual(service.export_rows(all_stream, None), 10)
            self.assertTrue(all_stream.getvalue().startswith("Time,5h Used"))
