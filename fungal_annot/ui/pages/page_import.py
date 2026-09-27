"""P1 序列导入页（§7.2）：拖放卡片为主视觉（Phase 2 新手引导）、序列表、
source 修饰符批量填写（默认折叠，应用前展开）。"""
import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QFrame,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from ...core.models import SeqInput
from ...core.presets import load_presets
from ..icons import icon

_SOURCE_FIELDS = [("organism", "organism (species)"),
                  ("strain", "strain (isolate no.)"),
                  ("country", "country (e.g. China: Yunnan)"),
                  ("collection_date", "collection_date (e.g. 2021-Mar)"),
                  ("isolated_from_source", "isolated_from_source (source)"),
                  ("lat_lon", "lat_lon (e.g. 30.5 N 114.3 E)"),
                  ("identified_by", "identified_by (determiner)")]


class DropCard(QFrame):
    """虚线拖放卡片：页面主视觉。点击 = 浏览文件；拖入 = 导入。"""

    clicked = pyqtSignal()
    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropCard")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = icon("fa5s.file-import", "#2D7DD2").pixmap(34, 34)
        self.icon_label.setPixmap(pm)
        self.main_label = QLabel("Drag & drop FASTA files here")
        self.main_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_label.setStyleSheet("font-size: 12pt; font-weight: 600; color: #24292f;")
        self.sub_label = QLabel("or click to browse — multi-file and multi-sequence supported")
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_label.setObjectName("Hint")
        layout.addWidget(self.icon_label)
        layout.addWidget(self.main_label)
        layout.addWidget(self.sub_label)

    def set_compact(self, compact: bool):
        """有序列后收缩为细条。"""
        self.setProperty("compact", "true" if compact else "false")
        self.icon_label.setVisible(not compact)
        self.sub_label.setVisible(not compact)
        self.main_label.setText("＋  Add more FASTA files (drag & drop or click)"
                                if compact else "Drag & drop FASTA files here")
        self.setMaximumHeight(64 if compact else 16777215)
        self.style().unpolish(self)
        self.style().polish(self)

    # ---- 交互 ----
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            self.setProperty("dragOver", "true")
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.setProperty("dragOver", "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent):
        self.setProperty("dragOver", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile() and os.path.splitext(u.toLocalFile())[1].lower()
                 in (".fasta", ".fa", ".fna", ".ffn", ".faa", ".txt")]
        if paths:
            self.filesDropped.emit(paths)


class PageImport(QWidget):
    title = "1. Import"

    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.drop_card = DropCard()
        self.drop_card.clicked.connect(self._add_files_dialog)
        self.drop_card.filesDropped.connect(self.add_fasta_paths)
        layout.addWidget(self.drop_card)

        row = QHBoxLayout()
        b_del = QPushButton(icon("fa5s.trash-alt"), "Remove selected")
        b_del.clicked.connect(self._remove_selected)
        b_clear = QPushButton(icon("fa5s.broom"), "Clear all")
        b_clear.setObjectName("DangerButton")
        b_clear.clicked.connect(self._clear)
        row.addWidget(b_del)
        row.addWidget(b_clear)
        row.addStretch(1)
        layout.addLayout(row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Seq ID (editable)", "Length", "Gene type"])
        self.table.setColumnWidth(0, 280)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)

        # source 修饰符：checkable GroupBox，取消勾选即折叠（Phase 2 新手引导）
        group = QGroupBox("Source modifiers — batch apply to all sequences (optional; §2.4)")
        group.setCheckable(True)
        group.setChecked(False)
        form = QFormLayout(group)
        self.source_edits = {}
        for key, label in _SOURCE_FIELDS:
            edit = QLineEdit()
            edit.setPlaceholderText({"country": "China: Yunnan",
                                     "collection_date": "2021-Mar",
                                     "lat_lon": "30.5 N 114.3 E"}.get(key, ""))
            self.source_edits[key] = edit
            form.addRow(label, edit)
        b_apply = QPushButton("Apply to all sequences")
        b_apply.clicked.connect(self._apply_source_to_all)
        form.addRow("", b_apply)
        layout.addWidget(group)

        self.preset_names = sorted(load_presets().keys())

    # ---- 添加/移除 ----
    def add_fasta_paths(self, paths):
        try:
            for path in paths:
                self.win.load_fasta_file(path)
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, "Import failed", str(ex))
        self.refresh()

    def refresh(self):
        self.drop_card.set_compact(len(self.win.sequences) > 0)
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for s in self.win.sequences:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(s.seq_id))
            self.table.setItem(row, 1, QTableWidgetItem(str(len(s.seq))))
            combo = QComboBox()
            combo.addItems(self.preset_names + ["Custom"])
            if s.gene_type in self.preset_names:
                combo.setCurrentText(s.gene_type)
            combo.currentTextChanged.connect(
                lambda text, sid=s.seq_id: self._on_gene_type(sid, text))
            self.table.setCellWidget(row, 2, combo)
        self.table.blockSignals(False)

    def _add_files_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select FASTA files", "",
            "FASTA (*.fasta *.fa *.fna *.ffn *.faa *.txt);;All files (*)")
        if paths:
            self.add_fasta_paths(paths)

    def _remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            sid = self.table.item(row, 0).text()
            self.win.remove_sequence(sid)
        self.refresh()

    def _clear(self):
        if self.win.sequences and QMessageBox.question(
                self, "Clear all", "Remove all imported sequences?") != QMessageBox.StandardButton.Yes:
            return
        self.win.sequences.clear()
        self.win.reset_results()
        self.refresh()

    def _on_item_changed(self, item):
        row = item.row()
        if row >= len(self.win.sequences):
            return
        s = self.win.sequences[row]
        if item.column() == 0:
            old = s.seq_id
            new = item.text().strip()
            if new and new != old:
                s.seq_id = new
                self.win.rename_sequence(old, new)

    def _on_gene_type(self, seq_id, text):
        self.win.set_gene_type(seq_id, "" if text == "Custom" else text)

    def _apply_source_to_all(self):
        quals = {k: e.text().strip() for k, e in self.source_edits.items()
                 if e.text().strip()}
        self.win.apply_source_to_all(quals)
        QMessageBox.information(self, "Applied",
                                f"Applied {len(quals)} modifier(s) to "
                                f"{len(self.win.sequences)} sequence(s)")
