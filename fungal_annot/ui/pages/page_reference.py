"""P3 参考选择页（§7.2 + 多参考对比）：命中表每行一个复选框，勾选即参与对比
注释（1-5 个，默认勾前 N=Settings 的 default_refs，推荐第一行总在其中）；
"View match" 弹窗查看/修改每条序列的参考 accession 列表（可手填，逗号分隔；
清空则回落前 N 推荐命中）。
注释按（序列 × 参考）成对执行，结果在审核页对比后采纳其一用于导出。"""
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
                             QLabel, QListWidget, QListWidgetItem, QPushButton,
                             QProgressBar, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from ..widgets.help import show_page_help
from ..widgets.hit_table import HitTable

MAX_REFS = 5
# 手填参考串的分隔符：半角/全角逗号、分号、空白
_SPLIT_RE = re.compile(r"[,;，；\s]+")


def parse_ref_entries(text: str) -> list[str]:
    """把一行手填的参考解析为去重后的 accession 列表（至多 MAX_REFS 个）。"""
    seen: list[str] = []
    for part in _SPLIT_RE.split((text or "").strip()):
        if part and part not in seen:
            seen.append(part)
    return seen[:MAX_REFS]


class AccessionDialog(QDialog):
    """两列表格弹窗：序列名（只读）+ 当前参考 accession 列表（可手修改）。

    第二列预填当前选择（逗号分隔）；OK 后逐行应用——非空行手动指定参考
    （至多 MAX_REFS 个），空行清掉选择、由 refresh 回落前 N 推荐命中。"""

    def __init__(self, sequences, current: dict[str, list[str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reference match")
        self.resize(560, 360)
        v = QVBoxLayout(self)
        tip = QLabel(f"Reference accession(s) per sequence (editable, up to "
                     f"{MAX_REFS}, comma-separated). Clear a row to fall back to "
                     f"the recommended hits.")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        v.addWidget(tip)
        self.table = QTableWidget(len(sequences), 2)
        self.table.setHorizontalHeaderLabels(["Sequence", "Reference accession(s)"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 280)
        for row, s in enumerate(sequences):
            name = QTableWidgetItem(s.seq_id)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(
                ", ".join(current.get(s.seq_id) or [])))
        v.addWidget(self.table, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def values(self) -> dict[str, str]:
        """收集全部行的 {seq_id: 原始文本}（含空串，空串表示回落推荐）。"""
        return {self.table.item(row, 0).text(): self.table.item(row, 1).text().strip()
                for row in range(self.table.rowCount())}


class PageReference(QWidget):
    title = "2. Select Reference"   # 步骤条标签：两词命名，与各步动词开头一致
    help_key = "page_reference"

    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

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
        right.addLayout(hits_header)
        self.hit_table = HitTable()
        right.addWidget(self.hit_table, 1)
        self.progress = QProgressBar()
        right.addWidget(self.progress)
        body.addLayout(right, 2)
        layout.addLayout(body, 1)

        # ---- 底部动作行：三按钮水平相邻（Help 不孤悬行尾）----
        btns = QHBoxLayout()
        b_acc = QPushButton("View match")
        b_acc.setToolTip("View and edit each sequence's reference accession(s) - "
                         "clear a row to fall back to the recommended hits")
        b_acc.clicked.connect(self._enter_accessions)
        btns.addWidget(b_acc)
        self.b_annotate = QPushButton("Start Annotation")
        self.b_annotate.setObjectName("PrimaryButton")
        self.b_annotate.clicked.connect(self._start_annotate)
        btns.addWidget(self.b_annotate)
        b_help = QPushButton("Help")
        b_help.setToolTip("How to use this page: steps, terms, tips")
        b_help.clicked.connect(lambda: show_page_help("page_reference", self))
        btns.addWidget(b_help)
        btns.addStretch(1)
        layout.addLayout(btns)

    def _default_n(self) -> int:
        """默认对比参考数（Settings 的 default_refs，夹在 1-5）。"""
        try:
            n = int(str(self.win.settings.get("default_refs", 3) or 3))
        except (TypeError, ValueError):
            n = 3
        return max(1, min(MAX_REFS, n))

    # ---- 展示 ----
    def refresh(self):
        self.seq_list.blockSignals(True)
        self.seq_list.clear()
        for s in self.win.sequences:
            item = QListWidgetItem(f"{s.seq_id} ({s.gene_type or 'auto-detect'})")
            self.seq_list.addItem(item)
        self.seq_list.blockSignals(False)
        # 未做选择的序列自动取前 N 推荐；此后 Start Annotation 全序列就绪才可点
        for s in self.win.sequences:
            hits = self.win.hits.get(s.seq_id)
            if hits and not self.win.selected_refs.get(s.seq_id):
                self.win.selected_refs[s.seq_id] = [h.accession for h in hits[:self._default_n()]]
        pending = self.win._annotate_pending > 0
        ready = (bool(self.win.sequences)
                 and all(self.win.selected_refs.get(s.seq_id) for s in self.win.sequences)
                 and not pending)       # 队列运行中不得重新点亮（防双重提交）
        self.b_annotate.setEnabled(ready)
        if pending:
            tip = "Annotation queue is running - wait for it to finish."
        elif ready:
            tip = ""
        else:
            tip = ("Every sequence needs at least one reference: check 1-5 hits per "
                   "row (top-ranked ones are pre-checked).")
        self.b_annotate.setToolTip(tip)
        if self.seq_list.count():
            self.seq_list.setCurrentRow(0)
        else:
            self.hit_table.setRowCount(0)

    def _current_sid(self):
        row = self.seq_list.currentRow()
        return self.win.sequences[row].seq_id if 0 <= row < len(self.win.sequences) else None

    def _on_seq_selected(self, row):
        if not (0 <= row < len(self.win.sequences)):
            return
        s = self.win.sequences[row]
        # 选中即展示命中表；已选参考按勾选状态恢复（1-5 个）
        self.hit_table.populate(self.win.hits.get(s.seq_id), len(s.seq),
                                on_toggle=self._on_ref_toggled,
                                selected=self.win.selected_refs.get(s.seq_id))
        self._highlight_recommended()

    def _on_ref_toggled(self, accession: str, checked: bool):
        """复选框回调：勾选/取消即写入状态；上限 MAX_REFS、至少保留 1 个。"""
        sid = self._current_sid()
        if not sid:
            return
        hits = self.win.hits.get(sid) or []
        order = [h.accession for h in hits]
        cur = list(self.win.selected_refs.get(sid) or [])
        if checked:
            if accession in cur:
                return
            if len(cur) >= MAX_REFS:
                self.win.log(f"Up to {MAX_REFS} references per sequence - "
                             "uncheck one first")
            else:
                cur.append(accession)
        else:
            if accession not in cur:
                return
            if len(cur) <= 1:
                self.win.log("At least one reference must stay selected")
            else:
                cur.remove(accession)
        # 按命中排名排序（手填、不在命中列表内的 accession 排在后）
        self.win.selected_refs[sid] = ([a for a in order if a in cur]
                                       + [a for a in cur if a not in order])
        self.win.mark_dirty()
        self.hit_table.sync_checks(self.win.selected_refs[sid])
        self.b_annotate.setEnabled(self._ready_now())
        if self._ready_now():
            self.b_annotate.setToolTip("")

    def _ready_now(self) -> bool:
        return (bool(self.win.sequences)
                and all(self.win.selected_refs.get(s.seq_id) for s in self.win.sequences)
                and self.win._annotate_pending == 0)

    def _highlight_recommended(self):
        """§6.1 排序第一名加推荐徽章与底色（新手不用懂排序规则）。"""
        row = self.seq_list.currentRow()
        if not (0 <= row < len(self.win.sequences)):
            return
        hits = self.win.hits.get(self.win.sequences[row].seq_id)
        if hits:
            self.hit_table.mark_recommended(0)

    def _enter_accessions(self):
        """View match 弹窗：逐行查看/修改参考 accession 列表——非空行手动指定
        （至多 5 个），空行清掉选择并由 refresh 回落前 N 推荐命中。"""
        dlg = AccessionDialog(self.win.sequences, self.win.selected_refs, self)
        if not dlg.exec():
            return
        for sid, text in dlg.values().items():
            entries = parse_ref_entries(text)
            if entries:
                self.win.selected_refs[sid] = entries
                self.win.log(f"[{sid}] references set to {', '.join(entries)} (manual)")
            else:
                hits = self.win.hits.get(sid) or []
                self.win.selected_refs[sid] = [h.accession for h in hits[:self._default_n()]]
                self.win.log(f"[{sid}] references cleared - falls back to "
                             "recommended hits")
        self.win.mark_dirty()
        self.refresh()

    # ---- 注释任务 ----
    def _start_annotate(self):
        if not self.b_annotate.isEnabled():
            return
        self.win.start_annotation()
        self.b_annotate.setEnabled(False)

    def on_queue_finished(self):
        self.progress.setValue(self.progress.maximum())
        self.refresh()      # 按当前状态重算按钮可用性（删除/清空后不得凭空点亮）
        if self.win.results:
            # 仅当用户仍停在参考选择页时自动进入审核页；批量任务期间用户可能
            # 已切到别页工作，无条件跳转会打断操作（BLAST 排空同理）
            if self.win.stack.currentIndex() == 1:
                self.win.go_page(2)      # 注释完成 → 进入审核页
            else:
                self.win.log("Annotation queue finished - continue on step 3 (review)")
