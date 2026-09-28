"""P3 参考选择页（§7.2）：命中表每行一个单选框，点选即生效（默认第一行=推荐）；
"Use recommended for all" 一键全部用推荐；"View match" 弹窗查看/修改每条序列的
参考 accession（清空则回落推荐命中）。"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
                             QLabel, QListWidget, QListWidgetItem, QPushButton,
                             QProgressBar, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from ..widgets.help import HelpButton, MARKER_HINT
from ..widgets.hit_table import HitTable


class AccessionDialog(QDialog):
    """两列表格弹窗：序列名（只读）+ 当前参考 accession（可手动修改）。

    第二列预填当前选择；OK 后逐行应用——非空行手动指定参考，
    清空行清掉选择、由 refresh 回落到推荐命中。"""

    def __init__(self, sequences, current: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reference match")
        self.resize(560, 360)
        v = QVBoxLayout(self)
        tip = QLabel("Reference accession per sequence (editable). Clear a row to "
                     "fall back to the recommended hit.")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        v.addWidget(tip)
        self.table = QTableWidget(len(sequences), 2)
        self.table.setHorizontalHeaderLabels(["Sequence", "Reference accession"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 200)
        for row, s in enumerate(sequences):
            name = QTableWidgetItem(s.seq_id)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(current.get(s.seq_id) or ""))
        v.addWidget(self.table, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def values(self) -> dict[str, str]:
        """收集全部行的 {seq_id: accession}（含空串，空串表示回落推荐）。"""
        return {self.table.item(row, 0).text(): self.table.item(row, 1).text().strip()
                for row in range(self.table.rowCount())}


class PageReference(QWidget):
    title = "2. Select Reference"   # 步骤条标签：两词命名，与各步动词开头一致

    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = QVBoxLayout(self)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Sequences"))
        self.seq_list = QListWidget()
        self.seq_list.setMaximumWidth(200)   # 名单列不挤占命中表（窄窗口下尤甚）
        self.seq_list.currentRowChanged.connect(self._on_seq_selected)
        left.addWidget(self.seq_list, 1)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        hits_header = QHBoxLayout()
        hits_header.addWidget(QLabel("BLAST hits"))
        hits_header.addStretch(1)
        hits_header.addWidget(HelpButton("hit_columns"))   # qcovs / Len ratio 就地解释
        right.addLayout(hits_header)
        self.hit_table = HitTable()
        right.addWidget(self.hit_table, 1)
        self.progress = QProgressBar()
        right.addWidget(self.progress)
        body.addLayout(right, 2)
        layout.addLayout(body, 1)

        # ---- 底部动作行：跨左右两栏水平排列 ----
        btns = QHBoxLayout()
        b_rec_all = QPushButton("Use recommended for all")
        b_rec_all.setToolTip("Set every sequence's reference to its top-ranked (first) hit")
        b_rec_all.clicked.connect(self._use_recommended_all)
        btns.addWidget(b_rec_all)
        b_acc = QPushButton("View match")
        b_acc.setToolTip("View and edit each sequence's reference accession - "
                         "clear a row to fall back to the recommended hit")
        b_acc.clicked.connect(self._enter_accessions)
        btns.addWidget(b_acc)
        self.b_annotate = QPushButton("Start Annotation")
        self.b_annotate.setObjectName("PrimaryButton")
        self.b_annotate.clicked.connect(self._start_annotate)
        btns.addWidget(self.b_annotate)
        btns.addStretch(1)
        layout.addLayout(btns)

    # ---- 展示 ----
    def refresh(self):
        self.seq_list.blockSignals(True)
        self.seq_list.clear()
        for s in self.win.sequences:
            item = QListWidgetItem(f"{s.seq_id} ({s.gene_type or 'auto-detect'})")
            item.setToolTip(MARKER_HINT)
            self.seq_list.addItem(item)
        self.seq_list.blockSignals(False)
        # 未做选择的序列自动取推荐（第一行）；此后 Start Annotation 全序列就绪才可点
        for s in self.win.sequences:
            hits = self.win.hits.get(s.seq_id)
            if hits and not self.win.selected_ref.get(s.seq_id):
                self.win.selected_ref[s.seq_id] = hits[0].accession
        ready = bool(self.win.sequences) and all(
            self.win.selected_ref.get(s.seq_id) for s in self.win.sequences)
        self.b_annotate.setEnabled(ready)
        self.b_annotate.setToolTip("" if ready else
                                   "Every sequence needs a reference: pick one per row "
                                   "(defaults to the recommended first hit).")
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

    def _on_hit_picked(self, accession: str):
        """命中表行内单选框回调：选择即写入状态，无需再点保存。"""
        sid = self._current_sid()
        if sid:
            self.win.selected_ref[sid] = accession
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

    def _enter_accessions(self):
        """View match 弹窗：逐行查看/修改参考 accession——非空行手动指定，
        清空行清掉选择并由 refresh 回落推荐命中。"""
        dlg = AccessionDialog(self.win.sequences, self.win.selected_ref, self)
        if not dlg.exec():
            return
        for sid, acc in dlg.values().items():
            if acc:
                self.win.selected_ref[sid] = acc
                self.win.log(f"[{sid}] reference set to {acc} (manual)")
            else:
                self.win.selected_ref[sid] = None
                self.win.log(f"[{sid}] reference cleared - falls back to recommended hit")
        self.refresh()

    # ---- 注释任务 ----
    def _start_annotate(self):
        if not self.b_annotate.isEnabled():
            return
        self.win.start_annotation()
        self.b_annotate.setEnabled(False)

    def on_queue_finished(self):
        self.b_annotate.setEnabled(True)
        self.progress.setValue(self.progress.maximum())
        if self.win.results:
            self.win.go_page(2)      # 注释完成 → 进入审核页
