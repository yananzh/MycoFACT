"""BLAST 命中表格（§7.2 P3）：accession / 标题 / pident / qcovs / 长度比 /
**行内单选框**（点选即选为参考，默认第一行=推荐）。

推荐行用整行淡蓝底标示（§6.1 排序第一名），Use 列的单选框默认勾选该行；
长度比 = 参考长度 / 查询长度，约 1.0–1.5 为推荐区间（§6.1 长度偏好）。
"""
import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QHeaderView, QRadioButton,
                             QTableWidget, QTableWidgetItem)

# 老式 NCBI 标题前缀 "gi|1779767538|gb|MK967294.1|" —— accession 已单列展示，
# 显示时剥掉以留出有效描述空间（tooltip 保留原始全文）
_GI_PREFIX = re.compile(r"^gi\|\d+\|[A-Za-z_]+\|[^|\s]+\|\s*")


def _fmt_title(title: str, limit: int = 64) -> str:
    t = _GI_PREFIX.sub("", title)
    return t if len(t) <= limit else t[:limit - 1] + "…"


def _title_tooltip(title: str, width: int = 78, max_chars: int = 800) -> str:
    """标题 tooltip：GenBank 定义行可能极长（基因组记录可达数百字符），单行
    tooltip 会横跨屏幕，按宽度折行后才是可读的多行块；过长部分截断。"""
    import textwrap
    t = _GI_PREFIX.sub("", title).strip()
    if len(t) > max_chars:
        t = t[:max_chars].rstrip() + "…"
    return "\n".join(textwrap.wrap(t, width=width)) or t


class HitTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 6, parent)
        self.setHorizontalHeaderLabels(["accession", "Title", "Ident %", "Cover %",
                                        "Ratio", "Use"])
        self.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)   # 与单元格左对齐一致
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in (2, 3, 4):   # 数字列按内容自适应：表头文字任何字体下都完整可见
            self.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self.setColumnWidth(5, 46)      # Use
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
            ratio = (h.subject_len / query_len) if query_len and h.subject_len else 0.0
            display_title = _fmt_title(h.title)
            title_item = QTableWidgetItem(display_title)
            if _GI_PREFIX.sub("", h.title).strip() != display_title:
                title_item.setToolTip(_title_tooltip(h.title))   # 仅在显示被截断时给全文
            items = [
                QTableWidgetItem(h.accession),
                title_item,
                QTableWidgetItem(f"{h.pident:.2f}"),
                QTableWidgetItem(f"{h.qcovs:.1f}"),
                QTableWidgetItem(f"{ratio:.2f}"),
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
            self.setCellWidget(row, 5, radio)
            self._radios.append(radio)
        if not self._radios:
            return
        if chosen:
            # 已选 accession 在命中列表内 → 勾选该行（触发一次 on_select，值不变）；
            # 不在列表内（弹窗手填的直接下载 accession）→ 不勾选、不覆盖已有选择
            if chosen in self._accessions:
                self._radios[self._accessions.index(chosen)].setChecked(True)
            return
        self._radios[0].setChecked(True)   # 无记录时默认推荐行

    def mark_recommended(self, row: int):
        """排序第一名：整行淡蓝底（§6.1）。推荐说明并入既有 tooltip——不能覆盖
        Title 列的全文与 Ratio 列的窗口截取说明；重复调用不叠加。"""
        if row < 0 or row >= self.rowCount():
            return
        tip = "Recommended - top-ranked hit by identity, coverage and length"
        for col in range(self.columnCount()):
            item = self.item(row, col)
            if item is None:
                continue
            item.setBackground(QColor("#eaf2fc"))
            existing = item.toolTip()
            if tip in existing:
                continue
            item.setToolTip(f"{tip}\n\n{existing}" if existing else tip)

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
