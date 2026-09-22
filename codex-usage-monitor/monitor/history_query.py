"""Read-only, bounded SQLite queries for the History UI and CSV export."""

from __future__ import annotations

import csv
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import TextIO

from monitor.history_database import DEFAULT_DATABASE_PATH


class HistoryRange(str, Enum):
    TODAY = "Today"
    HOURS_24 = "24 Hours"
    DAYS_7 = "7 Days"
    DAYS_30 = "30 Days"
    THIS_FIVE_HOUR = "This 5-hour Window"
    PREVIOUS_FIVE_HOUR = "Previous 5-hour Window"
    THIS_WEEKLY = "This Weekly Window"
    PREVIOUS_WEEKLY = "Previous Weekly Window"
    CUSTOM = "Custom"


SORT_COLUMNS = {
    "Time": "timestamp",
    "5h Used": "five_hour_used",
    "5h Remaining": "five_hour_remaining",
    "Weekly Used": "weekly_used",
    "Weekly Remaining": "weekly_remaining",
    "5h Reset": "five_hour_reset_at",
    "Weekly Reset": "weekly_reset_at",
    "Source": "source",
    "Status": "status",
}
CSV_COLUMNS = ("Time", "5h Used", "5h Remaining", "Weekly Used", "Weekly Remaining", "5h Reset", "Weekly Reset", "Source", "Status")


@dataclass(frozen=True)
class HistoryQuery:
    range: HistoryRange = HistoryRange.TODAY
    source: str | None = None
    status: str | None = None
    sort_label: str = "Time"
    descending: bool = True
    custom_start: datetime | None = None
    custom_end: datetime | None = None


@dataclass(frozen=True)
class HistoryPage:
    rows: list[tuple[object, ...]]
    total_rows: int
    page: int
    page_size: int


class HistoryQueryService:
    """All connections use SQLite's read-only URI mode; writes are impossible here."""

    def __init__(self, path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.path = path

    def fetch_page(self, query: HistoryQuery, page: int, page_size: int = 100, now: datetime | None = None) -> HistoryPage:
        if page < 0 or page_size <= 0:
            raise ValueError("page and page_size must be positive")
        where, parameters = self._where(query, now or datetime.now(timezone.utc))
        order_by = self._order_by(query)
        with self._connection() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) FROM usage_samples {where}", parameters).fetchone()[0])
            rows = connection.execute(
                "SELECT id, timestamp, five_hour_used, five_hour_remaining, five_hour_reset_at, "
                "weekly_used, weekly_remaining, weekly_reset_at, source, status "
                f"FROM usage_samples {where} {order_by} LIMIT ? OFFSET ?",
                (*parameters, page_size, page * page_size),
            ).fetchall()
        return HistoryPage(rows=rows, total_rows=total, page=page, page_size=page_size)

    def fetch_chart_rows(self, query: HistoryQuery, limit: int = 500, now: datetime | None = None) -> list[tuple[object, ...]]:
        """Return a bounded sample, preserving UI responsiveness for very large history."""

        if limit <= 0:
            raise ValueError("limit must be positive")
        where, parameters = self._where(query, now or datetime.now(timezone.utc))
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT timestamp, five_hour_used, five_hour_remaining, weekly_used, weekly_remaining "
                f"FROM usage_samples {where} ORDER BY timestamp DESC LIMIT ?",
                (*parameters, limit),
            ).fetchall()
        return list(reversed(rows))

    def export_rows(self, stream: TextIO, query: HistoryQuery | None, selected_ids: list[int] | None = None) -> int:
        """Stream UTF-8 CSV. `None` query means every row, without loading them all."""

        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        if selected_ids is not None and not selected_ids:
            return 0
        if selected_ids is not None:
            placeholders = ",".join("?" for _ in selected_ids)
            where, parameters = f"WHERE id IN ({placeholders})", tuple(selected_ids)
        elif query is None:
            where, parameters = "", ()
        else:
            where, parameters = self._where(query, datetime.now(timezone.utc))
        count = 0
        with self._connection() as connection:
            cursor = connection.execute(
                "SELECT timestamp, five_hour_used, five_hour_remaining, five_hour_reset_at, "
                "weekly_used, weekly_remaining, weekly_reset_at, source, status "
                f"FROM usage_samples {where} {self._order_by(query) if query else 'ORDER BY timestamp DESC'}",
                parameters,
            )
            while batch := cursor.fetchmany(500):
                writer.writerows(batch)
                count += len(batch)
        return count

    def _where(self, query: HistoryQuery, now: datetime) -> tuple[str, tuple[object, ...]]:
        clauses: list[str] = []
        parameters: list[object] = []
        if query.range is HistoryRange.TODAY:
            start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
            clauses.append("datetime(timestamp) >= datetime(?)")
            parameters.append(start.isoformat())
        elif query.range is HistoryRange.HOURS_24:
            clauses.append("datetime(timestamp) >= datetime(?)")
            parameters.append((now - timedelta(hours=24)).astimezone(timezone.utc).isoformat())
        elif query.range is HistoryRange.DAYS_7:
            clauses.append("datetime(timestamp) >= datetime(?)")
            parameters.append((now - timedelta(days=7)).astimezone(timezone.utc).isoformat())
        elif query.range is HistoryRange.DAYS_30:
            clauses.append("datetime(timestamp) >= datetime(?)")
            parameters.append((now - timedelta(days=30)).astimezone(timezone.utc).isoformat())
        elif query.range in {HistoryRange.THIS_FIVE_HOUR, HistoryRange.PREVIOUS_FIVE_HOUR}:
            offset = 0 if query.range is HistoryRange.THIS_FIVE_HOUR else 1
            clauses.append("five_hour_reset_at = (SELECT five_hour_reset_at FROM usage_samples WHERE five_hour_reset_at IS NOT NULL GROUP BY five_hour_reset_at ORDER BY five_hour_reset_at DESC LIMIT 1 OFFSET ?)")
            parameters.append(offset)
        elif query.range in {HistoryRange.THIS_WEEKLY, HistoryRange.PREVIOUS_WEEKLY}:
            offset = 0 if query.range is HistoryRange.THIS_WEEKLY else 1
            clauses.append("weekly_reset_at = (SELECT weekly_reset_at FROM usage_samples WHERE weekly_reset_at IS NOT NULL GROUP BY weekly_reset_at ORDER BY weekly_reset_at DESC LIMIT 1 OFFSET ?)")
            parameters.append(offset)
        elif query.range is HistoryRange.CUSTOM:
            if query.custom_start is not None:
                clauses.append("datetime(timestamp) >= datetime(?)")
                parameters.append(query.custom_start.astimezone(timezone.utc).isoformat())
            if query.custom_end is not None:
                clauses.append("datetime(timestamp) <= datetime(?)")
                parameters.append(query.custom_end.astimezone(timezone.utc).isoformat())
        if query.source:
            clauses.append("source = ?")
            parameters.append(query.source)
        if query.status:
            clauses.append("status = ?")
            parameters.append(query.status)
        return ("WHERE " + " AND ".join(clauses) if clauses else "", tuple(parameters))

    @staticmethod
    def _order_by(query: HistoryQuery) -> str:
        column = SORT_COLUMNS.get(query.sort_label)
        if column is None:
            raise ValueError("unsupported sort column")
        return f"ORDER BY {column} {'DESC' if query.descending else 'ASC'}, id DESC"

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
        try:
            yield connection
        finally:
            connection.close()
