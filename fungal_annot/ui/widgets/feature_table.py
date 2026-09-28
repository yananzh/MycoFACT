"""Feature 编辑表格（§7.2 P4）：可编辑坐标/feature key/qualifier，修改后由页面
触发即时重验。

坐标列格式："<1..300, 401..852"（升序区段，'<'/'> ' 前缀表示该端 partial）；
qualifier 列格式：每行 "key: value"。解析失败抛 ValueError 并定位行号。
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QHeaderView, QTableWidget,
                             QTableWidgetItem)

from ...core.models import Feature, FeaturePart

_TYPE_COLORS = {"CDS": "#1f6cb8", "gene": "#1a7f37", "source": "#57606a",
                "rRNA": "#8250df", "tRNA": "#8250df"}


def _mono_font():
    from PyQt6.QtGui import QFont
    f = QFont("Consolas")
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


_COL_TYPES = ["Type", "Strand", "Coordinates", "Qualifiers"]


def _coords_text(feat: Feature) -> str:
    segs = []
    for p in feat.parts:
        s = (f"<{p.start}" if p.partial_low else str(p.start))
        e = (f">{p.end}" if p.partial_high else str(p.end))
        segs.append(f"{s}..{e}")
    return ", ".join(segs)


def _quals_text(feat: Feature) -> str:
    lines = []
    for k, vals in feat.qualifiers.items():
        for v in vals:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def parse_coords(text: str) -> list[FeaturePart]:
    parts = []
    for seg in text.split(","):
        seg = seg.strip()
        if not seg:
            continue
        pl = seg.startswith("<")
        ph = seg.endswith(">")
        body = seg.strip("<>")
        if ".." not in body:
            raise ValueError(f"Coordinate segment '{seg}' is missing '..'")
        a, b = body.split("..", 1)
        try:
            start, end = int(a), int(b)
        except ValueError as ex:
            raise ValueError(f"Coordinate segment '{seg}' has non-integer bounds") from ex
        if start > end:
            raise ValueError(f"Coordinate segment '{seg}' start > end")
        parts.append(FeaturePart(start=start, end=end,
                                 partial_low=pl, partial_high=ph))
    if not parts:
        raise ValueError("Coordinates are empty")
    return parts


def parse_quals(text: str) -> dict:
    quals: dict[str, list[str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for sep in (": ", ":", "="):
            if sep in line:
                k, v = line.split(sep, 1)
                quals.setdefault(k.strip(), []).append(v.strip())
                break
        else:
            raise ValueError(f"Qualifier line '{line}' is missing ': ' or '=' separator")
    return quals


class FeatureTable(QTableWidget):
    edited = pyqtSignal()       # 用户编辑（含增删行）后发出，页面据此防抖重验

    def __init__(self, parent=None):
        super().__init__(0, len(_COL_TYPES), parent)
        self.setHorizontalHeaderLabels(_COL_TYPES)
        self.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # 列头就地解释（替代散落的 ? 帮助按钮）
        self.horizontalHeaderItem(0).setToolTip("Feature key: CDS, gene, rRNA ...")
        self.horizontalHeaderItem(1).setToolTip("Strand: + forward, - reverse complement")
        self.horizontalHeaderItem(2).setToolTip(
            "GenBank ranges, e.g. <1..300, 401..520 - '<' / '>' mark partial ends "
            "(normal for PCR amplicons); commas separate exons")
        self.horizontalHeaderItem(3).setToolTip("One qualifier per line, key: value "
                                                "(gene, product, codon_start ...)")
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.setColumnWidth(0, 110)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.setColumnWidth(2, 220)
        self._loading = False
        self.cellChanged.connect(self._emit_edited)
        self.set_editable(True)

    def set_editable(self, editable: bool):
        """项目加载态（无比对上下文）时禁编辑，避免改了也无法重验。"""
        if editable:
            self.setEditTriggers(
                QAbstractItemView.EditTrigger.DoubleClicked
                | QAbstractItemView.EditTrigger.SelectedClicked
                | QAbstractItemView.EditTrigger.EditKeyPressed)
        else:
            self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    def _emit_edited(self, _row, _col):
        if not self._loading:
            self.edited.emit()

    def build_from_features(self, features):
        self._loading = True
        self.setRowCount(0)
        for feat in features:
            row = self.rowCount()
            self.insertRow(row)
            strand = "+" if feat.strand > 0 else "-"
            type_item = QTableWidgetItem(feat.ftype)
            type_item.setForeground(QColor(_TYPE_COLORS.get(feat.ftype, "#24292f")))
            type_item.setFont(_mono_font())
            self.setItem(row, 0, type_item)
            self.setItem(row, 1, QTableWidgetItem(strand))
            self.setItem(row, 2, QTableWidgetItem(_coords_text(feat)))
            self.setItem(row, 3, QTableWidgetItem(_quals_text(feat)))
            if feat.ftype == "source":
                # source 坐标固定为全长，禁止编辑链/坐标（§2.4）
                for col in (1, 2):
                    item = self.item(row, col)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._loading = False

    def add_feature(self, ftype: str, coords: str, strand: str = "+") -> int:
        """插入一行待编辑的 feature（默认值由页面给定），返回新行号。"""
        self._loading = True
        row = self.rowCount()
        self.insertRow(row)
        type_item = QTableWidgetItem(ftype)
        type_item.setForeground(QColor(_TYPE_COLORS.get(ftype, "#24292f")))
        type_item.setFont(_mono_font())
        self.setItem(row, 0, type_item)
        self.setItem(row, 1, QTableWidgetItem(strand))
        self.setItem(row, 2, QTableWidgetItem(coords))
        self.setItem(row, 3, QTableWidgetItem(""))
        self._loading = False
        self.setCurrentCell(row, 0)
        return row

    def selected_rows(self) -> list[int]:
        """当前选中行号（倒序，便于安全删除）。"""
        return sorted({i.row() for i in self.selectedIndexes()}, reverse=True)

    def remove_rows(self, rows: list[int]) -> str | None:
        """删除指定行；source 行不可删（.tbl/.fsa 生成依赖它），返回原因或 None。"""
        for r in rows:
            item = self.item(r, 0)
            if item is not None and item.text().strip() == "source":
                return ("The source row cannot be deleted - "
                        "edit its qualifiers instead.")
        self._loading = True
        for r in rows:
            self.removeRow(r)
        self._loading = False
        return None

    def to_features(self) -> list[Feature]:
        out = []
        for row in range(self.rowCount()):
            try:
                ftype = self.item(row, 0).text().strip()
                strand_text = self.item(row, 1).text().strip()
                coords = self.item(row, 2).text()
                quals = self.item(row, 3).text()
            except AttributeError as ex:
                raise ValueError(f"Row {row + 1} has empty cells") from ex
            if not ftype:
                raise ValueError(f"Row {row + 1} is missing a feature type")
            if strand_text not in ("+", "-"):
                raise ValueError(f"Row {row + 1}: strand must be + or -")
            try:
                parts = parse_coords(coords)
                quals_d = parse_quals(quals)
            except ValueError as ex:
                raise ValueError(f"Row {row + 1} ({ftype}): {ex}") from ex
            out.append(Feature(ftype=ftype, strand=1 if strand_text == "+" else -1,
                               parts=parts, qualifiers=quals_d))
        return out
