"""主窗口（§7.1）：左侧步骤导航 + 中央五页向导 + 底部日志坞；工具栏项目存取与设置。

状态中枢：sequences / hits / selected_ref / results / confirmed 由本对象持有，
各页面通过 win 引用读写。BLAST 队列串行（限速），注释队列小并发。
"""
import os

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
                             QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                             QLineEdit, QListWidgetItem, QListWidget, QMainWindow,
                             QMessageBox,
                             QStackedWidget, QToolBar, QVBoxLayout, QWidget)
from PyQt6.QtGui import QColor

from ..core.blast_runner import BlastHit
from ..core.models import SeqInput
from ..services.pipeline import PipelineConfig
from ..services.project_store import (load_project, load_settings,
                                      save_project, save_settings)
from ..services.worker import AnnotateWorker, BlastWorker, TaskQueue, WorkerSignals
from .pages.page_blast import PageBlast
from .pages.page_export import PageExport
from .pages.page_import import PageImport
from .pages.page_reference import PageReference
from .pages.page_review import PageReview
from .icons import icon
from .widgets.log_panel import LogPanel


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
                  ("table2asn_path", "table2asn path (optional)"),
                  ("table2asn_sbt", "table2asn template .sbt (optional)")]
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
        self.resize(1180, 760)

        # ---- 状态 ----
        self.settings = load_settings()
        self.sequences: list[SeqInput] = []
        self.hits: dict[str, list[BlastHit]] = {}
        self.selected_ref: dict[str, str | None] = {}
        self.results: dict[str, object] = {}
        self.confirmed: dict[str, bool] = {}
        self.local_ref_text: str | None = None
        self.local_ref_name: str | None = None
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

        # ---- 布局 ----
        self.nav = QListWidget()
        self.nav.setObjectName("NavList")
        self.stack = QStackedWidget()
        self.page_import = PageImport(self)
        self.page_blast = PageBlast(self)
        self.page_reference = PageReference(self)
        self.page_review = PageReview(self)
        self.page_export = PageExport(self)
        for page in (self.page_import, self.page_blast, self.page_reference,
                     self.page_review, self.page_export):
            self.stack.addWidget(page)
            item = QListWidgetItem(page.title)
            item.setData(Qt.ItemDataRole.UserRole, page.title)
            self.nav.addItem(item)
        self.nav.currentRowChanged.connect(self._on_nav)
        self.nav.setCurrentRow(0)

        central = QWidget()
        h = QHBoxLayout(central)
        h.addWidget(self.nav, 0)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.log_dock = LogPanel(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()          # 新手默认不看日志，工具栏可开关

        # ---- 工具栏 ----
        tb = QToolBar("Main toolbar")
        self.addToolBar(tb)
        for label, slot, icon_name in (("New", self._new_project, "fa5s.file"),
                                       ("Open Project...", self._open_project, "fa5s.folder-open"),
                                       ("Save Project", self._save_project, "fa5s.save"),
                                       ("Settings...", self._open_settings, "fa5s.cog")):
            act = tb.addAction(icon(icon_name), label)
            act.triggered.connect(slot)
        self.log_toggle = tb.addAction(icon("fa5s.terminal"), "Log")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setChecked(False)
        self.log_toggle.toggled.connect(self.log_dock.setVisible)

        # ---- 状态栏摘要 ----
        self.status_summary = QLabel("")
        self.statusBar().addPermanentWidget(self.status_summary)
        self.update_summary()

        # ---- 记住窗口几何与布局 ----
        settings = QSettings("fungal_annot", "fungal_annot")
        geom = settings.value("geometry")
        if geom is not None:
            self.restoreGeometry(geom)
        state = settings.value("windowState")
        if state is not None:
            self.restoreState(state)
        self._refresh_nav()          # 首屏即显示步骤标记

    def closeEvent(self, event):
        settings = QSettings("fungal_annot", "fungal_annot")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        super().closeEvent(event)

    # ---- 页面导航 ----
    def go_page(self, index: int):
        for page in (self.page_import, self.page_blast, self.page_reference,
                     self.page_review, self.page_export):
            page.refresh()
        self.stack.setCurrentIndex(index)
        self._refresh_nav()

    def _on_nav(self, row):
        if row < 0 or row == self.stack.currentIndex():
            return
        locked, reason = self._step_locked(row)
        if locked:
            self.log(f"Step {row + 1} is locked: {reason}")
            self.nav.blockSignals(True)
            self.nav.setCurrentRow(self.stack.currentIndex())
            self.nav.blockSignals(False)
            return
        self.go_page(row)

    # ---- 步骤检查条（Phase 2）----
    def _step_states(self) -> list[bool]:
        DOC = "done states: import / reference / annotate / review / export"
        annotated = len(self.results) > 0
        reviewed = annotated and all(
            res.status != "red" or self.confirmed.get(sid)
            for sid, res in self.results.items())
        return [
            len(self.sequences) > 0,
            bool(self.hits) or self.local_ref_text is not None,
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
                item.setText(marks["cur"] + title)
                item.setBackground(QColor("#2D7DD2"))
                item.setForeground(QColor("#ffffff"))
            elif done:
                item.setText(marks["done"] + title)
                item.setBackground(QColor("#eaf4ec"))
                item.setForeground(QColor("#1a7f37"))
            elif locked:
                item.setText(marks["locked"] + title)
                item.setBackground(QColor("transparent"))
                item.setForeground(QColor("#8b949e"))
            else:
                item.setText(marks["todo"] + title)
                item.setBackground(QColor("transparent"))
                item.setForeground(QColor("#24292f"))
        self.update_summary()

    def update_summary(self):
        n = len(self.sequences)
        ann = len(self.results)
        warn = sum(1 for r in self.results.values() if getattr(r, "status", "red") == "yellow")
        err = sum(1 for r in self.results.values() if getattr(r, "status", "red") == "red")
        text = f"{n} sequence(s) \u00b7 {ann} annotated"
        if warn:
            text += f" \u00b7 {warn} warn"
        if err:
            text += f" \u00b7 {err} red"
        self.status_summary.setText(text)

    def log(self, text: str):
        self.log_dock.append(text)

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

    def reset_results(self):
        self.results.clear()
        self.hits.clear()
        self.confirmed.clear()
        self.selected_ref.clear()
        self.update_summary()

    def set_gene_type(self, seq_id: str, gene_type: str):
        for s in self.sequences:
            if s.seq_id == seq_id:
                s.gene_type = gene_type

    def apply_source_to_all(self, quals: dict):
        for s in self.sequences:
            s.source_qualifiers.update(quals)

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

    def load_local_reference(self, path: str):
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        from ..core.gb_fetcher import parse_gb
        rec = parse_gb(text)
        if len(rec.seq) == 0:
            raise ValueError("Reference record has no sequence")
        self.local_ref_text = text
        self.local_ref_name = os.path.basename(path)

    # ---- 后台任务 ----
    def start_blast(self):
        self.blast_queue.reset()
        self._blast_pending = 0
        for s in self.sequences:
            if s.seq_id in self.hits:
                continue
            if not s.gene_type:
                self.log(f"[{s.seq_id}] No gene type set - skipped BLAST")
                continue
            self.blast_queue.submit(BlastWorker(s, self.make_config(),
                                                self.blast_queue.signals))
            self._blast_pending += 1
        if self._blast_pending == 0:
            self.log("All sequences already have BLAST hits - continue to reference selection.")
            self.page_blast.on_queue_finished()
        else:
            self.page_blast.progress.setMaximum(self._blast_pending)
            self.page_blast.progress.setValue(0)

    def start_annotation(self):
        self.annotate_queue.reset()
        self._annotate_pending = 0
        offline = self.local_ref_text is not None
        for s in self.sequences:
            ref_text = self.local_ref_text if offline else None
            acc = self.selected_ref.get(s.seq_id)
            hits = None
            ref_acc = None
            if not offline:
                if acc:
                    ref_acc = acc            # 直接 accession 通道（§6.1）
                else:
                    hits = self.hits.get(s.seq_id)
                    if not hits:
                        self.log(f"[{s.seq_id}] no BLAST hits and no accession given - skipped (run BLAST first)")
                        continue
            self.annotate_queue.submit(AnnotateWorker(s, self.make_config(),
                                               self.annotate_queue.signals,
                                               hits=hits,
                                               reference_gb_text=ref_text,
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
            self.hits[seq_id] = payload
            self._blast_pending -= 1
            self.page_blast.progress.setValue(
                self.page_blast.progress.maximum() - self._blast_pending)
            if self._blast_pending <= 0:
                self.page_blast.on_queue_finished()
                self.page_reference.refresh()
        elif isinstance(payload, SeqResult):
            self.results[seq_id] = payload
            self._annotate_pending -= 1
            self.page_reference.progress.setValue(
                self.page_reference.progress.maximum() - self._annotate_pending)
            if self._annotate_pending <= 0:
                self.page_reference.on_queue_finished()

    def _on_worker_failed(self, seq_id: str, message: str):
        self.log(f"[{seq_id}] Failed: {message.splitlines()[-1] if message else ''}")
        if seq_id in [s.seq_id for s in self.sequences]:
            if self._blast_pending > 0:
                self._blast_pending -= 1
                self.page_blast.progress.setValue(
                    self.page_blast.progress.maximum() - self._blast_pending)
                if self._blast_pending <= 0:
                    self.page_blast.on_queue_finished()
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
        self.local_ref_text = None
        self.local_ref_name = None
        self.exported = False
        self.page_import.refresh()
        self.page_blast.refresh()
        self.go_page(0)

    def _save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", "project.fap.json",
                                              "fungal_annot project (*.json)")
        if not path:
            return
        save_project(path, self.sequences, self.hits, self.selected_ref,
                     self.results, self.settings)
        self.log(f"Project saved: {path}")

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "",
                                              "fungal_annot project (*.json)")
        if not path:
            return
        try:
            sequences, hits, selected_ref, results, settings = load_project(path)
        except (OSError, ValueError, KeyError) as ex:
            QMessageBox.warning(self, "Failed to open", str(ex))
            return
        self.sequences = sequences
        self.hits = hits
        self.selected_ref = selected_ref
        self.results = results
        self.confirmed = {}
        self.settings = settings or self.settings
        self.page_import.refresh()
        self.page_reference.refresh()
        self.page_review.refresh()
        self.update_summary()
        self.log(f"Project loaded: {path} ({len(sequences)} sequence(s))")

    def _open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.values()
            save_settings(self.settings)
            self.page_blast.refresh()
            self.log("Settings saved.")
