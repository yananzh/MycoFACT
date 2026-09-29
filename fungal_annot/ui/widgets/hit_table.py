"""BLAST 命中表格（§7.2 P3）：accession / 标题 / pident / qcovs / 长度比 /
**行内复选框**（勾选即参与对比注释，1-5 个，默认勾前 N=Settings 的 default_refs）。

推荐行用整行淡蓝底标示（§6.1 排序第一名）；长度比 = 参考长度 / 查询长度，
约 1.0–1.5 为推荐区间（§6.1 长度偏好）。
"""
import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QHeaderView,
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
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in (2, 3, 4):   # 数字列按内容自适应：表头文字任何字体下都完整可见
            self.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self.setColumnWidth(5, 46)      # Use
        self._on_toggle = None
        self._checks: list[QCheckBox] = []
        self._accessions: list[str] = []

    def populate(self, hits, query_len: int, on_toggle=None,
                 selected: list[str] | None = None):
        """填充命中表。selected 为该序列已选 accession 列表（勾选即参与对比）；
        勾选状态变化回调 on_toggle(accession, checked)，上限与默认选择由页面裁定。"""
        self._on_toggle = on_toggle
        self.setRowCount(0)          # 顺带清掉旧行的复选框控件
        self._checks = []
        self._accessions = []
        wanted = set(selected or [])
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
            # 行内复选框：勾选 = 该参考参与对比注释（页面裁定 1-5 上限）
            chk = QCheckBox()
            chk.setChecked(h.accession in wanted)
            chk.setToolTip("Compare annotation against this reference (up to 5)")
            chk.toggled.connect(lambda on, i=row: self._check_toggled(on, i))
            self.setCellWidget(row, 5, chk)
            self._checks.append(chk)

    def sync_checks(self, selected: list[str]):
        """把勾选状态统一同步回 selected 列表（页面拒绝某次勾选后回调撤回用）。"""
        wanted = set(selected or [])
        for row, acc in enumerate(self._accessions):
            if row >= len(self._checks):
                break
            chk = self._checks[row]
            if chk.isChecked() != (acc in wanted):
                chk.blockSignals(True)
                chk.setChecked(acc in wanted)
                chk.blockSignals(False)

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

    # ---- 内部 ----
    def _check_toggled(self, on: bool, row: int):
        if self._on_toggle:
            self._on_toggle(self._accessions[row], on)
