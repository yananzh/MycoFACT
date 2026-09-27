"""P2 BLAST 页（§7.2）：参数徽章、限速串行队列、进度/日志、可取消；
离线模式下跳过 BLAST 直接使用本地参考 GenBank。
Phase 2：主按钮状态驱动禁用（新手不点出错误）。"""
from PyQt6.QtWidgets import (QCheckBox, QFileDialog, QGroupBox, QHBoxLayout,
                             QLabel, QMessageBox, QProgressBar, QPushButton,
                             QVBoxLayout, QWidget)

from ...services.worker import BlastWorker
from ..icons import icon
from ..widgets.help import HelpButton


class PageBlast(QWidget):
    title = "2. BLAST / Reference"

    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ---- 参数徽章行 ----
        chips = QHBoxLayout()
        self.chip_db = QLabel("-")
        self.chip_db.setObjectName("Chip")
        self.chip_queue = QLabel("-")
        self.chip_queue.setObjectName("Chip")
        self.chip_mode = QLabel("ONLINE")
        self.chip_mode.setObjectName("ChipAccent")
        help_btn = HelpButton("identity")
        chips.addWidget(self.chip_db)
        chips.addWidget(self.chip_queue)
        chips.addWidget(self.chip_mode)
        chips.addStretch(1)
        chips.addWidget(help_btn)
        layout.addLayout(chips)

        offline_group = QGroupBox("Offline mode (no network / reference file known)")
        off_layout = QHBoxLayout(offline_group)
        self.chk_offline = QCheckBox("Use a local reference GenBank file (skip BLAST)")
        self.chk_offline.toggled.connect(self._toggle_offline)
        self.lbl_ref = QLabel("None selected")
        self.lbl_ref.setObjectName("Hint")
        b_pick = QPushButton("Browse...")
        b_pick.clicked.connect(self._pick_ref)
        off_layout.addWidget(self.chk_offline)
        off_layout.addWidget(self.lbl_ref, 1)
        off_layout.addWidget(b_pick)
        layout.addWidget(offline_group)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setObjectName("Hint")
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        btns = QHBoxLayout()
        self.b_start = QPushButton(icon("fa5s.play", "#ffffff"), "Start BLAST")
        self.b_start.setObjectName("PrimaryButton")
        self.b_start.clicked.connect(self._start)
        self.b_cancel = QPushButton("Cancel pending")
        self.b_cancel.clicked.connect(self._cancel)
        self.b_cancel.setEnabled(False)
        self.b_next = QPushButton("Next: Reference Selection →")
        self.b_next.clicked.connect(lambda: self.win.go_page(2))
        btns.addWidget(self.b_start)
        btns.addWidget(self.b_cancel)
        btns.addWidget(self.b_next)
        btns.addStretch(1)
        layout.addLayout(btns)
        layout.addStretch(1)

        self.chk_offline.setChecked(self.win.local_ref_text is not None)
        self._refresh()

    # ---- 状态刷新 ----
    def _refresh(self):
        cfg = self.win.make_config()
        n = len(self.win.sequences)
        offline = self.chk_offline.isChecked() and self.win.local_ref_text
        self.chip_db.setText(f"Database: {cfg.blast_db}")
        self.chip_queue.setText(
            f"{n} queued · ~{max(1, n * 3)} min" if n else "no sequences yet")
        self.chip_mode.setText("OFFLINE" if offline else "ONLINE")
        email_ok = bool(cfg.email)
        has_seqs = n > 0
        self.b_start.setEnabled(has_seqs and (offline or email_ok))
        if offline:
            self.b_start.setText("Next (offline, no BLAST needed)")
            self.lbl_hint.setText(f"{n} sequence(s) will be annotated against the local "
                                  "reference; typically a few seconds.")
        else:
            self.b_start.setText("Start BLAST")
            reason = ""
            if not has_seqs:
                reason = "Import FASTA files in step 1 first. "
            elif not email_ok:
                reason = "Set your NCBI contact email in toolbar Settings first. "
            self.lbl_hint.setText(reason + "Online BLAST takes ~1-5 min per sequence "
                                         "(serial, rate-limited queue).")
        self.b_start.setToolTip("" if self.b_start.isEnabled()
                                else reason.strip() or "not ready")

    def refresh(self):
        self._refresh()

    # ---- 离线参考 ----
    def _toggle_offline(self):
        if self.chk_offline.isChecked() and not self.win.local_ref_text:
            self._pick_ref()
        if not self.chk_offline.isChecked():
            self.win.local_ref_text = None
            self.win.local_ref_name = None
            self.lbl_ref.setText("None selected")
        self._refresh()

    def _pick_ref(self):
        path, _ = QFileDialog.getOpenFileNames(
            self, "Select reference GenBank file", "", "GenBank (*.gb *.gbk *.gbff);;All files (*)")
        if not path:
            self.chk_offline.setChecked(False)
            return
        try:
            self.win.load_local_reference(path[0])
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, "Invalid reference file", str(ex))
            self.chk_offline.setChecked(False)
            return
        self.lbl_ref.setText(self.win.local_ref_name or "Loaded")
        self._refresh()

    # ---- 任务 ----
    def _start(self):
        if not self.b_start.isEnabled():
            return
        if self.chk_offline.isChecked() and self.win.local_ref_text:
            self.win.go_page(2)          # 离线：P3 直接开始注释
            return
        self.win.start_blast()
        self.b_start.setEnabled(False)
        self.b_cancel.setEnabled(True)

    def _cancel(self):
        self.win.blast_queue.cancel()

    def on_queue_finished(self):
        self.b_start.setEnabled(True)
        self.b_cancel.setEnabled(False)
        self.progress.setValue(self.progress.maximum())
        self._refresh()
