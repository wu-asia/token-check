from collections.abc import Mapping
import unittest

from monitor.codex_detector import CodexInstallation
from monitor.usage_model import DataSource, SnapshotStatus
from monitor.usage_reader import UsageReader


VALID_RESPONSE: Mapping[str, object] = {
    "rateLimitsByLimitId": {
        "codex": {
            "limitId": "codex",
            "primary": {"usedPercent": 34, "windowDurationMins": 300, "resetsAt": 1790060250},
            "secondary": {"usedPercent": 57, "windowDurationMins": 10080, "resetsAt": 1790421278},
        }
    }
}


class UsageReaderTests(unittest.TestCase):
    def test_reads_sample_without_accessing_real_codex(self) -> None:
        reader = UsageReader(
            detector=lambda: CodexInstallation("C:/fake/codex.exe", "test", True, False),
            rate_limit_reader=lambda _: VALID_RESPONSE,
        )

        snapshot = reader.read_usage()

        self.assertEqual(snapshot.five_hour_used, 34)
        self.assertEqual(snapshot.weekly_remaining, 43)
        self.assertEqual(snapshot.source, DataSource.OFFICIAL)
        self.assertFalse(snapshot.verified)

    def test_missing_cli_returns_none_values(self) -> None:
        reader = UsageReader(
            detector=lambda: CodexInstallation(None, None, False, False),
            rate_limit_reader=lambda _: self.fail("reader must not be called"),
        )

        snapshot = reader.read_usage()

        self.assertIsNone(snapshot.five_hour_used)
        self.assertIsNone(snapshot.weekly_used)
        self.assertEqual(snapshot.status, SnapshotStatus.UNAVAILABLE)

    def test_read_failure_never_raises_or_forges_zero(self) -> None:
        def failing_reader(_: str) -> Mapping[str, object]:
            raise OSError("locked")

        reader = UsageReader(
            detector=lambda: CodexInstallation("C:/fake/codex.exe", "test", True, False),
            rate_limit_reader=failing_reader,
        )

        snapshot = reader.read_usage()

        self.assertIsNone(snapshot.five_hour_used)
        self.assertIsNone(snapshot.weekly_remaining)
        self.assertEqual(snapshot.status, SnapshotStatus.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
