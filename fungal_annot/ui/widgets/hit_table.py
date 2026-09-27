"""BLAST 命中表格（§7.2 P3）：accession / 标题 / pident / qcovs / 长度比 / 标星。

标星：★=模式菌株或培养物记录（title 线索），R=RefSeq（仅 rRNA 类预设加分）。
长度比 = 参考长度 / 查询长度，约 1.0–1.5 为推荐区间（§6.1 长度偏好）。
"""
from PyQt6.QtWidgets import (QAbstractItemView, QHeaderView, QTableWidget,
                             QTableWidgetItem)
from PyQt6.QtGui import QColor

_CULTURE = ("CBS", "ATCC", "CMCC", "NRRL", "ex-type", "ex type", "holotype",
            "neotype", "epitype", "paratype", "type strain")


def _fmt_title(title: str, limit: int = 64) -> str:
    return title if len(title) <= limit else title[:limit - 1] + "…"


class HitTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 6, parent)
        self.setHorizontalHeaderLabels(["accession", "Title", "pident %", "qcovs %",
                                        "Len ratio", "Marker"])
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def populate(self, hits, query_len: int, preset_kind: str = ""):
        self.setRowCount(0)
        for h in hits or []:
            row = self.rowCount()
            self.insertRow(row)
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
            if hits[row].qcovs >= 99.95:
                qcovs_item.setForeground(QColor("#1a7f37"))

    def mark_recommended(self, row: int):
        """排序第一名：整行淡蓝底 + 标题列加推荐徽章（§6.1）。"""
        if row < 0 or row >= self.rowCount():
            return
        title_item = self.item(row, 1)
        title_item.setText("★ Recommended — " + title_item.text())
        for col in range(self.columnCount()):
            self.item(row, col).setBackground(QColor("#eaf2fc"))

    def current_accession(self) -> str | None:
        row = self.currentRow()
        if row < 0:
            return None
        item = self.item(row, 0)
        return item.text() if item else None
