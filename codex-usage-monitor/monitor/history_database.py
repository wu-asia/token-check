"""SQLite persistence for normalized usage snapshots only."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterator

from monitor.settings import PROJECT_ROOT
from monitor.usage_model import UsageSnapshot


DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "usage_history.db"


class HistoryDatabase:
    """A small local database; `None` is persisted as SQL NULL, never as zero."""

    def __init__(self, path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    five_hour_used INTEGER NULL,
                    five_hour_remaining INTEGER NULL,
                    five_hour_reset_at TEXT NULL,
                    weekly_used INTEGER NULL,
                    weekly_remaining INTEGER NULL,
                    weekly_reset_at TEXT NULL,
                    source TEXT NOT NULL,
                    verified INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def record_snapshot(self, snapshot: UsageSnapshot, created_at: datetime | None = None) -> int:
        self.initialize()
        recorded_at = created_at or datetime.now(timezone.utc)
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO usage_samples (
                    timestamp, five_hour_used, five_hour_remaining, five_hour_reset_at,
                    weekly_used, weekly_remaining, weekly_reset_at,
                    source, verified, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.timestamp.isoformat(),
                    snapshot.five_hour_used,
                    snapshot.five_hour_remaining,
                    self._format_datetime(snapshot.five_hour_reset_at),
                    snapshot.weekly_used,
                    snapshot.weekly_remaining,
                    self._format_datetime(snapshot.weekly_reset_at),
                    snapshot.source.value,
                    int(snapshot.verified),
                    snapshot.status.value,
                    recorded_at.isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def count_samples(self) -> int:
        self.initialize()
        with self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM usage_samples").fetchone()[0])

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Commit on success and always release the Windows file handle."""

        connection = sqlite3.connect(self.path)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _format_datetime(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None
