"""Non-blocking, read-only History page for Codex Usage Monitor."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QDateTime, QModelIndex, QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QSplitter, QTableView,
    QVBoxLayout, QWidget,
)

from monitor.history_query import CSV_COLUMNS, HistoryPage, HistoryQuery, HistoryQueryService, HistoryRange, SORT_COLUMNS


def _display(value: object) -> str:
    return "N/A" if value is None else str(value)


class HistoryTableModel(QAbstractTableModel):
    """A page-only model: at most one page is resident in the GUI."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[object, ...]] = []

    def set_rows(self, rows: list[tuple[object, ...]]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(CSV_COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:  # type: ignore[override]
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        return _display(self.rows[index.row()][index.column() + 1])

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> object:  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return CSV_COLUMNS[section]
        return super().headerData(section, orientation, role)

    def selected_ids(self, indexes: list[QModelIndex]) -> list[int]:
        return sorted({int(self.rows[index.row()][0]) for index in indexes if index.isValid()})


class UsageChartWidget(QWidget):
    """A dependency-free line chart limited to the service's bounded sample."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self.metric = "Used"
        self.rows: list[tuple[object, ...]] = []
        self.setMinimumHeight(160)

    def set_data(self, rows: list[tuple[object, ...]], metric: str) -> None:
        self.rows = rows
        self.metric = metric
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        painter.setPen(self.palette().text().color())
        painter.drawText(10, 20, f"{self.title} — {self.metric}")
        left, top, right, bottom = 38, 32, self.width() - 12, self.height() - 25
        painter.setPen(QPen(self.palette().mid().color()))
        painter.drawLine(left, bottom, right, bottom)
        painter.drawLine(left, top, left, bottom)
        painter.drawText(4, top + 5, "100")
        painter.drawText(13, bottom + 4, "0")
        value_index = 1 if self.title == "5-hour Usage" and self.metric == "Used" else 2 if self.title == "5-hour Usage" else 3 if self.metric == "Used" else 4
        values = [(index, row[value_index]) for index, row in enumerate(self.rows) if isinstance(row[value_index], int)]
        if len(values) < 2 or right <= left or bottom <= top:
            painter.drawText(left + 8, top + 20, "No chart data")
            painter.end()
            return
        painter.setPen(QPen(QColor("#3584e4"), 2))
        denominator = max(1, len(self.rows) - 1)
        previous: tuple[int, int] | None = None
        for index, value in values:
            x = left + round((right - left) * index / denominator)
            y = bottom - round((bottom - top) * int(value) / 100)
            if previous is not None:
                painter.drawLine(*previous, x, y)
            previous = (x, y)
        painter.end()


class QueryWorker(QObject):
    completed = Signal(object, object)
    failed = Signal(str)

    def __init__(self, service: HistoryQueryService, query: HistoryQuery, page: int, page_size: int) -> None:
        super().__init__()
        self.service, self.query, self.page, self.page_size = service, query, page, page_size

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(self.service.fetch_page(self.query, self.page, self.page_size), self.service.fetch_chart_rows(self.query))
        except Exception as error:
            self.failed.emit(str(error) or "Unable to read history")


class ExportWorker(QObject):
    completed = Signal(int)
    failed = Signal(str)

    def __init__(self, service: HistoryQueryService, path: Path, query: HistoryQuery | None, selected_ids: list[int] | None) -> None:
        super().__init__()
        self.service, self.path, self.query, self.selected_ids = service, path, query, selected_ids

    @Slot()
    def run(self) -> None:
        try:
            with self.path.open("w", encoding="utf-8", newline="") as stream:
                count = self.service.export_rows(stream, self.query, self.selected_ids)
            self.completed.emit(count)
        except Exception as error:
            self.failed.emit(str(error) or "Unable to export history")


class HistoryWindow(QMainWindow):
    """History UI; it never writes to the raw history database."""

    PAGE_SIZE = 100

    def __init__(self, service: HistoryQueryService | None = None) -> None:
        super().__init__()
        self.service = service or HistoryQueryService()
        self.page = 0
        self.total_rows = 0
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self.setWindowTitle("Codex Usage Monitor — History")
        self.resize(1080, 720)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        filters = QFormLayout()
        self.range_combo = QComboBox()
        self.range_combo.addItems([item.value for item in HistoryRange])
        self.source_combo = QComboBox(); self.source_combo.addItems(["All", "Official", "Verified Local", "Local Unverified", "Estimated", "Unknown"])
        self.status_combo = QComboBox(); self.status_combo.addItems(["All", "available", "pending_manual_verification", "unavailable", "malformed", "stale"])
        self.sort_combo = QComboBox(); self.sort_combo.addItems(SORT_COLUMNS)
        self.descending = QCheckBox("Descending"); self.descending.setChecked(True)
        self.custom_start = QDateTimeEdit(QDateTime.currentDateTime()); self.custom_start.setCalendarPopup(True)
        self.custom_end = QDateTimeEdit(QDateTime.currentDateTime()); self.custom_end.setCalendarPopup(True)
        filters.addRow("Range:", self.range_combo)
        filters.addRow("Source:", self.source_combo)
        filters.addRow("Status:", self.status_combo)
        filters.addRow("Sort:", self.sort_combo)
        filters.addRow("Order:", self.descending)
        filters.addRow("Custom start:", self.custom_start)
        filters.addRow("Custom end:", self.custom_end)
        layout.addLayout(filters)
        controls = QHBoxLayout()
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self._apply_filters)
        self.prev_button = QPushButton("Previous")
        self.prev_button.clicked.connect(self._previous_page)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self._next_page)
        self.page_label = QLabel("Page 1")
        self.export_view_button = QPushButton("Export Current View")
        self.export_view_button.clicked.connect(lambda: self._export("view"))
        self.export_selected_button = QPushButton("Export Selected Range")
        self.export_selected_button.clicked.connect(lambda: self._export("selected"))
        self.export_all_button = QPushButton("Export All")
        self.export_all_button.clicked.connect(lambda: self._export("all"))
        for widget in (self.apply_button, self.prev_button, self.next_button, self.page_label, self.export_view_button, self.export_selected_button, self.export_all_button): controls.addWidget(widget)
        layout.addLayout(controls)
        self.model = HistoryTableModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.five_chart = UsageChartWidget("5-hour Usage")
        self.weekly_chart = UsageChartWidget("Weekly Usage")
        self.metric_combo = QComboBox(); self.metric_combo.addItems(["Used", "Remaining"]); self.metric_combo.currentTextChanged.connect(self._update_charts)
        layout.addWidget(self.metric_combo)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        charts = QWidget(); chart_layout = QHBoxLayout(charts); chart_layout.addWidget(self.five_chart); chart_layout.addWidget(self.weekly_chart)
        splitter.addWidget(charts)
        layout.addWidget(splitter)
        self.status_label = QLabel("Loading history…")
        layout.addWidget(self.status_label)
        self.setCentralWidget(root)

    def _query(self) -> HistoryQuery:
        range_value = HistoryRange(self.range_combo.currentText())
        start = self.custom_start.dateTime().toPython().astimezone()
        end = self.custom_end.dateTime().toPython().astimezone()
        return HistoryQuery(
            range=range_value,
            source=None if self.source_combo.currentText() == "All" else self.source_combo.currentText(),
            status=None if self.status_combo.currentText() == "All" else self.status_combo.currentText(),
            sort_label=self.sort_combo.currentText(), descending=self.descending.isChecked(),
            custom_start=start, custom_end=end,
        )

    @Slot()
    def _apply_filters(self) -> None:
        self.page = 0
        self.refresh()

    @Slot()
    def _previous_page(self) -> None:
        if self.page:
            self.page -= 1
            self.refresh()

    @Slot()
    def _next_page(self) -> None:
        if (self.page + 1) * self.PAGE_SIZE < self.total_rows:
            self.page += 1
            self.refresh()

    @Slot()
    def refresh(self) -> None:
        if self._thread is not None:
            return
        self.status_label.setText("Loading history…")
        self._set_controls_enabled(False)
        self._start_worker(QueryWorker(self.service, self._query(), self.page, self.PAGE_SIZE), self._query_completed)

    def _start_worker(self, worker: QObject, completed: Callable[..., None]) -> None:
        self._thread = QThread(self)
        self._worker = worker
        worker.moveToThread(self._thread)
        self._thread.started.connect(getattr(worker, "run"))
        if isinstance(worker, QueryWorker):
            worker.completed.connect(completed)
            worker.failed.connect(self._failed)
            worker.completed.connect(self._thread.quit)
            worker.failed.connect(self._thread.quit)
        else:
            worker.completed.connect(completed)  # type: ignore[attr-defined]
            worker.failed.connect(self._failed)  # type: ignore[attr-defined]
            worker.completed.connect(self._thread.quit)  # type: ignore[attr-defined]
            worker.failed.connect(self._thread.quit)  # type: ignore[attr-defined]
        self._thread.finished.connect(worker.deleteLater)
        self._thread.finished.connect(self._clear_worker)
        self._thread.start()

    @Slot(object, object)
    def _query_completed(self, page: HistoryPage, chart_rows: list[tuple[object, ...]]) -> None:
        self.total_rows = page.total_rows
        self.model.set_rows(page.rows)
        self._chart_rows = chart_rows
        self._update_charts()
        pages = max(1, math.ceil(self.total_rows / self.PAGE_SIZE))
        self.page_label.setText(f"Page {self.page + 1} / {pages} ({self.total_rows} rows)")
        self.status_label.setText("History loaded")
        self._set_controls_enabled(True)

    @Slot(str)
    def _failed(self, message: str) -> None:
        self.model.set_rows([])
        self.status_label.setText(f"Unable to read history: {message}")
        self._set_controls_enabled(True)

    @Slot()
    def _clear_worker(self) -> None:
        self._thread = None
        self._worker = None

    def _set_controls_enabled(self, enabled: bool) -> None:
        for control in (self.apply_button, self.prev_button, self.next_button, self.export_view_button, self.export_selected_button, self.export_all_button): control.setEnabled(enabled)

    @Slot(str)
    def _update_charts(self, metric: str | None = None) -> None:
        metric = metric or self.metric_combo.currentText()
        rows = getattr(self, "_chart_rows", [])
        self.five_chart.set_data(rows, metric)
        self.weekly_chart.set_data(rows, metric)

    @Slot()
    def _export(self, kind: str) -> None:
        path_text, _ = QFileDialog.getSaveFileName(self, "Export history", "usage_history.csv", "CSV files (*.csv)")
        if not path_text:
            return
        if kind == "selected":
            selected_ids = self.model.selected_ids(self.table.selectionModel().selectedRows())
            if not selected_ids:
                QMessageBox.information(self, "Export history", "Select one or more rows first.")
                return
            query: HistoryQuery | None = None
        elif kind == "all":
            selected_ids, query = None, None
        else:
            selected_ids, query = None, self._query()
        self.status_label.setText("Exporting…")
        self._set_controls_enabled(False)
        self._start_worker(ExportWorker(self.service, Path(path_text), query, selected_ids), self._export_completed)

    @Slot(int)
    def _export_completed(self, count: int) -> None:
        self.status_label.setText(f"Exported {count} rows as UTF-8 CSV")
        self._set_controls_enabled(True)

    def closeEvent(self, event: object) -> None:  # noqa: N802
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)
        event.accept()  # type: ignore[union-attr]
