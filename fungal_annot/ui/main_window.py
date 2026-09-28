"""主窗口（§7.1）：顶部水平步骤条 + 中央四页向导 + 底部状态栏；项目存取与设置走菜单栏。
消息与摘要都收敛到状态栏（左侧最近消息 + 右侧单格摘要：序列数/基因型 + 注释进度与告警；
步骤与导出进度由顶部步骤条表达，参考信息在对应页面内展示）。

状态中枢：sequences / hits / selected_ref / results / confirmed 由本对象持有，
各页面通过 win 引用读写。BLAST 队列串行（限速），注释队列小并发。
"""
import os

from PyQt6.QtCore import QSettings, QSize, Qt
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
                             QFormLayout, QLabel, QLineEdit, QListWidgetItem,
                             QMainWindow, QMessageBox, QStackedWidget,
                             QVBoxLayout, QWidget)
from PyQt6.QtGui import QColor, QGuiApplication

from ..core.blast_runner import BlastHit
from ..core.models import SeqInput
from ..services.pipeline import PipelineConfig
from ..services.project_store import (load_project, load_settings,
                                      save_project, save_settings)
from ..services.worker import AnnotateWorker, BlastWorker, TaskQueue
from .pages.page_export import PageExport
from .pages.page_import import PageImport
from .pages.page_reference import PageReference
from .pages.page_review import PageReview
from .widgets.step_bar import StepBar


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(520, 300)
        form = QFormLayout(self)
        self.edits = {}
        fields = [("email", "NCBI contact email (required)"),
                  ("api_key", "Entrez API key (optional)"),
                  ("blast_db", "BLAST database (core_nt / refseq_genomic ...)"),
                  ("organism_filter", "BLAST organism filter (optional)"),
                  ("identity_threshold", "identity threshold %"),
                  ("hitlist_size", "Max hits"),
                  ("cache_dir", "Cache directory (optional)"),
                  ]
        defaults = {"blast_db": "core_nt"}
        hints = {"email": "NCBI uses this to contact you about the submission.",
                 "blast_db": "core_nt is the current default nucleotide database.",
                 "identity_threshold": "Below this identity a sequence is flagged RED for manual review."}
        for key, label in fields:
            edit = QLineEdit(str(settings.get(key) or defaults.get(key, "")))
            self.edits[key] = edit
            form.addRow(label, edit)
            if key in hints:
                hint = QLabel(hints[key])
                hint.setObjectName("Hint")
                form.addRow("", hint)
        self.chk_partial = QCheckBox("Auto-mark features touching sequence ends as partial (§2.1)")
        self.chk_partial.setChecked(bool(settings.get("auto_partial", True)))
        form.addRow(self.chk_partial)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self) -> dict:
        d = {k: e.text().strip() for k, e in self.edits.items()}
        d["auto_partial"] = self.chk_partial.isChecked()
        return d


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fungal Multi-locus Feature Table Generator")
        # 默认窗口大小：可用屏幕的 60%（夹在 860x560 与 1060x700 之间）；
        # 用户手动调整后由 QSettings 记忆，此默认值仅首次启动生效
        self.setMinimumSize(860, 560)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            target = QSize(int(avail.width() * 0.6), int(avail.height() * 0.6))
            target = target.boundedTo(QSize(1060, 700)).expandedTo(QSize(860, 560))
            self.resize(target)
        else:
            self.resize(920, 620)

        # ---- 状态 ----
        self.settings = load_settings()
        self.sequences: list[SeqInput] = []
        self.hits: dict[str, list[BlastHit]] = {}
        self.selected_ref: dict[str, str | None] = {}
        self.results: dict[str, object] = {}
        self.confirmed: dict[str, bool] = {}
        self._blast_running: set[str] = set()   # 已提交 BLAST、尚未返回的序列
        self.last_export_dir = os.path.join(os.path.expanduser("~"), "fungal_annot_out")
        self.exported = False

        # ---- 任务队列 ----
        self.blast_queue = TaskQueue(max_threads=1)     # 限速串行（§6.1）
        self.annotate_queue = TaskQueue(max_threads=2)
        self._blast_pending = 0
        self._annotate_pending = 0
        for q in (self.blast_queue, self.annotate_queue):
            q.signals.finished.connect(self._on_worker_finished)
            q.signals.failed.connect(self._on_worker_failed)
            q.signals.log.connect(self.log)
            q.signals.progress.connect(self._on_worker_progress)

        # ---- 布局：顶部水平步骤条 + 中央页面 ----
        self.nav = StepBar()
        self.stack = QStackedWidget()
        self.page_import = PageImport(self)
        self.page_reference = PageReference(self)
        self.page_review = PageReview(self)
        self.page_export = PageExport(self)
        for page in (self.page_import, self.page_reference,
                     self.page_review, self.page_export):
            self.stack.addWidget(page)
            item = QListWidgetItem(page.title)
            item.setData(Qt.ItemDataRole.UserRole, page.title)
            self.nav.addItem(item)
        self.nav.stepClicked.connect(self._on_step)
        self.stack.currentChanged.connect(lambda _i: self._refresh_nav())

        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(10, 8, 10, 6)
        v.setSpacing(8)
        v.addWidget(self.nav, 0)
        v.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # ---- 菜单栏（原图标工具栏）----
        bar = self.menuBar()
        m_file = bar.addMenu("&File")
        for label, shortcut, slot in (("New Project", "Ctrl+N", self._new_project),
                                      ("Open Project...", "Ctrl+O", self._open_project),
                                      ("Save Project...", "Ctrl+S", self._save_project)):
            act = m_file.addAction(label, slot)
            act.setShortcut(shortcut)
        m_file.addSeparator()
        m_file.addAction("Exit", self.close).setShortcut("Ctrl+Q")
        bar.addMenu("&Tools").addAction("Settings...", self._open_settings)

        # ---- 状态栏：左侧最近消息 + 右侧单格常驻摘要 ----
        self.status_summary = QLabel()
        self.status_summary.setObjectName("StatusAlerts")
        self.statusBar().addPermanentWidget(self.status_summary)
        self.update_summary()

        # ---- 记住窗口几何 ----
        # 键名 geometry2：2026-09-28 默认尺寸调小后换键，旧几何不再恢复，
        # 否则老用户永远看不到新默认值
        settings = QSettings("fungal_annot", "fungal_annot")
        geom = settings.value("geometry2")
        if geom is not None:
            self.restoreGeometry(geom)
        self._refresh_nav()          # 首屏即显示步骤标记

    def closeEvent(self, event):
        settings = QSettings("fungal_annot", "fungal_annot")
        settings.setValue("geometry2", self.saveGeometry())
        super().closeEvent(event)

    # ---- 页面导航 ----
    def go_page(self, index: int):
        for page in (self.page_import, self.page_reference,
                     self.page_review, self.page_export):
            page.refresh()
        self.stack.setCurrentIndex(index)
        self._refresh_nav()

    def _on_step(self, row: int):
        if row < 0 or row == self.stack.currentIndex():
            return
        locked, reason = self._step_locked(row)
        if locked:
            self.log(f"Step {row + 1} is locked: {reason}")
            return
        self.go_page(row)

    # ---- 步骤检查条（Phase 2）----
    def _step_states(self) -> list[bool]:
        annotated = len(self.results) > 0
        reviewed = annotated and all(
            res.status != "red" or self.confirmed.get(sid)
            for sid, res in self.results.items())
        # 4 步：1 Import&BLAST 就绪（序列+hits）→ 2 已注释 → 3 已审核 → 4 已导出
        return [
            len(self.sequences) > 0 and bool(self.hits),
            annotated,
            reviewed,
            self.exported,
        ]

    def _step_locked(self, row: int):
        states = self._step_states()
        for i in range(row):
            if not states[i]:
                return True, f"finish step {i + 1} first"
        return False, ""

    def _refresh_nav(self):
        states = self._step_states()
        cur = self.stack.currentIndex()
        marks = {"done": "\u2713  ", "cur": "\u25b6  ", "locked": "\u2022  ", "todo": "\u25cb  "}
        for i in range(self.nav.count()):
            item = self.nav.item(i)
            title = item.data(Qt.ItemDataRole.UserRole)
            done = states[i]
            locked = any(not s for s in states[:i])
            if i == cur:
                mark, bg, fg = marks["cur"], "#2D7DD2", "#ffffff"
            elif done:
                mark, bg, fg = marks["done"], "#eaf4ec", "#1a7f37"
            elif locked:
                mark, bg, fg = marks["locked"], None, "#8b949e"
            else:
                mark, bg, fg = marks["todo"], None, "#24292f"
            item.setText(mark + title)
            item.setBackground(QColor(bg) if bg else QColor(Qt.GlobalColor.transparent))
            item.setForeground(QColor(fg))
            font = item.font()
            font.setBold(i == cur)
            item.setFont(font)
        self.update_summary()

    def update_summary(self):
        """状态栏右侧单格摘要：序列数/基因型 + 注释进度与告警（彩色级别）。"""
        n = len(self.sequences)
        if not n:
            self.status_summary.setText("no sequences")
            self._set_status_level(self.status_summary, "")
            return

        genes = {s.gene_type for s in self.sequences if getattr(s, "gene_type", "")}
        text = f"{n} sequence(s)"
        if len(genes) == 1:
            text += f" \u00b7 {genes.pop()}"
        elif len(genes) > 1:
            text += f" \u00b7 {len(genes)} gene types"

        ann = len(self.results)
        warn = sum(1 for r in self.results.values()
                   if getattr(r, "status", "red") == "yellow")
        red = [sid for sid, r in self.results.items()
               if getattr(r, "status", "red") == "red"]
        open_red = sum(1 for sid in red if not self.confirmed.get(sid))
        if ann:
            parts = [f"annotated {ann}/{n}"]
            if warn:
                parts.append(f"{warn} warn")
            if red:
                parts.append(f"{len(red)} red"
                             + (f" ({open_red} unconfirmed)" if open_red else ""))
            if not warn and not red:
                parts.append("all clear")
            text += " \u00b7 " + " \u00b7 ".join(parts)

        self.status_summary.setText(text)
        self._set_status_level(self.status_summary,
                               "error" if red else "warn" if warn
                               else "ok" if ann else "")

    @staticmethod
    def _set_status_level(label: QLabel, level: str):
        """切换 QSS 的 [level=...] 分支：需 unpolish/polish 才会重绘。"""
        if label.property("level") == level:
            return
        label.setProperty("level", level)
        label.style().unpolish(label)
        label.style().polish(label)

    def log(self, text: str):
        """原日志坞由状态栏承接：最近一条消息留在状态栏左侧，直到被下一条替换。"""
        self.statusBar().showMessage(text)

    # ---- 序列状态维护（页面调用）----
    def load_fasta_file(self, path: str):
        from Bio import SeqIO
        for rec in SeqIO.parse(path, "fasta"):
            self.add_sequence(SeqInput(seq_id=str(rec.id), seq=str(rec.seq).upper()))
        self.log(f"Imported {path}")

    def add_sequence(self, s: SeqInput):
        if any(x.seq_id == s.seq_id for x in self.sequences):
            raise ValueError(f"Duplicate Seq ID: {s.seq_id}")
        self.sequences.append(s)
        self.selected_ref.setdefault(s.seq_id, None)
        self.update_summary()

    def remove_sequence(self, seq_id: str):
        self.sequences = [s for s in self.sequences if s.seq_id != seq_id]
        self.rename_sequence(seq_id, None)
        self.update_summary()

    def rename_sequence(self, old: str, new: str | None):
        if new is None:
            self.hits.pop(old, None)
            self.results.pop(old, None)
            self.selected_ref.pop(old, None)
            self.confirmed.pop(old, None)
        else:
            for store in (self.hits, self.results, self.selected_ref, self.confirmed):
                if old in store:
                    store[new] = store.pop(old)
            # SeqInput 与结果对象自身的 seq_id 同步改（导出文件名取自 res.seq_id）
            for s in self.sequences:
                if s.seq_id == old:
                    s.seq_id = new
            res = self.results.get(new)
            if res is not None and getattr(res, "seq_id", None) == old:
                res.seq_id = new
        self.update_summary()

    def reset_results(self):
        self.results.clear()
        self.hits.clear()
        self.confirmed.clear()
        self.selected_ref.clear()
        self.update_summary()

    # ---- 配置 ----
    def make_config(self) -> PipelineConfig:
        st = self.settings
        try:
            identity = float(st.get("identity_threshold", 97) or 97)
        except ValueError:
            identity = 97.0
        try:
            hitlist = int(st.get("hitlist_size", 50) or 50)
        except ValueError:
            hitlist = 50
        return PipelineConfig(
            email=st.get("email", ""), api_key=st.get("api_key", ""),
            blast_db=(st.get("blast_db") or "").strip() or "core_nt",
            organism_filter=st.get("organism_filter", ""),
            identity_threshold=identity, hitlist_size=hitlist,
            cache_dir=st.get("cache_dir") or None,
            auto_partial=bool(st.get("auto_partial", True)))

    # ---- 后台任务 ----
    def start_blast(self):
        self.blast_queue.reset()
        self._blast_pending = 0
        self._blast_running.clear()
        for s in self.sequences:
            if s.seq_id in self.hits:
                continue
            self.blast_queue.submit(BlastWorker(s, self.make_config(),
                                                self.blast_queue.signals))
            self._blast_pending += 1
            self._blast_running.add(s.seq_id)
        if self._blast_pending == 0:
            self.log("All sequences already have BLAST hits - continue to reference selection.")
            self.page_import.on_queue_finished()
            if self.sequences:
                self.go_page(1)
        else:
            self.page_import.progress.setMaximum(self._blast_pending)
            self.page_import.progress.setValue(0)

    def start_annotation(self):
        self.annotate_queue.reset()
        self._annotate_pending = 0
        for s in self.sequences:
            acc = self.selected_ref.get(s.seq_id)
            hits = None
            ref_acc = None
            if acc:
                # 行内单选存的是 accession：与已知命中匹配时按命中走
                # （保留 BLAST HSP 窗口截取信息），否则走直接下载通道（§6.1）
                hit = next((h for h in self.hits.get(s.seq_id, [])
                            if h.accession == acc), None)
                if hit is not None:
                    hits = [hit]
                else:
                    ref_acc = acc
            else:
                self.log(f"[{s.seq_id}] no reference chosen - skipped")
                continue
            self.annotate_queue.submit(AnnotateWorker(s, self.make_config(),
                                               self.annotate_queue.signals,
                                               hits=hits,
                                               reference_accession=ref_acc))
            self._annotate_pending += 1
        if self._annotate_pending == 0:
            self.log("Nothing to annotate.")
            self.page_reference.on_queue_finished()
        else:
            self.page_reference.progress.setMaximum(self._annotate_pending)
            self.page_reference.progress.setValue(0)

    def _on_worker_finished(self, seq_id: str, payload: object):
        # 依据 payload 类型区分队列：list=BlastHit 命中，SeqResult=注释结果
        from ..services.pipeline import SeqResult
        self.update_summary()
        if isinstance(payload, list):
            self._blast_running.discard(seq_id)
            if any(s.seq_id == seq_id for s in self.sequences):
                self.hits[seq_id] = payload   # 序列已被丢弃则不落陈旧命中
            self._blast_pending -= 1
            self.page_import.progress.setValue(
                self.page_import.progress.maximum() - self._blast_pending)
            self.page_import.refresh()        # 清单里该序列的 BLAST 状态即时更新
            if self._blast_pending <= 0:
                self.page_import.on_queue_finished()
                if self.sequences:            # 项目已丢弃则不再强制跳转
                    self.go_page(1)           # BLAST 排空 → 自动进入参考选择
        elif isinstance(payload, SeqResult):
            self.results[seq_id] = payload
            self._annotate_pending -= 1
            self.page_reference.progress.setValue(
                self.page_reference.progress.maximum() - self._annotate_pending)
            if self._annotate_pending <= 0:
                self.page_reference.on_queue_finished()

    def _on_worker_failed(self, seq_id: str, message: str):
        self.log(f"[{seq_id}] Failed: {message.splitlines()[-1] if message else ''}")
        self._blast_running.discard(seq_id)
        if seq_id in [s.seq_id for s in self.sequences]:
            if self._blast_pending > 0:
                self._blast_pending -= 1
                self.page_import.progress.setValue(
                    self.page_import.progress.maximum() - self._blast_pending)
                if self._blast_pending <= 0:
                    self.page_import.on_queue_finished()
                    self.go_page(1)         # 失败同样排空 → 跳转
            elif self._annotate_pending > 0:
                self._annotate_pending -= 1
                self.page_reference.progress.setValue(
                    self.page_reference.progress.maximum() - self._annotate_pending)
                if self._annotate_pending <= 0:
                    self.page_reference.on_queue_finished()

    def _on_worker_progress(self, seq_id: str, stage: str, frac: float):
        self.log(f"[{seq_id}] {stage} {frac:.0%}")

    # ---- 项目与设置 ----
    def _new_project(self):
        if self.sequences and QMessageBox.question(
                self, "New", "Discard the current project?") != QMessageBox.StandardButton.Yes:
            return
        self.sequences.clear()
        self.reset_results()
        self.exported = False
        self.page_import.refresh()
        self.go_page(0)

    def _save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", "project.fap.json",
                                              "fungal_annot project (*.json)")
        if not path:
            return
        save_project(path, self.sequences, self.hits, self.selected_ref,
                     self.results, self.settings, confirmed=self.confirmed,
                     exported=self.exported)
        self.log(f"Project saved: {path}")

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "",
                                              "fungal_annot project (*.json)")
        if not path:
            return
        try:
            (sequences, hits, selected_ref, results, settings,
             confirmed, exported) = load_project(path)
        except (OSError, ValueError, KeyError) as ex:
            QMessageBox.warning(self, "Failed to open", str(ex))
            return
        self.sequences = sequences
        self.hits = hits
        self.selected_ref = selected_ref
        self.results = results
        self.confirmed = confirmed      # 红灯确认随项目恢复，导出拦截状态一致
        self.exported = exported
        self._blast_running.clear()
        self.settings = settings or self.settings
        self.page_import.refresh()
        self.page_reference.refresh()
        self.page_review.refresh()
        self.page_export.refresh()
        self.update_summary()
        self._refresh_nav()
        self.log(f"Project loaded: {path} ({len(sequences)} sequence(s))")

    def _open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.values()
            save_settings(self.settings)
            self.page_import.refresh()
            self.log("Settings saved.")
