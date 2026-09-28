"""P5 导出页（§7.2）：汇总表、输出目录、导出（红灯未确认拦截）。

BankIt 门户模式：.tbl 只含 gene/CDS 等 feature（source 由门户表单采集），
因此 table2asn 预检不再适用，已随自包含模式一并移除。
"""
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from ...services.pipeline import write_outputs
from ..icons import icon


class PageExport(QWidget):
    title = "5. Export"         # 步骤条标签：水平等宽排布下需要短标签

    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Seq ID", "Gene type", "Status", "Features", "Reference", "Region",
             "Orientation", "Confirmed"])
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
        b_refresh = QPushButton("Refresh summary")
        b_refresh.clicked.connect(self.refresh)
        b_export = QPushButton(icon("fa5s.file-export", "#ffffff"),
                               "Export all (.tbl + .fsa + report)")
        b_export.setObjectName("PrimaryButton")
        b_export.clicked.connect(self._export)
        self.b_open_folder = QPushButton(icon("fa5s.folder-open"), "Open output folder")
        self.b_open_folder.clicked.connect(self._open_folder)
        btns.addWidget(b_refresh)
        btns.addWidget(b_export)
        btns.addWidget(self.b_open_folder)
        btns.addStretch(1)
        layout.addLayout(btns)

        self.lbl_hint = QLabel(
            "Red sequences without manual confirmation are blocked from export (§7.2 P5). "
            "The .tbl contains gene/CDS features only - organism and source modifiers are "
            "entered in the BankIt portal (GB2sequin-style workflow). Results were "
            "validated at annotation time and after every edit.")
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select output directory")
        if d:
            self.dir_edit.setText(d)

    def refresh(self):
        self.table.setRowCount(0)
        for s in self.win.sequences:
            res = self.win.results.get(s.seq_id)
            row = self.table.rowCount()
            self.table.insertRow(row)
            if res is None:
                for col, text in enumerate([s.seq_id, s.gene_type, "not annotated", "-", "-", "-", "-", "-"]):
                    self.table.setItem(row, col, QTableWidgetItem(text))
                continue
            p = res.provenance
            confirmed = "Yes" if self.win.confirmed.get(s.seq_id) else "No"
            values = [s.seq_id, s.gene_type, res.status, str(len(res.features)),
                      p.reference or "-", p.region or "-", p.orientation, confirmed]
            for col, text in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(text))

    def _export(self):
        blocked = [sid for sid, res in self.win.results.items()
                   if res.status == "red" and not self.win.confirmed.get(sid)]
        if blocked:
            QMessageBox.warning(
                self, "Export blocked",
                "These RED sequences lack manual confirmation and cannot be exported (§7.2 P4):\n"
                + "\n".join(blocked)
                + "\n\nUse the 'Manual confirm' button on the Review page.")
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
