"""可停靠日志面板（§7.1）。"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget, QPlainTextEdit


class LogPanel(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Log", parent)
        self.edit = QPlainTextEdit()
        self.edit.setReadOnly(True)
        self.edit.setMaximumBlockCount(5000)
        self.setWidget(self.edit)
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea
                             | Qt.DockWidgetArea.TopDockWidgetArea)

    def append(self, text: str):
        self.edit.appendPlainText(text)
