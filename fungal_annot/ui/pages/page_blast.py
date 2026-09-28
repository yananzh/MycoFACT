"""P2 BLAST 页（§7.2）：两种模式用模式卡片明确区分——

- Online BLAST：NCBI 在线比对（限速串行队列，进度/取消）；
- Offline · local reference：直接用本地参考 GenBank，跳过 BLAST（秒级注释）。

选中模式卡片即切换下方面板；离线模式选文件失败/取消自动回落到在线。
Phase 2：主按钮状态驱动禁用（新手不点出错误）。"""
from PyQt6.QtWidgets import (QButtonGroup, QFileDialog, QHBoxLayout, QLabel,
                             QMessageBox, QProgressBar, QPushButton,
                             QStackedWidget, QVBoxLayout, QWidget)

from ..icons import icon
from ..widgets.help import HelpButton


class PageBlast(QWidget):
    title = "2. BLAST"          # 步骤条标签：水平等宽排布下需要短标签

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

        # ---- 模式选择：两张互斥卡片，两种模式一眼分开 ----
        mode_row = QHBoxLayout()
        self.btn_mode_online = QPushButton(
            "① Online BLAST\nSearch NCBI nt with the imported sequences")
        self.btn_mode_online.setObjectName("ModeCard")
        self.btn_mode_online.setCheckable(True)
        self.btn_mode_offline = QPushButton(
            "② Offline · local reference\nAnnotate against a local GenBank file (no network)")
        self.btn_mode_offline.setObjectName("ModeCard")
        self.btn_mode_offline.setCheckable(True)
        mode_row.addWidget(self.btn_mode_online, 1)
        mode_row.addWidget(self.btn_mode_offline, 1)
        layout.addLayout(mode_row)

        # ---- 模式面板：随所选卡片切换 ----
        self.mode_stack = QStackedWidget()
        w_online = QWidget()
        v_online = QVBoxLayout(w_online)
        v_online.setContentsMargins(0, 0, 0, 0)
        self.lbl_hint = QLabel("")
        self.lbl_hint.setObjectName("Hint")
        self.lbl_hint.setWordWrap(True)
        v_online.addWidget(self.lbl_hint)
        self.mode_stack.addWidget(w_online)

        w_offline = QWidget()
        h_off = QHBoxLayout(w_offline)
        h_off.setContentsMargins(0, 0, 0, 0)
        self.lbl_ref = QLabel("None selected")
        self.lbl_ref.setObjectName("Hint")
        b_pick = QPushButton("Browse reference GenBank...")
        b_pick.clicked.connect(lambda: self._pick_ref())
        h_off.addWidget(self.lbl_ref, 1)
        h_off.addWidget(b_pick)
        self.mode_stack.addWidget(w_offline)
        layout.addWidget(self.mode_stack)

        self.btn_mode_online.clicked.connect(lambda: self._on_mode_clicked(False))
        self.btn_mode_offline.clicked.connect(lambda: self._on_mode_clicked(True))

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

        # 初始模式：已加载本地参考 → 离线；否则在线（编程置位不触发 clicked）
        if self.win.local_ref_text is not None:
            self.btn_mode_offline.setChecked(True)
            self.lbl_ref.setText(self.win.local_ref_name or "Loaded")
        else:
            self.btn_mode_online.setChecked(True)
        self._refresh()

    # ---- 状态刷新 ----
    def _refresh(self):
        cfg = self.win.make_config()
        n = len(self.win.sequences)
        offline_card = self.btn_mode_offline.isChecked()
        offline = offline_card and bool(self.win.local_ref_text)
        self.mode_stack.setCurrentIndex(1 if offline_card else 0)
        self.chip_db.setText(f"Database: {cfg.blast_db}")
        self.chip_queue.setText(
            f"{n} queued · ~{max(1, n * 3)} min" if n else "no sequences yet")
        self.chip_mode.setText("OFFLINE" if offline else "ONLINE")
        email_ok = bool(cfg.email)
        has_seqs = n > 0
        reason = ""
        self.b_start.setEnabled(has_seqs and (offline or email_ok))
        if offline:
            self.b_start.setText("Next (offline, no BLAST needed)")
            self.lbl_hint.setText(f"{n} sequence(s) will be annotated against the local "
                                  "reference; typically a few seconds.")
        else:
            self.b_start.setText("Start BLAST")
            if not has_seqs:
                reason = "Import FASTA files in step 1 first. "
            elif not email_ok:
                reason = "Set your NCBI contact email in Tools ▸ Settings first. "
            self.lbl_hint.setText(reason + "Online BLAST takes ~1-5 min per sequence "
                                         "(serial, rate-limited queue).")
        self.b_start.setToolTip("" if self.b_start.isEnabled()
                                else reason.strip() or "not ready")

    def refresh(self):
        self._refresh()

    # ---- 模式切换 ----
    def _on_mode_clicked(self, offline: bool):
        if offline and not self.win.local_ref_text:
            if not self._pick_ref():                 # 取消/文件无效 → 回落在线
                self.btn_mode_online.setChecked(True)
        elif not offline:
            self.win.local_ref_text = None
            self.win.local_ref_name = None
            self.lbl_ref.setText("None selected")
        self._refresh()

    def _pick_ref(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select reference GenBank file", "",
            "GenBank (*.gb *.gbk *.gbff);;All files (*)")
        if not path:
            return False
        try:
            self.win.load_local_reference(path)
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, "Invalid reference file", str(ex))
            return False
        self.lbl_ref.setText(self.win.local_ref_name or "Loaded")
        self._refresh()
        return True

    # ---- 任务 ----
    def _start(self):
        if not self.b_start.isEnabled():
            return
        if self.btn_mode_offline.isChecked() and self.win.local_ref_text:
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
