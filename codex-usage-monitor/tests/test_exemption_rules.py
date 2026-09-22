from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, time, timezone
from pathlib import Path

from monitor.exemption_rules import ExemptionRule, ExemptionStore, RuleType


LOCAL_TIMEZONE = datetime.now().astimezone().tzinfo


class ExemptionRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = ExemptionStore(Path(self.temp.name) / "usage_history.db")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_daily_crosses_midnight(self) -> None:
        rule = ExemptionRule(None, "night", RuleType.DAILY, time(22), time(6))
        self.assertTrue(self.store.is_exempt(1, datetime(2026, 9, 22, 1, tzinfo=LOCAL_TIMEZONE), [rule], set()))
        self.assertFalse(self.store.is_exempt(1, datetime(2026, 9, 22, 12, tzinfo=LOCAL_TIMEZONE), [rule], set()))

    def test_weekly_crosses_week_boundary(self) -> None:
        rule = ExemptionRule(None, "weekend", RuleType.WEEKLY, time(22), time(2), weekdays=(6,))
        self.assertTrue(self.store.is_exempt(1, datetime(2026, 9, 28, 1, tzinfo=LOCAL_TIMEZONE), [rule], set()))  # Monday; belongs to Sunday

    def test_one_time_manual_overlap_and_disabled_rules(self) -> None:
        moment = datetime(2026, 9, 25, 15, tzinfo=timezone.utc)
        one_time = ExemptionRule(None, "travel", RuleType.ONE_TIME, start_datetime=datetime(2026, 9, 25, 14, tzinfo=timezone.utc), end_datetime=datetime(2026, 9, 25, 18, tzinfo=timezone.utc))
        disabled = ExemptionRule(None, "off", RuleType.DAILY, time(0), time(23, 59), enabled=False)
        self.assertTrue(self.store.is_exempt(1, moment, [one_time, disabled], set()))
        self.assertTrue(self.store.is_exempt(9, moment, [disabled], {9}))

    def test_manual_exclude_include_again_keeps_raw_samples_untouched(self) -> None:
        self.store.exclude_samples([4, 5])
        self.assertEqual(self.store.manual_sample_ids(), {4, 5})
        self.store.include_samples_again([4])
        self.assertEqual(self.store.manual_sample_ids(), {5})

    def test_rule_persistence_and_toggle(self) -> None:
        rule_id = self.store.save_rule(ExemptionRule(None, "morning", RuleType.WEEKLY, time(8), time(12), weekdays=(0, 1, 2, 3, 4)))
        self.store.set_enabled(rule_id, False)
        rule = self.store.list_rules()[0]
        self.assertEqual(rule.weekdays, (0, 1, 2, 3, 4))
        self.assertFalse(rule.enabled)
