"""Local-only statistics exemption rules; they never alter Codex or raw history."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from pathlib import Path

from monitor.history_database import DEFAULT_DATABASE_PATH


class RuleType(str, Enum):
    DAILY = "Daily"
    WEEKLY = "Weekly"
    ONE_TIME = "One-Time"
    MANUAL = "Manual"


@dataclass(frozen=True)
class ExemptionRule:
    id: int | None
    name: str
    rule_type: RuleType
    start_time: time | None = None
    end_time: time | None = None
    weekdays: tuple[int, ...] = ()  # Monday=0 through Sunday=6
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    enabled: bool = True
    created_at: datetime | None = None


class ExemptionStore:
    """Writes only exemption metadata; raw `usage_samples` remain immutable."""

    def __init__(self, path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS exemption_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    rule_type TEXT NOT NULL,
                    start_time TEXT NULL,
                    end_time TEXT NULL,
                    weekdays TEXT NULL,
                    start_datetime TEXT NULL,
                    end_datetime TEXT NULL,
                    enabled INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS manual_exemptions (
                    sample_id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL
                )"""
            )

    def save_rule(self, rule: ExemptionRule) -> int:
        self._validate_rule(rule)
        self.initialize()
        created_at = rule.created_at or datetime.now().astimezone()
        values = (
            rule.name, rule.rule_type.value, self._format_time(rule.start_time), self._format_time(rule.end_time),
            ",".join(str(day) for day in rule.weekdays), self._format_datetime(rule.start_datetime),
            self._format_datetime(rule.end_datetime), int(rule.enabled), created_at.isoformat(),
        )
        with self._connection() as connection:
            if rule.id is None:
                cursor = connection.execute(
                    "INSERT INTO exemption_rules (name, rule_type, start_time, end_time, weekdays, start_datetime, end_datetime, enabled, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", values,
                )
                return int(cursor.lastrowid)
            connection.execute(
                "UPDATE exemption_rules SET name=?, rule_type=?, start_time=?, end_time=?, weekdays=?, start_datetime=?, end_datetime=?, enabled=? WHERE id=?",
                (*values[:-1], rule.id),
            )
            return rule.id

    def list_rules(self) -> list[ExemptionRule]:
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, name, rule_type, start_time, end_time, weekdays, start_datetime, end_datetime, enabled, created_at "
                "FROM exemption_rules ORDER BY id"
            ).fetchall()
        return [self._rule_from_row(row) for row in rows]

    def set_enabled(self, rule_id: int, enabled: bool) -> None:
        self.initialize()
        with self._connection() as connection:
            connection.execute("UPDATE exemption_rules SET enabled=? WHERE id=?", (int(enabled), rule_id))

    def exclude_samples(self, sample_ids: list[int]) -> None:
        self.initialize()
        now = datetime.now().astimezone().isoformat()
        with self._connection() as connection:
            connection.executemany("INSERT OR IGNORE INTO manual_exemptions (sample_id, created_at) VALUES (?, ?)", ((sample_id, now) for sample_id in sample_ids))

    def include_samples_again(self, sample_ids: list[int]) -> None:
        self.initialize()
        with self._connection() as connection:
            connection.executemany("DELETE FROM manual_exemptions WHERE sample_id=?", ((sample_id,) for sample_id in sample_ids))

    def manual_sample_ids(self) -> set[int]:
        self.initialize()
        with self._connection() as connection:
            return {int(row[0]) for row in connection.execute("SELECT sample_id FROM manual_exemptions")}

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=0.2)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def is_exempt(sample_id: int, timestamp: datetime, rules: list[ExemptionRule], manual_ids: set[int]) -> bool:
        if sample_id in manual_ids:
            return True
        return any(rule.enabled and _matches_rule(timestamp.astimezone(), rule) for rule in rules)

    @staticmethod
    def _validate_rule(rule: ExemptionRule) -> None:
        if not rule.name.strip():
            raise ValueError("rule name is required")
        if rule.rule_type in {RuleType.DAILY, RuleType.WEEKLY}:
            if rule.start_time is None or rule.end_time is None:
                raise ValueError("daily and weekly rules need start_time and end_time")
            if rule.rule_type is RuleType.WEEKLY and any(day not in range(7) for day in rule.weekdays):
                raise ValueError("weekdays must use 0..6")
        if rule.rule_type is RuleType.ONE_TIME:
            if rule.start_datetime is None or rule.end_datetime is None or rule.end_datetime <= rule.start_datetime:
                raise ValueError("one-time rules need an increasing datetime range")

    @staticmethod
    def _format_time(value: time | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _format_datetime(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _rule_from_row(row: tuple[object, ...]) -> ExemptionRule:
        weekdays = tuple(int(value) for value in str(row[5] or "").split(",") if value != "")
        return ExemptionRule(
            id=int(row[0]), name=str(row[1]), rule_type=RuleType(str(row[2])),
            start_time=time.fromisoformat(str(row[3])) if row[3] else None,
            end_time=time.fromisoformat(str(row[4])) if row[4] else None,
            weekdays=weekdays,
            start_datetime=datetime.fromisoformat(str(row[6])) if row[6] else None,
            end_datetime=datetime.fromisoformat(str(row[7])) if row[7] else None,
            enabled=bool(row[8]), created_at=datetime.fromisoformat(str(row[9])),
        )


def _matches_rule(moment: datetime, rule: ExemptionRule) -> bool:
    if rule.rule_type is RuleType.ONE_TIME:
        return bool(rule.start_datetime and rule.end_datetime and rule.start_datetime <= moment <= rule.end_datetime)
    if rule.rule_type is RuleType.MANUAL:
        return False  # Manual exclusions are represented by manual_exemptions sample IDs.
    if rule.start_time is None or rule.end_time is None:
        return False
    current_time = moment.timetz().replace(tzinfo=None)
    crosses_midnight = rule.end_time <= rule.start_time
    in_time = current_time >= rule.start_time or current_time <= rule.end_time if crosses_midnight else rule.start_time <= current_time <= rule.end_time
    if not in_time:
        return False
    if rule.rule_type is RuleType.DAILY:
        return True
    weekday = moment.weekday()
    if crosses_midnight and current_time <= rule.end_time:
        weekday = (weekday - 1) % 7
    return weekday in rule.weekdays
