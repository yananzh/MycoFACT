"""P1 序列导入页（§7.2）：统一导入输入框——支持直接粘贴序列文本（FASTA 或裸
序列），也支持把 FASTA 文件拖入框内（内容读入框中），统一点 Import 解析入库。
source 修饰符不在本页采集——BankIt 门户模式下由门户表单录入（§7.2 P5）。"""
import io
import os

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QTextCursor
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                             QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                             QProgressBar, QPushButton, QVBoxLayout, QWidget)

from ...core.models import SeqInput
from ..icons import icon
from ..widgets.help import HelpButton

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
        from PyQt6.QtGui import QTextCursor
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
    title = "1. Import"

    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(icon("fa5s.file-import", "#2D7DD2").pixmap(20, 20))
        title = QLabel("Import sequences — paste text or drag & drop FASTA files into the box")
        title.setObjectName("PageTitle")
        header.addWidget(icon_label)
        header.addWidget(title)
        header.addStretch(1)
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("Hint")
        header.addWidget(self.lbl_count)
        layout.addLayout(header)

        self.import_box = ImportBox()
        self.import_box.setMinimumHeight(120)
        self.import_box.errorRaised.connect(
            lambda msg: QMessageBox.warning(self, "Import failed", msg))
        layout.addWidget(self.import_box, 1)

        row = QHBoxLayout()
        self.b_import = QPushButton(icon("fa5s.check", "#ffffff"), "Import")
        self.b_import.setObjectName("PrimaryButton")
        self.b_import.setToolTip("Parse the box content and add the sequences to the project")
        self.b_import.clicked.connect(self._import_box)
        b_browse = QPushButton(icon("fa5s.folder-open", "#ffffff"), "Browse")
        b_browse.setObjectName("PrimaryButton")
        b_browse.setToolTip("Pick FASTA files and load them into the box")
        b_browse.clicked.connect(self._add_files_dialog)
        b_clear = QPushButton(icon("fa5s.broom", "#ffffff"), "Clear")
        b_clear.setObjectName("PrimaryButton")
        b_clear.setToolTip("Remove all imported sequences")
        b_clear.clicked.connect(self._clear)
        row.addWidget(self.b_import)
        row.addWidget(b_browse)
        row.addWidget(b_clear)
        row.addStretch(1)
        layout.addLayout(row)

        # ---- BLAST 区（自 BLAST 页并入，在线部分）----
        chips = QHBoxLayout()
        self.chip_db = QLabel("-")
        self.chip_db.setObjectName("Chip")
        self.chip_queue = QLabel("-")
        self.chip_queue.setObjectName("Chip")
        chips.addWidget(self.chip_db)
        chips.addWidget(self.chip_queue)
        chips.addStretch(1)
        chips.addWidget(HelpButton("identity"))
        layout.addLayout(chips)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setObjectName("Hint")
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        b_row = QHBoxLayout()
        self.b_start = QPushButton(icon("fa5s.play", "#ffffff"), "Start BLAST")
        self.b_start.setObjectName("PrimaryButton")
        self.b_start.clicked.connect(self._start)
        self.b_cancel = QPushButton("Cancel pending")
        self.b_cancel.clicked.connect(self._cancel)
        self.b_cancel.setEnabled(False)
        b_row.addWidget(self.b_start)
        b_row.addWidget(self.b_cancel)
        b_row.addStretch(1)
        layout.addLayout(b_row)

        self.refresh()

    # ---- 导入 ----
    def _import_box(self):
        try:
            seqs = parse_pasted_input(self.import_box.toPlainText())
        except ValueError as ex:
            QMessageBox.warning(self, "Invalid input", str(ex))
            return
        try:
            for s in seqs:
                self.win.add_sequence(s)
        except ValueError as ex:
            QMessageBox.warning(self, "Import failed", str(ex))
        self.import_box.clear()
        self.refresh()

    def _add_files_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select FASTA files", "",
            "FASTA (*.fasta *.fa *.fna *.ffn *.faa *.txt);;All files (*)")
        if paths:
            self.import_box.load_paths(paths)

    # ---- 刷新 ----
    def refresh(self):
        """页眉导入计数 + BLAST 区状态（徽章、提示、Start 禁用条件）。"""
        n = len(self.win.sequences)
        self.lbl_count.setText(f"{n} sequence(s) imported" if n else "")

        cfg = self.win.make_config()
        self.chip_db.setText(f"Database: {cfg.blast_db}")
        self.chip_queue.setText(
            f"{n} queued · ~{max(1, n * 3)} min" if n else "no sequences yet")
        email_ok = bool(cfg.email)
        reason = ""
        if not n:
            reason = "Import FASTA files in step 1 first. "
        elif not email_ok:
            reason = "Set your NCBI contact email in Tools ▸ Settings first. "
        self.b_start.setEnabled(n > 0 and email_ok)
        self.b_start.setToolTip("" if self.b_start.isEnabled()
                                else reason.strip() or "not ready")
        self.lbl_hint.setText(reason + "Online BLAST takes ~1-5 min per sequence "
                                       "(serial, rate-limited queue).")

    # ---- BLAST 任务 ----
    def _start(self):
        if not self.b_start.isEnabled():
            return
        # 先置按钮状态再提交：队列可能同步排空（全部已有 hits），
        # 由 on_queue_finished 的刷新决定最终态（见 ledger ruling）
        self.b_start.setEnabled(False)
        self.b_cancel.setEnabled(True)
        self.win.start_blast()

    def _cancel(self):
        self.win.blast_queue.cancel()

    def on_queue_finished(self):
        self.progress.setValue(self.progress.maximum())
        self.b_cancel.setEnabled(False)
        self.refresh()

    def _clear(self):
        if self.win.sequences and QMessageBox.question(
                self, "Clear all", "Remove all imported sequences?") != QMessageBox.StandardButton.Yes:
            return
        self.win.sequences.clear()
        self.win.reset_results()
        self.refresh()
