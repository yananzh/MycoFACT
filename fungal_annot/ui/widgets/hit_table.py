"""BLAST 命中表格（§7.2 P3）：accession / 标题 / pident / qcovs / 长度比 / 标记 /
**行内单选框**（点选即选为参考，默认第一行=推荐）。

标星：★=模式菌株或培养物记录（title 线索），R=RefSeq（仅 rRNA 类预设加分）。
长度比 = 参考长度 / 查询长度，约 1.0–1.5 为推荐区间（§6.1 长度偏好）。
"""
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QHeaderView, QRadioButton,
                             QTableWidget, QTableWidgetItem)

_CULTURE = ("CBS", "ATCC", "CMCC", "NRRL", "ex-type", "ex type", "holotype",
            "neotype", "epitype", "paratype", "type strain")


def _fmt_title(title: str, limit: int = 64) -> str:
    return title if len(title) <= limit else title[:limit - 1] + "…"


class HitTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 7, parent)
        self.setHorizontalHeaderLabels(["accession", "Title", "pident %", "qcovs %",
                                        "Len ratio", "Marker", "Use"])
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.setColumnWidth(6, 46)
        self._on_select = None
        self._radios: list[QRadioButton] = []
        self._accessions: list[str] = []

    def populate(self, hits, query_len: int, on_select=None, chosen: str | None = None):
        """填充命中表。chosen 为该序列已选 accession；无记录时默认选第一行，
        默认选择完成后回调 on_select(第一行 accession) 一次。"""
        self._on_select = on_select
        self.setRowCount(0)          # 顺带清掉旧行的单选框控件
        self._radios = []
        self._accessions = []
        for h in hits or []:
            row = self.rowCount()
            self.insertRow(row)
            self._accessions.append(h.accession)
            star = "★" if h.flags.get("culture") else ""
            ref = "R" if h.flags.get("refseq") else ""
            marker = (star + ref).strip() or "—"
            ratio = (h.subject_len / query_len) if query_len and h.subject_len else 0.0
            items = [
                QTableWidgetItem(h.accession),
                QTableWidgetItem(_fmt_title(h.title)),
                QTableWidgetItem(f"{h.pident:.2f}"),
                QTableWidgetItem(f"{h.qcovs:.1f}"),
                QTableWidgetItem(f"{ratio:.2f}"),
                QTableWidgetItem(marker),
            ]
            for col, item in enumerate(items):
                self.setItem(row, col, item)
            # 长度比着色：1.0–1.5 绿（推荐区间），>2 黄（基因组级）
            ratio_item = self.item(row, 4)
            if 1.0 <= ratio <= 1.5:
                ratio_item.setForeground(QColor("#1a7f37"))
            elif ratio > 2.0:
                ratio_item.setForeground(QColor("#9a6700"))
                ratio_item.setToolTip("Much longer than query: genome-scale record; "
                                      "windowed fetch will be used")
            qcovs_item = self.item(row, 3)
            if h.qcovs >= 99.95:
                qcovs_item.setForeground(QColor("#1a7f37"))
            # 行内单选框：构造时不勾选，循环结束后统一勾默认行，
            # 由 toggled 回调精确触发一次 on_select
            radio = QRadioButton()
            radio.setToolTip("Use this hit as the reference")
            radio.toggled.connect(lambda on, r=radio, i=row: self._radio_toggled(on, r, i))
            self.setCellWidget(row, 6, radio)
            self._radios.append(radio)
        if not self._radios:
            return
        default_row = 0
        if chosen:
            for i, acc in enumerate(self._accessions):
                if acc == chosen:
                    default_row = i
                    break
        self._radios[default_row].setChecked(True)   # 触发一次 on_select

    def mark_recommended(self, row: int):
        """排序第一名：整行淡蓝底 + 标题列加推荐徽章（§6.1）。"""
        if row < 0 or row >= self.rowCount():
            return
        title_item = self.item(row, 1)
        title_item.setText("★ Recommended — " + title_item.text())
        for col in range(self.columnCount() - 1):    # 选择列不涂底色
            self.item(row, col).setBackground(QColor("#eaf2fc"))

    def select_accession(self, accession: str) -> bool:
        """勾选指定 accession 行的单选框；不在表中返回 False。"""
        for i, acc in enumerate(self._accessions):
            if acc == accession:
                self._radios[i].setChecked(True)
                return True
        return False

    def current_accession(self) -> str | None:
        row = self.currentRow()
        if row < 0:
            return None
        item = self.item(row, 0)
        return item.text() if item else None

    # ---- 内部 ----
    def _radio_toggled(self, on: bool, radio: QRadioButton, row: int):
        if not on:
            return
        for r in self._radios:               # 手动互斥（各单元格控件父级不同，自动互斥不可靠）
            if r is not radio and r.isChecked():
                r.blockSignals(True)
                r.setChecked(False)
                r.blockSignals(False)
        if self._on_select:
            self._on_select(self._accessions[row])
