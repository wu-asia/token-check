"""Phase-2 usage data contract; intentionally contains no data-reading code."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DataSource(str, Enum):
    OFFICIAL = "Official"
    VERIFIED_LOCAL = "Verified Local"
    LOCAL_UNVERIFIED = "Local Unverified"
    ESTIMATED = "Estimated"
    UNKNOWN = "Unknown"


class SnapshotStatus(str, Enum):
    AVAILABLE = "available"
    PENDING_MANUAL_VERIFICATION = "pending_manual_verification"
    UNAVAILABLE = "unavailable"
    MALFORMED = "malformed"
    STALE = "stale"


@dataclass(frozen=True)
class UsageSnapshot:
    """A normalized two-window snapshot.

    `None` always means unknown or unavailable. A numeric zero means a real
    reported 0% value and is never used as an unknown-value sentinel.
    """

    timestamp: datetime
    five_hour_used: int | None
    five_hour_remaining: int | None
    five_hour_reset_at: datetime | None
    weekly_used: int | None
    weekly_remaining: int | None
    weekly_reset_at: datetime | None
    source: DataSource
    verified: bool
    status: SnapshotStatus

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        for field_name in (
            "five_hour_used", "five_hour_remaining", "weekly_used", "weekly_remaining",
        ):
            value = getattr(self, field_name)
            if value is not None and not 0 <= value <= 100:
                raise ValueError(f"{field_name} must be between 0 and 100 or None")
        for field_name in ("five_hour_reset_at", "weekly_reset_at"):
            value = getattr(self, field_name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{field_name} must be timezone-aware when present")
        if self.verified and self.status is SnapshotStatus.PENDING_MANUAL_VERIFICATION:
            raise ValueError("a verified snapshot cannot be pending manual verification")
