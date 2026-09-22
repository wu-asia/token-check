from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from monitor.history_query import HistoryQueryService
from tests.test_history_query import make_database
from ui.history_window import HistoryWindow


class HistoryWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_large_history_loads_in_background_and_keeps_page_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = make_database(Path(directory), count=3_000)
            started = time.monotonic()
            window = HistoryWindow(HistoryQueryService(database.path))
            construction_seconds = time.monotonic() - started
            try:
                self.assertLess(construction_seconds, 1.0)
                loop = QEventLoop()
                QTimer.singleShot(5_000, loop.quit)
                original = window._query_completed

                def complete(page: object, chart: object) -> None:
                    original(page, chart)  # type: ignore[arg-type]
                    loop.quit()

                window._query_completed = complete  # type: ignore[method-assign]
                loop.exec()
                self.assertLessEqual(window.model.rowCount(), window.PAGE_SIZE)
                self.assertIn("rows", window.page_label.text())
            finally:
                window.close()
