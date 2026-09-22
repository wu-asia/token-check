from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from diagnostics.diagnostics import Candidate, RootResult, evidence_status, matching_terms, walk_root


class DiagnosticsTests(unittest.TestCase):
    def test_matching_terms_returns_keyword_names_not_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "state.json"
            candidate.write_text('{"rate_limit": {"weekly": "value-not-to-report"}}', encoding="utf-8")

            terms = matching_terms(candidate)

        self.assertIn("rate_limit", terms)
        self.assertIn("weekly", terms)
        self.assertNotIn("value-not-to-report", terms)

    def test_sensitive_filename_is_not_inspected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            credential_file = Path(temporary) / "auth-token.json"
            credential_file.write_text('{"usage": 88}', encoding="utf-8")

            self.assertEqual(matching_terms(credential_file), ())

    def test_walk_root_ignores_sensitive_paths_and_finds_safe_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "usage.log").write_text("weekly quota reset", encoding="utf-8")
            (root / "session.json").write_text("weekly quota reset", encoding="utf-8")

            result = walk_root("test", root)

        self.assertTrue(result.exists)
        self.assertTrue(result.readable)
        self.assertEqual([item.path.name for item in result.candidates], ["usage.log"])
        self.assertEqual(set(result.candidates[0].terms), {"reset", "weekly", "quota"})

    def test_evidence_status_does_not_call_candidate_data_official(self) -> None:
        empty = RootResult("empty", Path("missing"), False)
        candidate = Candidate(Path("state.json"), 1, datetime.now(timezone.utc), ("usage",))
        local = RootResult("local", Path("local"), True, candidates=[candidate])

        self.assertEqual(evidence_status([empty]), "Unknown")
        self.assertEqual(evidence_status([empty, local]), "Local / Unverified")


if __name__ == "__main__":
    unittest.main()
