"""P1 导入 & BLAST 页（§7.2 + 2026-09-28 合并页改造）：统一导入输入框——支持直接
粘贴序列文本（FASTA 或裸序列），也支持把 FASTA 文件拖入框内；四按钮
BLAST/Browse/Example/Clear/STOP，点 BLAST 自动导入框内文本并启动在线 BLAST 队列，
Example 把内置 demo/example.fasta 载入框内供试跑。
source 修饰符不在本页采集——BankIt 门户模式下由门户表单录入（§7.2 P5）。"""
import io
import os
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QTextCursor
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                             QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                             QMessageBox, QPlainTextEdit, QProgressBar,
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QToolButton, QVBoxLayout, QWidget)

from ...core.models import SeqInput
from ..widgets.help import MARKER_HINT, show_page_help

# 裸序列允许的字符（IUPAC 核苷酸歧义码）
_DNA_CHARS = set("ACGTUNRYKMSWBDHV")


def parse_pasted_input(text: str) -> list[SeqInput]:
    """解析输入框文本：FASTA（一条或多条）或裸 DNA 序列。

    裸序列自动命名 pasted_seq；含非核苷酸字符或为空时抛 ValueError。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Nothing to import: the text is empty.")
    if text.startswith(">"):
        from Bio import SeqIO
        records = list(SeqIO.parse(io.StringIO(text), "fasta"))
        if not records:
            raise ValueError("No FASTA entries found in the input.")
        return [SeqInput(seq_id=str(r.id), seq=str(r.seq).upper()) for r in records]
    clean = "".join(text.split()).upper()
    bad = set(clean) - _DNA_CHARS
    if bad:
        raise ValueError("Non-nucleotide characters in the sequence: "
                         + "".join(sorted(bad))[:10])
    return [SeqInput(seq_id="pasted_seq", seq=clean)]


class PasteDialog(QDialog):
    """粘贴输入对话框：校验通过才允许关闭，解析结果存 self.sequences。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Paste sequences")
        self.resize(560, 420)
        self.sequences: list[SeqInput] = []
        v = QVBoxLayout(self)
        tip = QLabel("Paste FASTA text (one or more entries) or a bare DNA sequence.")
        tip.setObjectName("Hint")
        v.addWidget(tip)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(">seq1\nATGG...\n\n>seq2\nATGG...")
        font = self.edit.font()
        font.setFamily("Consolas")
        self.edit.setFont(font)
        v.addWidget(self.edit, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def accept(self):
        try:
            self.sequences = parse_pasted_input(self.edit.toPlainText())
        except ValueError as ex:
            QMessageBox.warning(self, "Invalid input", str(ex))
            return
        super().accept()


class ImportBox(QPlainTextEdit):
    """统一导入输入框：可直接粘贴序列文本，也可把 FASTA 文件拖入框内
    （文件内容读入框中），再由 Import 按钮统一解析入库。"""

    filesLoaded = pyqtSignal(list)   # 成功读入的文件路径
    errorRaised = pyqtSignal(str)    # 读文件失败的提示信息

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ImportBox")
        self.setAcceptDrops(True)
        self.setPlaceholderText("Paste FASTA here (one or more entries) or a bare DNA "
                                "sequence,\nor drag & drop FASTA files into this box...")

    def load_paths(self, paths: list[str]):
        """把文件内容读入输入框（追加）。裸序列文件自动补上以文件名命名的 FASTA 头。"""
        for p in paths:
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    text = fh.read().strip()
            except OSError as ex:
                self.errorRaised.emit(f"Cannot read {os.path.basename(p)}: {ex}")
                continue
            if not text:
                continue
            if not text.startswith(">"):
                base = os.path.splitext(os.path.basename(p))[0]
                seq = "".join(text.split()).upper()
                bad = set(seq) - _DNA_CHARS
                if bad:
                    self.errorRaised.emit(
                        f"{os.path.basename(p)}: non-nucleotide characters "
                        + "".join(sorted(bad))[:10])
                    continue
                text = f">{base}\n{seq}"
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)
            self.insertPlainText(text + "\n")
            self.filesLoaded.emit([p])

    # ---- 拖放：文件读入框内；文本拖入按默认插入 ----
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            self.setProperty("dragOver", "true")
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self.setProperty("dragOver", "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            self.setProperty("dragOver", "false")
            self.style().unpolish(self)
            self.style().polish(self)
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            self.load_paths(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class PageImport(QWidget):
    title = "1. Import & BLAST"
    help_key = "page_import"

    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.import_box = ImportBox()
        self.import_box.setMinimumHeight(110)
        self.import_box.errorRaised.connect(
            lambda msg: QMessageBox.warning(self, "Import failed", msg))
        layout.addWidget(self.import_box, 1)

        row = QHBoxLayout()
        self.b_blast = QPushButton("BLAST")
        self.b_blast.setObjectName("PrimaryButton")
        self.b_blast.setToolTip("Import the box content (if any) and start online BLAST")
        self.b_blast.clicked.connect(self._start)
        b_browse = QPushButton("Browse")
        b_browse.setToolTip("Pick FASTA files and load them into the box")
        b_browse.clicked.connect(self._add_files_dialog)
        b_example = QPushButton("Example")
        b_example.setToolTip("Load the bundled example FASTA (demo/example.fasta, 4 "
                             "Colletotrichum marker sequences) into the box, then click BLAST")
        b_example.clicked.connect(self._load_example)
        b_clear = QPushButton("Clear")
        b_clear.setToolTip("Remove all imported sequences")
        b_clear.clicked.connect(self._clear)
        self.b_stop = QPushButton("STOP")
        self.b_stop.clicked.connect(self._cancel)
        self.b_stop.setEnabled(False)
        row_buttons = (self.b_blast, b_browse, b_example, b_clear, self.b_stop)
        uniform = max(b.sizeHint().width() for b in row_buttons)
        for b in row_buttons:           # 五按钮统一宽度（取最宽者的自然宽度）
            b.setFixedWidth(uniform)
        row.addWidget(self.b_blast)
        row.addWidget(b_browse)
        row.addWidget(b_example)
        row.addWidget(b_clear)
        row.addWidget(self.b_stop)
        b_help = QPushButton("Help")
        b_help.setToolTip("How to use this page: steps, terms, tips")
        b_help.clicked.connect(lambda: show_page_help("page_import", self))
        row.addWidget(b_help)               # 紧挨 STOP 右侧
        row.addStretch(1)
        layout.addLayout(row)

        # ---- 已导入序列清单：BLAST 状态 / 单条删除 / 双击 Seq ID 改名 ----
        self.seq_table = QTableWidget(0, 5)
        self.seq_table.setHorizontalHeaderLabels(
            ["Seq ID", "Length (bp)", "Marker", "BLAST", ""])
        self.seq_table.verticalHeader().setVisible(False)
        self.seq_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.seq_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.seq_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.seq_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.seq_table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.seq_table.setColumnWidth(1, 90)
        self.seq_table.setColumnWidth(2, 90)
        self.seq_table.setColumnWidth(3, 90)
        self.seq_table.setColumnWidth(4, 34)
        self.seq_table.setMinimumHeight(110)
        self.seq_table.itemChanged.connect(self._on_seq_item_changed)
        layout.addWidget(self.seq_table, 1)

        # ---- 状态提示（BLAST 区）----
        self.lbl_hint = QLabel("")
        self.lbl_hint.setObjectName("Hint")
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self._loading_table = False     # 重建清单期间抑制 itemChanged 联动
        self._seq_sig: list = []        # 清单内容签名，未变化时不重建
        self.import_box.textChanged.connect(self.refresh)
        self.refresh()

    def _add_files_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select FASTA files", "",
            "FASTA (*.fasta *.fa *.fna *.ffn *.faa *.txt);;All files (*)")
        if paths:
            self.import_box.load_paths(paths)

    def _load_example(self):
        """把仓库自带 demo/example.fasta 载入输入框（追加，与 Browse 同通道）。

        状态栏报出文件内的序列条数——此时序列尚未导入项目（右栏摘要仍显示
        no sequences），故消息里明确"点 BLAST 运行"，避免两种状态混淆。"""
        path = Path(__file__).resolve().parents[3] / "demo" / "example.fasta"
        if not path.is_file():
            QMessageBox.information(
                self, "Example not found",
                f"The bundled example file is missing:\n{path}")
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            n = len(parse_pasted_input(text))
        except ValueError:
            n = 0
        self.import_box.load_paths([str(path)])
        self.win.log(f"Example loaded into the box: {n} sequence(s) from "
                     f"{path.name} - click BLAST to run")

    # ---- 刷新 ----
    def refresh(self):
        """序列清单 + BLAST 区状态（提示、BLAST 禁用条件）。"""
        n = len(self.win.sequences)
        self._refresh_seq_table()

        email_ok = bool(self.win.make_config().email)
        has_input = bool(self.import_box.toPlainText().strip())
        reason = ""
        if not n and not has_input:
            reason = "Paste FASTA or drag & drop files first. "
        elif self.win._blast_pending > 0:
            reason = "BLAST queue is running - wait for it to finish. "
        elif not email_ok:
            reason = "Set your NCBI contact email in menu ▸ Settings (Ctrl+,) first. "
        self.b_blast.setEnabled((n > 0 or has_input) and email_ok
                                and self.win._blast_pending == 0)
        self.b_blast.setToolTip("" if self.b_blast.isEnabled()
                                else reason.strip() or "not ready")
        self.lbl_hint.setText(reason + "Online BLAST takes ~1-5 min per sequence "
                                       "(serial, rate-limited queue).")

    # ---- 序列清单 ----
    def _refresh_seq_table(self):
        """重建清单（ID/长度/Marker/BLAST 状态/删除）；签名未变则跳过。"""
        self.seq_table.setVisible(bool(self.win.sequences))
        running = self.win._blast_running
        sig = [(s.seq_id, len(s.seq), s.gene_type or "auto-detect",
                "done" if s.seq_id in self.win.hits
                else "running…" if s.seq_id in running else "-")
               for s in self.win.sequences]
        if sig == self._seq_sig:
            return
        self._seq_sig = sig
        self._loading_table = True
        self.seq_table.setRowCount(0)
        for row, s in enumerate(self.win.sequences):
            self.seq_table.insertRow(row)
            id_item = QTableWidgetItem(s.seq_id)
            id_item.setToolTip("Double-click to rename - hits, results and the "
                               "confirmation state move with the new name")
            self.seq_table.setItem(row, 0, id_item)
            for col, value in ((1, str(len(s.seq))), (2, s.gene_type or "auto-detect")):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 2:
                    item.setToolTip(MARKER_HINT)
                self.seq_table.setItem(row, col, item)
            if s.seq_id in self.win.hits:
                st = QTableWidgetItem("done")
                st.setForeground(QColor("#1a7f37"))
            elif s.seq_id in running:
                st = QTableWidgetItem("running…")
                st.setForeground(QColor("#9a6700"))
            else:
                st = QTableWidgetItem("-")
            st.setFlags(st.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.seq_table.setItem(row, 3, st)
            btn = QToolButton()
            btn.setText("✕")
            btn.setToolTip(f"Remove {s.seq_id} (with its hits, results and confirmations)")
            btn.clicked.connect(lambda _=False, sid=s.seq_id: self._remove_one(sid))
            self.seq_table.setCellWidget(row, 4, btn)
        self._loading_table = False

    def _revert_cell(self, row: int, col: int, text: str):
        self._loading_table = True
        self.seq_table.item(row, col).setText(text)
        self._loading_table = False

    def _on_seq_item_changed(self, item):
        """Seq ID 列编辑 → 全局改名（命中/结果/确认状态随新名迁移）。"""
        if self._loading_table or item.column() != 0:
            return
        row = item.row()
        if not (0 <= row < len(self.win.sequences)):
            return
        old = self.win.sequences[row].seq_id
        new = item.text().strip()
        if new == old:
            return
        if not new:
            QMessageBox.warning(self, "Invalid Seq ID", "Seq ID cannot be empty.")
            self._revert_cell(row, 0, old)
            return
        if any(x.seq_id == new for x in self.win.sequences):
            QMessageBox.warning(self, "Duplicate Seq ID", f"'{new}' already exists.")
            self._revert_cell(row, 0, old)
            return
        if self.win._blast_pending > 0 or self.win._annotate_pending > 0:
            # 迟到的 worker 结果按提交时的 seq_id 返回，改名会让它找不到归宿
            QMessageBox.warning(self, "Queue is running",
                                "Wait for the BLAST/annotation queue to finish "
                                "before renaming.")
            self._revert_cell(row, 0, old)
            return
        self.win.rename_sequence(old, new)
        self.win.log(f"[{old}] renamed to {new}")
        self.refresh()

    def _remove_one(self, sid: str):
        self.win.remove_sequence(sid)
        self.win._refresh_nav()
        self.refresh()

    def _dedupe_ids(self, seqs: list) -> None:
        """入库前整体查重：全部通过才清空输入框（避免半提交丢内容）。

        自动命名的 pasted_seq 冲突时追加序号（pasted_seq_2、…_3），
        用户命名的重复仍视为错误。"""
        existing = {s.seq_id for s in self.win.sequences}
        seen: set[str] = set()
        for s in seqs:
            if s.seq_id in existing or s.seq_id in seen:
                if not (s.seq_id == "pasted_seq" or s.seq_id.startswith("pasted_seq_")):
                    raise ValueError(f"Duplicate Seq ID: {s.seq_id}")
                n = 2
                while f"pasted_seq_{n}" in existing or f"pasted_seq_{n}" in seen:
                    n += 1
                s.seq_id = f"pasted_seq_{n}"
            seen.add(s.seq_id)

    # ---- BLAST 任务（点击即自动导入框内文本并启动）----
    def _start(self):
        if not self.b_blast.isEnabled():
            return
        if self.import_box.toPlainText().strip():
            try:
                seqs = parse_pasted_input(self.import_box.toPlainText())
                self._dedupe_ids(seqs)
            except ValueError as ex:
                QMessageBox.warning(self, "Invalid input", str(ex))
                return          # 输入框保留原文，改名/修正后重试
            for s in seqs:
                self.win.add_sequence(s)
            self.import_box.clear()         # textChanged → refresh
        # 先置按钮状态再提交：队列可能同步排空（全部已有 hits），
        # 由 on_queue_finished 的刷新决定最终态（见 ledger ruling）
        self.b_blast.setEnabled(False)
        self.b_stop.setEnabled(True)
        self.win.start_blast()

    def _cancel(self):
        self.win.blast_queue.cancel()

    def on_queue_finished(self):
        self.progress.setValue(self.progress.maximum())
        self.b_stop.setEnabled(False)
        self.refresh()

    def _clear(self):
        if self.win.sequences and QMessageBox.question(
                self, "Clear all", "Remove all imported sequences?") != QMessageBox.StandardButton.Yes:
            return
        self.win._abandon_queues()      # 在途队列作废，迟到的结果不写回
        self.win.sequences.clear()
        self.win.reset_results()
        self.refresh()
