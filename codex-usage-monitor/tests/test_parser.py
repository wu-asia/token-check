from datetime import datetime, timezone
import unittest

from monitor.log_parser import parse_rate_limit_payload
from monitor.usage_model import DataSource, SnapshotStatus


def valid_payload() -> dict:
    return {
        "rateLimitsByLimitId": {
            "other": {"limitId": "other", "primary": {"usedPercent": 99, "windowDurationMins": 300, "resetsAt": 1}},
            "codex": {
                "limitId": "codex",
                "primary": {"usedPercent": 19, "windowDurationMins": 300, "resetsAt": 1790060250},
                "secondary": {"usedPercent": 57, "windowDurationMins": 10080, "resetsAt": 1790421278},
            },
        }
    }


class RateLimitParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.timestamp = datetime(2026, 9, 22, tzinfo=timezone.utc)

    def test_maps_only_exact_codex_window_durations(self) -> None:
        snapshot = parse_rate_limit_payload(valid_payload(), timestamp=self.timestamp)

        self.assertEqual(snapshot.five_hour_used, 19)
        self.assertEqual(snapshot.five_hour_remaining, 81)
        self.assertEqual(snapshot.weekly_used, 57)
        self.assertEqual(snapshot.weekly_remaining, 43)
        self.assertEqual(snapshot.source, DataSource.OFFICIAL)
        self.assertFalse(snapshot.verified)
        self.assertEqual(snapshot.status, SnapshotStatus.PENDING_MANUAL_VERIFICATION)

    def test_ignores_unrelated_limit_id(self) -> None:
        snapshot = parse_rate_limit_payload({"rateLimits": {"limitId": "other"}}, timestamp=self.timestamp)

        self.assertIsNone(snapshot.five_hour_used)
        self.assertEqual(snapshot.source, DataSource.UNKNOWN)
        self.assertEqual(snapshot.status, SnapshotStatus.UNAVAILABLE)

    def test_rejects_invalid_percent_instead_of_substituting_zero(self) -> None:
        payload = valid_payload()
        payload["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = 101

        snapshot = parse_rate_limit_payload(payload, timestamp=self.timestamp)

        self.assertIsNone(snapshot.five_hour_used)
        self.assertIsNone(snapshot.weekly_used)
        self.assertEqual(snapshot.status, SnapshotStatus.MALFORMED)


if __name__ == "__main__":
    unittest.main()
