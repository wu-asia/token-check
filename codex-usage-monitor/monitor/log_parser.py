"""Validate documented App Server rate-limit payloads.

Desktop/CLI log formats are intentionally not parsed: Phase 2 did not verify
their schema or relationship to the Usage screen.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from monitor.usage_model import DataSource, SnapshotStatus, UsageSnapshot


FIVE_HOUR_MINUTES = 300
WEEKLY_MINUTES = 10_080


def unavailable_snapshot(timestamp: datetime, *, source: DataSource = DataSource.UNKNOWN) -> UsageSnapshot:
    return UsageSnapshot(
        timestamp=timestamp,
        five_hour_used=None,
        five_hour_remaining=None,
        five_hour_reset_at=None,
        weekly_used=None,
        weekly_remaining=None,
        weekly_reset_at=None,
        source=source,
        verified=False,
        status=SnapshotStatus.UNAVAILABLE,
    )


def _malformed_snapshot(timestamp: datetime) -> UsageSnapshot:
    snapshot = unavailable_snapshot(timestamp, source=DataSource.OFFICIAL)
    return UsageSnapshot(**{**snapshot.__dict__, "status": SnapshotStatus.MALFORMED})


def _valid_window(value: Any) -> tuple[int, datetime] | None:
    if not isinstance(value, Mapping):
        return None
    used = value.get("usedPercent")
    reset_seconds = value.get("resetsAt")
    if isinstance(used, bool) or not isinstance(used, int) or not 0 <= used <= 100:
        return None
    if isinstance(reset_seconds, bool) or not isinstance(reset_seconds, int) or reset_seconds <= 0:
        return None
    try:
        return used, datetime.fromtimestamp(reset_seconds, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _codex_limit(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    result = payload.get("result", payload)
    if not isinstance(result, Mapping):
        return None
    by_id = result.get("rateLimitsByLimitId")
    if isinstance(by_id, Mapping):
        candidate = by_id.get("codex")
        return candidate if isinstance(candidate, Mapping) and candidate.get("limitId") == "codex" else None
    candidate = result.get("rateLimits")
    return candidate if isinstance(candidate, Mapping) and candidate.get("limitId") == "codex" else None


def parse_rate_limit_payload(payload: Mapping[str, Any], *, timestamp: datetime | None = None) -> UsageSnapshot:
    """Map only exact documented `codex` 300/10080-minute windows to a snapshot."""
    captured_at = timestamp or datetime.now(timezone.utc)
    if captured_at.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    limit = _codex_limit(payload)
    if limit is None:
        return unavailable_snapshot(captured_at)

    matches: dict[int, list[tuple[int, datetime]]] = {FIVE_HOUR_MINUTES: [], WEEKLY_MINUTES: []}
    for slot in ("primary", "secondary"):
        window = limit.get(slot)
        if not isinstance(window, Mapping):
            continue
        duration = window.get("windowDurationMins")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration not in matches:
            continue
        validated = _valid_window(window)
        if validated is None:
            return _malformed_snapshot(captured_at)
        matches[duration].append(validated)

    if any(len(windows) > 1 for windows in matches.values()):
        return _malformed_snapshot(captured_at)
    five = matches[FIVE_HOUR_MINUTES][0] if matches[FIVE_HOUR_MINUTES] else None
    weekly = matches[WEEKLY_MINUTES][0] if matches[WEEKLY_MINUTES] else None
    if five is None and weekly is None:
        return unavailable_snapshot(captured_at, source=DataSource.OFFICIAL)

    return UsageSnapshot(
        timestamp=captured_at,
        five_hour_used=five[0] if five else None,
        five_hour_remaining=100 - five[0] if five else None,
        five_hour_reset_at=five[1] if five else None,
        weekly_used=weekly[0] if weekly else None,
        weekly_remaining=100 - weekly[0] if weekly else None,
        weekly_reset_at=weekly[1] if weekly else None,
        source=DataSource.OFFICIAL,
        verified=False,
        status=SnapshotStatus.PENDING_MANUAL_VERIFICATION,
    )
