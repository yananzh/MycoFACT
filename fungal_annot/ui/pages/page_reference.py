"""P3 参考选择页（§7.2）：命中表每行一个单选框，点选即生效（默认第一行=推荐）；
支持直接输入 accession；"Use recommended for all" 一键全部用推荐。"""
from PyQt6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QMessageBox, QPushButton,
                             QProgressBar, QVBoxLayout, QWidget)

from ..icons import icon
from ..widgets.hit_table import HitTable


class PageReference(QWidget):
    title = "2. Reference"      # 步骤条标签：水平等宽排布下需要短标签

    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = QHBoxLayout(self)

        left = QVBoxLayout()
        left.addWidget(QLabel("Sequences"))
        self.seq_list = QListWidget()
        self.seq_list.currentRowChanged.connect(self._on_seq_selected)
        left.addWidget(self.seq_list, 1)
        b_rec_all = QPushButton("Use recommended (first hit) for all")
        b_rec_all.clicked.connect(self._use_recommended_all)
        left.addWidget(b_rec_all)
        layout.addLayout(left, 1)

        right = QVBoxLayout()
        self.lbl_offline = QLabel("")
        self.lbl_offline.setWordWrap(True)
        right.addWidget(self.lbl_offline)
        self.hit_table = HitTable()
        right.addWidget(self.hit_table, 1)

        choice = QGroupBox("Reference choice")
        c_layout = QVBoxLayout(choice)
        c_layout.addWidget(QLabel("Selected reference:"))
        self.lbl_choice = QLabel("-")
        self.lbl_choice.setObjectName("Hint")
        c_layout.addWidget(self.lbl_choice)
        acc_row = QHBoxLayout()
        self.accession_edit = QLineEdit()
        self.accession_edit.setPlaceholderText(
            "Use a reference not in the list? Enter its accession (e.g. MZ123456.1)")
        b_use_acc = QPushButton("Use this accession")
        b_use_acc.clicked.connect(self._use_typed_accession)
        acc_row.addWidget(self.accession_edit, 1)
        acc_row.addWidget(b_use_acc)
        c_layout.addLayout(acc_row)
        right.addWidget(choice)

        btns = QHBoxLayout()
        self.b_annotate = QPushButton(icon("fa5s.play", "#ffffff"), "Start Annotation →")
        self.b_annotate.setObjectName("PrimaryButton")
        self.b_annotate.clicked.connect(self._start_annotate)
        self.b_cancel = QPushButton("Cancel pending")
        self.b_cancel.clicked.connect(self.win.annotate_queue.cancel)
        btns.addWidget(self.b_annotate)
        btns.addWidget(self.b_cancel)
        btns.addStretch(1)
        right.addLayout(btns)

        self.progress = QProgressBar()
        right.addWidget(self.progress)
        layout.addLayout(right, 2)

    # ---- 展示 ----
    def refresh(self):
        self.seq_list.blockSignals(True)
        self.seq_list.clear()
        for s in self.win.sequences:
            self.seq_list.addItem(f"{s.seq_id} ({s.gene_type or 'auto'})")
        self.seq_list.blockSignals(False)
        offline = self.win.local_ref_text is not None
        self.lbl_offline.setText("Offline mode: all sequences will use the local reference GenBank."
                                 if offline else "")
        # 未做选择的序列自动取推荐（第一行）；此后 Start Annotation 全序列就绪才可点
        for s in self.win.sequences:
            hits = self.win.hits.get(s.seq_id)
            if hits and not self.win.selected_ref.get(s.seq_id):
                self.win.selected_ref[s.seq_id] = hits[0].accession
        ready = bool(self.win.sequences) and (
            offline
            or all(self.win.selected_ref.get(s.seq_id) for s in self.win.sequences))
        self.b_annotate.setEnabled(ready)
        self.b_annotate.setToolTip("" if ready else
                                   "Every sequence needs a reference: pick one per row "
                                   "(defaults to the recommended first hit), or load an "
                                   "offline reference.")
        if self.seq_list.count():
            self.seq_list.setCurrentRow(0)

    def _current_sid(self):
        row = self.seq_list.currentRow()
        return self.win.sequences[row].seq_id if 0 <= row < len(self.win.sequences) else None

    def _on_seq_selected(self, row):
        if not (0 <= row < len(self.win.sequences)):
            return
        s = self.win.sequences[row]
        # 选中即生效：默认第一行（推荐），已做过选择的序列恢复其选择
        self.hit_table.populate(self.win.hits.get(s.seq_id), len(s.seq),
                                on_select=self._on_hit_picked,
                                chosen=self.win.selected_ref.get(s.seq_id))
        self._highlight_recommended()
        self.lbl_choice.setText(f"Reference: {self.win.selected_ref.get(s.seq_id) or '-'}")

    def _on_hit_picked(self, accession: str):
        """命中表行内单选框回调：选择即写入状态，无需再点保存。"""
        sid = self._current_sid()
        if sid:
            self.win.selected_ref[sid] = accession
            self.lbl_choice.setText(f"Reference: {accession}")
            self.b_annotate.setEnabled(True)
            self.b_annotate.setToolTip("")

    def _highlight_recommended(self):
        """§6.1 排序第一名加推荐徽章与底色（新手不用懂排序规则）。"""
        row = self.seq_list.currentRow()
        if not (0 <= row < len(self.win.sequences)):
            return
        hits = self.win.hits.get(self.win.sequences[row].seq_id)
        if hits:
            self.hit_table.mark_recommended(0)

    def _use_recommended_all(self):
        for s in self.win.sequences:
            hits = self.win.hits.get(s.seq_id)
            if hits:
                self.win.selected_ref[s.seq_id] = hits[0].accession
        self.win.log("All sequences set to their recommended (top-ranked) reference.")
        self.refresh()

    def _use_typed_accession(self):
        sid = self._current_sid()
        acc = self.accession_edit.text().strip()
        if not sid or not acc:
            QMessageBox.warning(self, "Missing accession",
                                "Select a sequence and enter an accession.")
            return
        # 若与表中命中一致，联动该行单选框；否则直接记录（走直接下载通道）
        if not self.hit_table.select_accession(acc):
            self.win.selected_ref[sid] = acc
            self.lbl_choice.setText(f"Reference: {acc}")
        self.win.log(f"[{sid}] reference set to {acc}")

    # ---- 注释任务 ----
    def _start_annotate(self):
        if not self.b_annotate.isEnabled():
            return
        self.win.start_annotation()
        self.b_annotate.setEnabled(False)
        self.b_cancel.setEnabled(True)

    def on_queue_finished(self):
        self.b_annotate.setEnabled(True)
        self.b_cancel.setEnabled(False)
        self.progress.setValue(self.progress.maximum())
        if self.win.results:
            self.win.go_page(3)      # 注释完成 → 进入审核页
