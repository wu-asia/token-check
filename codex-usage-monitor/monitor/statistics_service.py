"""Read-only statistical calculations over raw history with local exemptions."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from monitor.exemption_rules import ExemptionStore
from monitor.history_database import DEFAULT_DATABASE_PATH


class StatisticsRange(str, Enum):
    TODAY = "Today"
    HOURS_24 = "24 Hours"
    DAYS_7 = "7 Days"
    DAYS_30 = "30 Days"
    CUSTOM = "Custom"


@dataclass(frozen=True)
class StatisticsQuery:
    range: StatisticsRange = StatisticsRange.TODAY
    custom_start: datetime | None = None
    custom_end: datetime | None = None
    include_exempt: bool = False


@dataclass(frozen=True)
class WindowStatistics:
    usage_delta: int | None
    peak_usage: int | None
    minimum_remaining: int | None
    average_change_rate_per_hour: float | None
    window_count: int
    sample_count: int


@dataclass(frozen=True)
class StatisticsResult:
    five_hour: WindowStatistics
    weekly: WindowStatistics
    raw_sample_count: int
    exempt_sample_count: int
    chart_rows: list[tuple[object, ...]]  # timestamp, 5h used/remain, weekly used/remain, exempt


class StatisticsService:
    """Streams raw rows in order; no change is made to the raw-history table."""

    def __init__(self, path: Path = DEFAULT_DATABASE_PATH, exemption_store: ExemptionStore | None = None) -> None:
        self.path = path
        self.exemption_store = exemption_store or ExemptionStore(path)

    def calculate(self, query: StatisticsQuery, now: datetime | None = None) -> StatisticsResult:
        rules, manual_ids = self.exemption_store.list_rules(), self.exemption_store.manual_sample_ids()
        where, parameters = self._where(query, now or datetime.now(timezone.utc))
        five = _Accumulator(used_index=2, remaining_index=3, reset_index=4)
        weekly = _Accumulator(used_index=5, remaining_index=6, reset_index=7)
        raw_count = exempt_count = 0
        chart_rows: list[tuple[object, ...]] = []
        with self._connection() as connection:
            cursor = connection.execute(
                "SELECT id, timestamp, five_hour_used, five_hour_remaining, five_hour_reset_at, "
                "weekly_used, weekly_remaining, weekly_reset_at FROM usage_samples "
                f"{where} ORDER BY timestamp ASC", parameters,
            )
            while batch := cursor.fetchmany(500):
                for row in batch:
                    raw_count += 1
                    timestamp = datetime.fromisoformat(str(row[1]))
                    exempt = self.exemption_store.is_exempt(int(row[0]), timestamp, rules, manual_ids)
                    if exempt:
                        exempt_count += 1
                    if len(chart_rows) < 500:
                        chart_rows.append((row[1], row[2], row[3], row[5], row[6], exempt))
                    if query.include_exempt or not exempt:
                        five.add(row, timestamp)
                        weekly.add(row, timestamp)
        return StatisticsResult(five.finish(), weekly.finish(), raw_count, exempt_count, chart_rows)

    def _where(self, query: StatisticsQuery, now: datetime) -> tuple[str, tuple[object, ...]]:
        start: datetime | None = None
        if query.range is StatisticsRange.TODAY:
            start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        elif query.range is StatisticsRange.HOURS_24:
            start = now - timedelta(hours=24)
        elif query.range is StatisticsRange.DAYS_7:
            start = now - timedelta(days=7)
        elif query.range is StatisticsRange.DAYS_30:
            start = now - timedelta(days=30)
        elif query.range is StatisticsRange.CUSTOM:
            start = query.custom_start
        clauses, params = [], []
        if start is not None:
            clauses.append("datetime(timestamp) >= datetime(?)"); params.append(start.astimezone(timezone.utc).isoformat())
        end = query.custom_end if query.range is StatisticsRange.CUSTOM else None
        if end is not None:
            clauses.append("datetime(timestamp) <= datetime(?)"); params.append(end.astimezone(timezone.utc).isoformat())
        return ("WHERE " + " AND ".join(clauses) if clauses else "", tuple(params))

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
        try:
            yield connection
        finally:
            connection.close()


class _Accumulator:
    def __init__(self, used_index: int, remaining_index: int, reset_index: int) -> None:
        self.used_index, self.remaining_index, self.reset_index = used_index, remaining_index, reset_index
        self.values: list[int] = []; self.remaining: list[int] = []; self.resets: set[str] = set()
        self.delta = 0; self.rate_seconds = 0.0; self.previous: tuple[int, str, datetime] | None = None

    def add(self, row: tuple[object, ...], timestamp: datetime) -> None:
        used, remaining, reset = row[self.used_index], row[self.remaining_index], row[self.reset_index]
        if isinstance(used, int): self.values.append(used)
        if isinstance(remaining, int): self.remaining.append(remaining)
        if isinstance(reset, str): self.resets.add(reset)
        if not isinstance(used, int) or not isinstance(reset, str):
            self.previous = None
            return
        if self.previous is not None:
            prior_used, prior_reset, prior_time = self.previous
            # A reset starts a new window: never subtract values across it.
            if prior_reset == reset and used >= prior_used:
                self.delta += used - prior_used
                self.rate_seconds += max(0.0, (timestamp - prior_time).total_seconds())
        self.previous = (used, reset, timestamp)

    def finish(self) -> WindowStatistics:
        rate = self.delta / (self.rate_seconds / 3600) if self.rate_seconds else None
        return WindowStatistics(self.delta if self.values else None, max(self.values) if self.values else None,
                                min(self.remaining) if self.remaining else None, rate, len(self.resets), len(self.values))
