"""P3 参考选择页（§7.2）：每序列单选参考（推荐/命中表/直接输入 accession），
"Use recommended for all"，"开始注释"（线程池 + 进度）。"""
from PyQt6.QtWidgets import (QButtonGroup, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QMessageBox, QPushButton,
                             QProgressBar, QRadioButton, QVBoxLayout, QWidget)

from ...services.worker import AnnotateWorker
from ..icons import icon
from ..widgets.hit_table import HitTable


class PageReference(QWidget):
    title = "3. Reference Selection"

    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = QHBoxLayout(self)

        left = QVBoxLayout()
        left.addWidget(QLabel("Sequences"))
        self.seq_list = QListWidget()
        self.seq_list.currentRowChanged.connect(self._on_seq_selected)
        left.addWidget(self.seq_list, 1)
        b_rec_all = QPushButton("Use recommended for all")
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
        self.radio_group = QButtonGroup(self)
        self.rb_recommended = QRadioButton("Use auto-recommended hit (top-ranked, §6.1)")
        self.rb_from_table = QRadioButton("Use selected hit below")
        self.rb_accession = QRadioButton("Enter reference accession directly (skip BLAST)")
        self.rb_recommended.setChecked(True)
        self.radio_group.addButton(self.rb_recommended)
        self.radio_group.addButton(self.rb_from_table)
        self.radio_group.addButton(self.rb_accession)
        self.accession_edit = QLineEdit()
        self.accession_edit.setPlaceholderText("e.g. MZ123456.1")
        c_layout.addWidget(self.rb_recommended)
        c_layout.addWidget(self.rb_from_table)
        h = QHBoxLayout()
        h.addWidget(self.rb_accession)
        h.addWidget(self.accession_edit, 1)
        c_layout.addLayout(h)
        right.addWidget(choice)

        btns = QHBoxLayout()
        b_save_choice = QPushButton("Save choice for this sequence")
        b_save_choice.clicked.connect(self._save_choice)
        self.b_annotate = QPushButton(icon("fa5s.play", "#ffffff"), "Start Annotation →")
        self.b_annotate.setObjectName("PrimaryButton")
        self.b_annotate.clicked.connect(self._start_annotate)
        self.b_cancel = QPushButton("Cancel pending")
        self.b_cancel.clicked.connect(self.win.annotate_queue.cancel)
        btns.addWidget(b_save_choice)
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
            self.seq_list.addItem(f"{s.seq_id} ({s.gene_type or 'no gene type'})")
        self.seq_list.blockSignals(False)
        offline = self.win.local_ref_text is not None
        self.lbl_offline.setText("Offline mode: all sequences will use the local reference GenBank."
                                 if offline else "")
        # 状态驱动：有序列且（离线 / 有命中 / 有 accession）才可注释
        ready = bool(self.win.sequences) and (
            offline
            or any(self.win.hits.get(s.seq_id) for s in self.win.sequences)
            or any(self.win.selected_ref.get(s.seq_id) for s in self.win.sequences))
        self.b_annotate.setEnabled(ready)
        self.b_annotate.setToolTip("" if ready else
                                   "Run BLAST in step 2, enter an accession, or load an offline reference first.")
        if self.seq_list.count():
            self.seq_list.setCurrentRow(0)
            self._highlight_recommended()

    def _highlight_recommended(self):
        """§6.1 排序第一名加推荐徽章与底色（新手不用懂排序规则）。"""
        row = self.seq_list.currentRow()
        if not (0 <= row < len(self.win.sequences)):
            return
        hits = self.win.hits.get(self.win.sequences[row].seq_id)
        if hits:
            self.hit_table.mark_recommended(0)

    def _on_seq_selected(self, row):
        if not (0 <= row < len(self.win.sequences)):
            return
        s = self.win.sequences[row]
        self.hit_table.populate(self.win.hits.get(s.seq_id), len(s.seq))
        self._highlight_recommended()
        choice = self.win.selected_ref.get(s.seq_id)
        if choice and not choice.startswith("rec:"):
            self.rb_accession.setChecked(True)
            self.accession_edit.setText(choice)
        else:
            self.rb_recommended.setChecked(True)

    def _use_recommended_all(self):
        for s in self.win.sequences:
            self.win.selected_ref[s.seq_id] = None    # None = 推荐第一名
        QMessageBox.information(self, "Set", "All sequences will use the auto-recommended reference.")

    def _save_choice(self):
        row = self.seq_list.currentRow()
        if row < 0:
            return
        s = self.win.sequences[row]
        if self.rb_accession.isChecked():
            acc = self.accession_edit.text().strip()
            if not acc:
                QMessageBox.warning(self, "Missing accession", "Enter a reference accession.")
                return
            self.win.selected_ref[s.seq_id] = acc
        elif self.rb_from_table.isChecked():
            acc = self.hit_table.current_accession()
            if not acc:
                QMessageBox.warning(self, "No hit selected", "Click a row in the hit table.")
                return
            self.win.selected_ref[s.seq_id] = acc
        else:
            self.win.selected_ref[s.seq_id] = None
        QMessageBox.information(self, "Saved", f"[{s.seq_id}]  reference choice recorded.")

    # ---- 注释任务 ----
    def _start_annotate(self):
        if not self.win.sequences:
            QMessageBox.information(self, "No sequences", "Import sequences first.")
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
