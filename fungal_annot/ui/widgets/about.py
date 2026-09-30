"""About 弹窗（原生控件，简洁风）+ 手动更新检查（About 弹窗内按钮）。

更新流程：CheckUpdatesRunnable 在 QThreadPool 后台跑 core.updater.check_for_update，
信号回 UI 线程——已最新就地提示，有新版弹 UpdateAvailableDialog（一键打开 Releases
下载页），失败 QMessageBox 简短提示；界面全程不阻塞，失败不影响其他功能。
"""
import os
import traceback

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
                             QLabel, QMessageBox, QPushButton, QVBoxLayout)

from ...paths import resource_path
from ..icons import ACCENT, icon
from .help import DISCLAIMER

REPO_URL = "https://github.com/yananzh/MycoFACT"


def _logo_pixmap(size: int):
    """应用 logo 位图；图标资源缺失时退回 qtawesome 的 dna 占位图标。"""
    path = resource_path("fungal_annot", "resources", "icons",
                         "mycofact_256.png")
    if os.path.isfile(path):
        return QPixmap(path).scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
    return icon("fa5s.dna", color=ACCENT).pixmap(size, size)


# ---- About 弹窗 -------------------------------------------------------------
class AboutDialog(QDialog):
    """图标 + 名称/版本 + 一句简介 + 仓库链接 + 居中更新按钮 + 底部免责声明。"""

    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self._version = version
        self._check_run = None          # 持有在途 QRunnable 引用，防执行中被 GC
        self.setWindowTitle("About")
        self.setMinimumWidth(400)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 14)
        v.setSpacing(10)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(_logo_pixmap(44))
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        title = QLabel("MycoFACT")
        title.setObjectName("AboutTitle")
        names.addWidget(title)
        sub = QLabel("Fungal Feature Annotation & Comparison Tool")
        sub.setObjectName("Hint")
        names.addWidget(sub)
        head.addLayout(names, 1)
        v.addLayout(head)

        ver = QLabel(f"Version {version}")
        ver.setObjectName("AboutVersion")
        v.addWidget(ver)

        desc = QLabel("BLAST a close reference, transfer its annotation, "
                      "review, and export BankIt-ready five-column .tbl "
                      "feature tables.")
        desc.setWordWrap(True)
        v.addWidget(desc)

        self.update_status = QLabel("")
        self.update_status.setObjectName("Hint")
        self.update_status.setWordWrap(True)
        v.addWidget(self.update_status)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        v.addWidget(sep)

        row = QHBoxLayout()
        self.b_check = QPushButton("Check for Updates")
        self.b_check.setObjectName("PrimaryButton")
        self.b_check.clicked.connect(self.check_updates)
        row.addWidget(self.b_check)
        b_repo = QPushButton("GitHub")
        b_repo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        row.addWidget(b_repo)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        v.addLayout(row)

        tip = QLabel(DISCLAIMER)
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        v.addWidget(tip)

    # ---- 更新检查 ----
    def check_updates(self):
        """后台查询 GitHub Releases；结果由 _on_check_done/_on_check_failed 呈现。"""
        from ...core import updater
        if self._check_run is not None:      # 已有检查在途
            return
        self.b_check.setEnabled(False)
        self.update_status.setText("Checking for updates…")
        self._check_run = CheckUpdatesRunnable(self._version)
        self._check_run.signals.done.connect(self._on_check_done)
        self._check_run.signals.failed.connect(self._on_check_failed)
        QThreadPool.globalInstance().start(self._check_run)

    def _finish_check(self):
        self._check_run = None
        self.b_check.setEnabled(True)

    def _on_check_done(self, info):
        self._finish_check()
        if info is None:
            self.update_status.setText(
                f"You're up to date (Version {self._version}).")
            return
        self.update_status.setText("")
        UpdateAvailableDialog(info, self._version, self).exec()

    def _on_check_failed(self, message):
        self._finish_check()
        self.update_status.setText("")
        QMessageBox.warning(self, "Check for updates",
                            f"Could not check for updates.\n\n{message}")


class UpdateAvailableDialog(QDialog):
    """发现新版本：版本对照 + release notes 摘录（前 12 行）+ 打开下载页。"""

    MAX_NOTE_LINES = 12

    def __init__(self, info: dict, current_version: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update available")
        self.setMinimumWidth(440)
        self._url = info.get("url") or REPO_URL + "/releases"

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 14)
        v.setSpacing(10)

        title = QLabel(f"Version {info.get('version', '?')} is available")
        title.setObjectName("AboutTitle")
        v.addWidget(title)
        sub = QLabel(f"You are running Version {current_version}.")
        sub.setObjectName("Hint")
        v.addWidget(sub)

        notes = (info.get("notes") or "").strip()
        if notes:
            lines = [ln for ln in notes.splitlines() if ln.strip()]
            shown = "\n".join(lines[:self.MAX_NOTE_LINES])
            if len(lines) > self.MAX_NOTE_LINES:
                shown += "\n…"
            box = QLabel(shown)
            box.setWordWrap(True)
            box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v.addWidget(box, 1)

        row = QHBoxLayout()
        b_dl = QPushButton("Download from GitHub")
        b_dl.setObjectName("PrimaryButton")
        b_dl.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._url)))
        row.addWidget(b_dl)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        v.addLayout(row)


# ---- 后台任务 ---------------------------------------------------------------
class _CheckSignals(QObject):
    done = pyqtSignal(object)   # dict（有新版）或 None（已最新）
    failed = pyqtSignal(str)    # 用户可读的错误摘要


class CheckUpdatesRunnable(QRunnable):
    """后台执行一次 check_for_update；调用方须持有本对象引用直至信号返回
    （PyQt QRunnable 执行中被 GC 会段错误，见 services/worker.py 同款注释）。"""

    def __init__(self, current_version: str):
        super().__init__()
        self.current_version = current_version
        self.signals = _CheckSignals()

    def run(self):
        from ...core import updater
        try:
            self.signals.done.emit(
                updater.check_for_update(self.current_version))
        except Exception as ex:
            self.signals.failed.emit(str(ex) or repr(ex))


def build_about_dialog(version: str, parent=None) -> QDialog:
    """构建 About 弹窗（保持旧签名：菜单与测试共用）。"""
    return AboutDialog(version, parent)
