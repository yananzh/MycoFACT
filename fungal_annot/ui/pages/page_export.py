"""P5 导出页（§7.2 + 多参考对比）：汇总表、输出目录、导出（红灯需确认后放行）。

每序列一个 .tbl，取其采纳（Adopted）的 variant，另加多记录汇总
all_features.tbl（全部序列的 >Feature 块合并，可整文件提交 BankIt）。

BankIt 门户模式：导出只写 .tbl（每条序列一个，含 gene/CDS 等 feature）；
organism 等来源信息在门户表单录入，因此 table2asn 预检不适用，已移除。
"""
import os

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from ...services.pipeline import write_outputs
from ..widgets.help import MARKER_HINT, STATUS_COLOR, STATUS_MARK, show_page_help

_N_COLS = 8


class PageExport(QWidget):
    title = "4. Export Results"
    help_key = "page_export"

    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.table = QTableWidget(0, _N_COLS)
        self.table.setHorizontalHeaderLabels(
            ["Seq ID", "Marker", "Status", "Features", "Reference", "Region",
             "Orientation", "Confirmed"])
        self.table.verticalHeader().setVisible(False)
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
        self.b_export = QPushButton("Export Feature Table")
        self.b_export.setObjectName("PrimaryButton")
        self.b_export.setToolTip("Write one five-column .tbl file per sequence, "
                                 "plus a combined all_features.tbl with all records")
        self.b_export.clicked.connect(self._export)
        b_open = QPushButton("Open output folder")
        b_open.clicked.connect(self._open_folder)
        b_help = QPushButton("Help")
        b_help.setToolTip("How to use this page: steps, terms, tips")
        b_help.clicked.connect(lambda: show_page_help("page_export", self))
        btns.addWidget(self.b_export)
        btns.addWidget(b_open)
        btns.addWidget(b_help)
        layout.addLayout(btns)

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
            variants = self.win.results.get(s.seq_id) or {}
            chosen_acc = self.win.chosen_accession(s.seq_id)
            res = variants.get(chosen_acc) if chosen_acc else None
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
                item = QTableWidgetItem(text)
                if len(variants) > 1:
                    item.setToolTip(f"{len(variants)} variants compared; exporting "
                                    f"the adopted one ({chosen_acc})")
                self.table.setItem(row, col, item)
            self.table.setItem(row, 2, status_item)
            self.table.setItem(row, 7, conf_item)
        # 无结果时禁用导出（点击才弹提示没有意义）
        has_results = any(self.win.results.values())
        self.b_export.setEnabled(has_results)
        self.b_export.setToolTip("" if has_results else
                                 "Nothing to export yet - annotate sequences in "
                                 "steps 1-3 first")

    def _export(self):
        # 红灯序列在导出时知情确认（Review 页原 Confirm 按钮已并入本弹窗）；
        # 只看采纳（导出）的 variant，未采纳 variant 供比选，不拦
        red_open = []
        for s in self.win.sequences:
            res = self.win.chosen_result(s.seq_id)
            if res is not None and res.status == "red" \
                    and not self.win.confirmed.get(s.seq_id):
                red_open.append(s.seq_id)
        if red_open:
            answer = QMessageBox.question(
                self, "Confirm export of red sequences",
                "These RED sequences have unfixed errors:\n"
                + "\n".join(red_open)
                + "\n\nExport them anyway? Only do this if you reviewed the "
                  "issues knowingly.")
            if answer != QMessageBox.StandardButton.Yes:
                return
            for sid in red_open:
                self.win.confirmed[sid] = True
                self.win.log(f"[{sid}] Manually confirmed at export")
            self.refresh()
        if not any(self.win.results.values()):
            QMessageBox.information(self, "No results", "Nothing to export yet.")
            return
        out = self.dir_edit.text().strip()
        if not out:
            QMessageBox.warning(self, "Missing directory", "Select an output directory.")
            return
        inputs = list(self.win.sequences)
        chosen_results = []
        for s in inputs:
            variants = self.win.results.get(s.seq_id) or {}
            if not variants:
                continue
            chosen_results.append(variants[self.win.chosen_accession(s.seq_id)])
        skipped: list[str] = []
        try:
            written = write_outputs(chosen_results, out, inputs,
                                    with_fsa=False, with_report=False,
                                    skipped=skipped)
        except OSError as ex:
            # 无效盘符/只读目录等写盘失败：弹窗告知，而非全局 excepthook 兜底成
            # 状态栏一行 traceback 尾巴
            QMessageBox.warning(self, "Export failed",
                                f"Could not write to '{out}':\n{ex}")
            return
        self.win.last_export_dir = out
        self.win.exported = True
        self.win.update_summary()
        msg = (f"Wrote {len(written)} .tbl file(s) to:\n{out}\n\n"
               + "\n".join(os.path.basename(w) for w in written))
        if skipped:
            # 零产出序列不写文件（只有 >Feature 头的表 BankIt 会拒收），
            # 但必须让用户知道是哪些序列、以及数量对不上
            msg += ("\n\nNo feature table written for: " + ", ".join(skipped)
                    + "\n(no feature could be transferred - check the reference "
                      "and the gene preset for these sequences)")
        self.win.log(f"Exported {len(written)} .tbl file(s) to {out}"
                     + (f" ({len(skipped)} sequence(s) produced no feature table)"
                        if skipped else ""))
        QMessageBox.information(self, "Export done", msg)

    def _open_folder(self):
        out = self.dir_edit.text().strip()
        if out and os.path.isdir(out):
            QDesktopServices.openUrl(QUrl.fromLocalFile(out))
        else:
            QMessageBox.information(self, "Folder not found",
                                    f"The directory does not exist yet:\n{out or '(empty)'}")
