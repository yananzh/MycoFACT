"""顶部水平步骤条（Phase 2 步骤检查条）。

四个步骤等宽平铺于窗口顶部；点击已解锁的步骤切换页面，点在锁定的步骤上
只记录原因不切换（步骤状态由主窗口给出）。

步骤块的底色/字色由主窗口写入 item 的 Background/Foreground/Font 角色，这里
用委托自绘：走 QSS 的 ::item 规则时 Qt 会忽略 item 背景色，当前步骤会变成
白字透明底而看不见。
"""
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFontMetrics
from PyQt6.QtWidgets import (QListView, QListWidget, QSizePolicy,
                             QStyle, QStyledItemDelegate)

CHIP_MARGIN = 3
HOVER_BG = "#eef1f4"
DEFAULT_FG = "#24292f"


class _StepChipDelegate(QStyledItemDelegate):
    """圆角步骤块：底色取 item 背景角色，文字居中并按需省略。"""

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), 34)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        rect = option.rect.adjusted(CHIP_MARGIN, CHIP_MARGIN, -CHIP_MARGIN, -CHIP_MARGIN)

        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        if isinstance(bg, QBrush) and bg.color().alpha() > 0:
            painter.setBrush(bg)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.setBrush(QColor(HOVER_BG))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 6, 6)

        font = index.data(Qt.ItemDataRole.FontRole) or option.font
        painter.setFont(font)
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        fg = fg.color() if isinstance(fg, QBrush) else QColor(fg or DEFAULT_FG)
        painter.setPen(fg)
        text = QFontMetrics(font).elidedText(
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
            Qt.TextElideMode.ElideRight, rect.width() - 8)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class StepBar(QListWidget):
    stepClicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavList")
        # 水平单行排列：LeftToRight + 不换行 + Static 移动（让 setGridSize 生效）
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)   # 状态色自绘，不用选中态
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(46)
        self.setSpacing(0)
        self.setItemDelegate(_StepChipDelegate(self))
        self.itemClicked.connect(lambda item: self.stepClicked.emit(self.row(item)))
        self._slot = QSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._uniform_slots()

    def _uniform_slots(self):
        """四步平分宽度：改写每个 item 的 sizeHint（ListMode 下 item 宽度取自它），
        窗口缩放时同步，长标题由委托省略号截断。"""
        count = self.count()
        if count == 0:
            return
        slot = QSize(max(110, self.viewport().width() // count),
                     self.viewport().height())
        if slot == self._slot:
            return
        self._slot = slot
        for i in range(count):
            self.item(i).setSizeHint(slot)
