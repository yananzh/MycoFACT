"""P5 导出页（§7.2）：汇总表、输出目录、导出（红灯未确认拦截）。

BankIt 门户模式：.tbl 只含 gene/CDS 等 feature（source 由门户表单采集），
因此 table2asn 预检不再适用，已随自包含模式一并移除。
"""
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from ...services.pipeline import write_outputs
from ..widgets.help import MARKER_HINT, STATUS_COLOR, STATUS_MARK

_N_COLS = 8


class PageExport(QWidget):
    title = "4. Export Results"

    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.table = QTableWidget(0, _N_COLS)
        self.table.setHorizontalHeaderLabels(
            ["Seq ID", "Marker", "Status", "Features", "Reference", "Region",
             "Orientation", "Confirmed"])
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.horizontalHeaderItem(1).setToolTip(MARKER_HINT)
        self.table.horizontalHeader().setStretchLastSection(True)   # 表格铺满行宽
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)

        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Output directory:"))
        self.dir_edit = QLineEdit()
        self.dir_edit.setText(str(self.win.last_export_dir))
        dir_layout.addWidget(self.dir_edit, 1)
        b_dir = QPushButton("Browse...")
        b_dir.clicked.connect(self._pick_dir)
        dir_layout.addWidget(b_dir)
        layout.addLayout(dir_layout)

        btns = QHBoxLayout()
        self.b_export = QPushButton("Export all (.tbl + .fsa + report)")
        self.b_export.setObjectName("PrimaryButton")
        self.b_export.clicked.connect(self._export)
        b_open = QPushButton("Open output folder")
        b_open.clicked.connect(self._open_folder)
        btns.addWidget(self.b_export)
        btns.addWidget(b_open)
        btns.addStretch(1)
        layout.addLayout(btns)

        self.lbl_hint = QLabel(
            "Sequences marked 'Needs review' are blocked from export until confirmed on "
            "the Review page. The .tbl contains gene/CDS features only - organism and "
            "source modifiers are entered in the BankIt portal (GB2sequin-style "
            "workflow). Results were validated at annotation time and after every edit.")
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select output directory")
        if d:
            self.dir_edit.setText(d)

    def refresh(self):
        self.table.clearSpans()
        self.table.setRowCount(0)
        if not self.win.sequences:
            # 空状态：一行跨全表的引导，替代只有表头的空白
            self.table.setRowCount(1)
            self.table.setSpan(0, 0, 1, _N_COLS)
            hint = QTableWidgetItem(
                "Nothing here yet - import and annotate sequences in steps 1-3, "
                "then the export summary fills in")
            hint.setFlags(hint.flags() & ~Qt.ItemFlag.ItemIsEditable)
            hint.setForeground(QColor("#8b949e"))
            self.table.setItem(0, 0, hint)
        for s in self.win.sequences:
            res = self.win.results.get(s.seq_id)
            row = self.table.rowCount()
            self.table.insertRow(row)
            if res is None:
                values = [s.seq_id, s.gene_type or "auto-detect", "○ not annotated",
                          "-", "-", "-", "-", "-"]
                for col, text in enumerate(values):
                    self.table.setItem(row, col, QTableWidgetItem(text))
                continue
            p = res.provenance
            status_item = QTableWidgetItem(
                STATUS_MARK.get(res.status, res.status))
            status_item.setForeground(
                QColor(STATUS_COLOR.get(res.status, "#24292f")))
            confirmed = bool(self.win.confirmed.get(s.seq_id))
            conf_item = QTableWidgetItem("Yes" if confirmed else "No")
            # 只有"红灯未确认"的 No 是阻断性的，标红；其余中性灰
            conf_item.setForeground(
                QColor(STATUS_COLOR["red"])
                if res.status == "red" and not confirmed else QColor("#57606a"))
            # Seq ID / Marker / Features / Reference / Region / Orientation 按列布局，
            # Status(2) 与 Confirmed(7) 两列带颜色单独填
            plain = [s.seq_id, s.gene_type, str(len(res.features)),
                     p.reference or "-", p.region or "-", p.orientation]
            for col, text in zip((0, 1, 3, 4, 5, 6), plain):
                self.table.setItem(row, col, QTableWidgetItem(text))
            self.table.setItem(row, 2, status_item)
            self.table.setItem(row, 7, conf_item)
        # 无结果时禁用导出（点击才弹提示没有意义）
        has_results = bool(self.win.results)
        self.b_export.setEnabled(has_results)
        self.b_export.setToolTip("" if has_results else
                                 "Nothing to export yet - annotate sequences in "
                                 "steps 1-3 first")

    def _export(self):
        blocked = [sid for sid, res in self.win.results.items()
                   if res.status == "red" and not self.win.confirmed.get(sid)]
        if blocked:
            QMessageBox.warning(
                self, "Export blocked",
                "These RED sequences lack manual confirmation and cannot be exported:\n"
                + "\n".join(blocked)
                + "\n\nUse the 'Confirm for export' button on the Review page.")
            return
        if not self.win.results:
            QMessageBox.information(self, "No results", "Nothing to export yet.")
            return
        out = self.dir_edit.text().strip()
        if not out:
            QMessageBox.warning(self, "Missing directory", "Select an output directory.")
            return
        inputs = list(self.win.sequences)
        written = write_outputs(list(self.win.results.values()), out, inputs)
        self.win.last_export_dir = out
        self.win.exported = True
        self.win.update_summary()
        self.win.log(f"Exported {len(written)} file(s) to {out}")
        QMessageBox.information(self, "Export done",
                                "Written:\n" + "\n".join(written))

    def _open_folder(self):
        import os
        out = self.dir_edit.text().strip()
        if out and os.path.isdir(out):
            QDesktopServices.openUrl(QUrl.fromLocalFile(out))
        else:
            QMessageBox.information(self, "Folder not found",
                                    f"The directory does not exist yet:\n{out or '(empty)'}")
