"""主窗口（§7.1）：顶部水平步骤条 + 中央四页向导 + 底部状态栏；菜单栏仅
Settings / Guide / About 三个直接动作（点击即执行，无下拉子菜单）。
消息与摘要都收敛到状态栏（左侧最近消息 + 右侧单格摘要：序列数/基因型 + 注释进度与告警；
步骤与导出进度由顶部步骤条表达，参考信息在对应页面内展示）。

状态中枢：sequences / hits / selected_refs / results / chosen_ref / confirmed 由本对象持有，
各页面通过 win 引用读写。results[seq_id] = {参考accession → SeqResult}（多参考对比，
2026-09-29）；BLAST 队列小并发（默认 3，全局提交间隔由共享节流器限速 ≥10 s），
注释队列小并发、按（序列 × 参考）成对提交。
"""
import os

from PyQt6.QtCore import QSettings, QSize, Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                             QLabel, QLineEdit, QListWidgetItem, QMainWindow,
                             QMessageBox, QStackedWidget, QVBoxLayout, QWidget)
from PyQt6.QtGui import QColor, QGuiApplication

from ..core.blast_runner import BlastHit
from ..core.models import SeqInput
from ..services.pipeline import PipelineConfig
from ..services.project_store import load_settings, save_settings
from ..services.worker import AnnotateWorker, BlastWorker, TaskQueue
from .pages.page_export import PageExport
from .pages.page_import import PageImport
from .pages.page_reference import PageReference
from .pages.page_review import PageReview
from .widgets.about import AboutDialog
from .widgets.help import show_app_guide
from .widgets.step_bar import StepBar


class SettingsDialog(QDialog):
    """设置弹窗（简化版）：只露出普通用户需要的三项——NCBI 邮箱（BLAST 必需）、
    identity 阈值（决定红灯复核线）、每序列对比参考数；其余高级项（api_key /
    blast_db / organism_filter / hitlist_size / cache_dir / auto_partial）不再
    展示，由 make_config 的默认值兜底，settings.json 里已有的值保存时原样带回。"""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._base = dict(settings)     # 未露出的键不因保存而丢失
        self.setWindowTitle("Settings")
        form = QFormLayout(self)
        self.edits = {}
        fields = [("email", "NCBI contact email (required)"),
                  ("identity_threshold", "identity threshold %"),
                  ("default_refs", "References compared per sequence (1-5)"),
                  ("blast_concurrency", "Concurrent BLAST submissions (1-4)")]
        # 与 make_config 的兜底默认值保持一致（identity_threshold 空白会被误读为未设置）
        defaults = {"identity_threshold": "97", "default_refs": "3",
                    "blast_concurrency": "3"}
        hints = {"email": "NCBI uses this to contact you about the submission.",
                 "identity_threshold": "Below this identity a sequence is "
                                       "flagged RED for manual review.",
                 "blast_concurrency": "How many BLAST jobs run in parallel; "
                                      "submissions stay rate-limited (>=10 s "
                                      "apart). Higher risks NCBI throttling."}
        for key, label in fields:
            edit = QLineEdit(str(settings.get(key) or defaults.get(key, "")))
            self.edits[key] = edit
            form.addRow(label, edit)
            if key in hints:
                hint = QLabel(hints[key])
                hint.setObjectName("Hint")
                hint.setWordWrap(True)      # 提示行跨两列折行，不撑宽弹窗
                form.addRow(hint)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        # 四行表单无需大弹窗：直接贴 sizeHint（不得再手动放大）
        self.resize(self.sizeHint())

    def values(self) -> dict:
        d = dict(self._base)
        d.update({k: e.text().strip() for k, e in self.edits.items()})
        return d


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MycoFACT - Fungal Feature Annotation & Comparison Tool")
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
        # 多参考对比（2026-09-29）：每序列可选 1-5 个参考；results[seq_id] 是
        # {参考accession → SeqResult} 的 variant 表；chosen_ref 为采纳导出的 variant
        self.selected_refs: dict[str, list[str]] = {}
        self.results: dict[str, dict[str, object]] = {}
        self.chosen_ref: dict[str, str] = {}
        self.confirmed: dict[str, bool] = {}
        self._blast_running: set[str] = set()   # 已提交 BLAST、尚未返回的序列
        self.last_export_dir = os.path.join(os.path.expanduser("~"), "fungal_annot_out")
        self.exported = False

        # ---- 任务队列 ----
        self.blast_queue = TaskQueue(max_threads=self._blast_concurrency())
        # 并发提交池：线程内各自跑完整 BLAST，全局提交间隔由共享节流器保证（§6.1）
        self.annotate_queue = TaskQueue(max_threads=2)
        self._blast_pending = 0
        self._annotate_pending = 0
        # 两条队列的回调分开连接（payload 类型不同、排空路径各自独立）；
        # 计数递减收敛到 _after_*_task，成功/失败/跳过严格对称
        bq, aq = self.blast_queue.signals, self.annotate_queue.signals
        bq.finished.connect(self._on_blast_finished)
        bq.failed.connect(self._on_blast_failed)
        bq.skipped.connect(self._on_blast_skipped)
        bq.log.connect(self.log)
        bq.progress.connect(self._on_worker_progress)
        aq.finished.connect(self._on_annotate_finished)
        aq.failed.connect(self._on_annotate_failed)
        aq.skipped.connect(self._on_annotate_skipped)
        aq.log.connect(self.log)
        aq.progress.connect(self._on_worker_progress)

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

        # ---- 菜单栏：四个直接动作（点击即执行，无子菜单，无快捷键）----
        bar = self.menuBar()
        act = bar.addAction("Settings")
        act.triggered.connect(self._open_settings)
        act = bar.addAction("Guide")
        act.triggered.connect(self._show_app_guide)
        act = bar.addAction("About")
        act.triggered.connect(self._show_about)

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
        annotated = any(self.results.values())
        # 已审核 = 每条已注释序列都有采纳结果；红灯序列的知情确认挪到
        # 导出页导出弹窗（page_export._export），不再阻断第 4 步入口
        reviewed = annotated and all(
            (res := self.chosen_result(s.seq_id)) is not None
            for s in self.sequences if self.results.get(s.seq_id))
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
                return True, self._step_block_reason(i)
        return False, ""

    def _step_block_reason(self, step: int) -> str:
        """第 step 步（0 基）未完成的具体原因；步骤条悬停提示与点击日志共用。"""
        if step == 0:
            if not self.sequences:
                return "step 1 has no sequences yet - paste FASTA and run BLAST"
            return "step 1 has no BLAST hits yet - run BLAST (or wait for the queue)"
        if step == 1:
            return "step 2 has no annotation results yet - start annotation"
        return "step 3 is not fully reviewed - adopt a result per sequence"

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
            # 锁定的步骤悬停即显示缺什么（QListWidget 默认按 ToolTipRole 弹出）
            block = next((j for j, s in enumerate(states[:i]) if not s), None)
            item.setToolTip("" if block is None else
                            f"Locked - {self._step_block_reason(block)}")
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

        ann = sum(1 for s in self.sequences if self.results.get(s.seq_id))
        chosen = [self.chosen_result(s.seq_id) for s in self.sequences
                  if self.results.get(s.seq_id)]
        warn = sum(1 for r in chosen if getattr(r, "status", "red") == "yellow")
        red = [s.seq_id for s in self.sequences if self.results.get(s.seq_id)
               and getattr(self.chosen_result(s.seq_id), "status", "red") == "red"]
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
    def chosen_accession(self, seq_id: str) -> str | None:
        """采纳（导出/步骤状态用）的 variant accession；未显式采纳时取第一个。"""
        variants = self.results.get(seq_id)
        if not variants:
            return None
        acc = self.chosen_ref.get(seq_id)
        return acc if acc in variants else next(iter(variants))

    def chosen_result(self, seq_id: str):
        return (self.results.get(seq_id) or {}).get(self.chosen_accession(seq_id) or "")

    def load_fasta_file(self, path: str):
        from Bio import SeqIO
        for rec in SeqIO.parse(path, "fasta"):
            self.add_sequence(SeqInput(seq_id=str(rec.id), seq=str(rec.seq).upper()))
        self.log(f"Imported {path}")

    def add_sequence(self, s: SeqInput):
        if any(x.seq_id == s.seq_id for x in self.sequences):
            raise ValueError(f"Duplicate Seq ID: {s.seq_id}")
        self.sequences.append(s)
        self.selected_refs.setdefault(s.seq_id, [])
        self.update_summary()

    def remove_sequence(self, seq_id: str):
        self.sequences = [s for s in self.sequences if s.seq_id != seq_id]
        self.rename_sequence(seq_id, None)
        self.update_summary()

    def rename_sequence(self, old: str, new: str | None):
        if new is None:
            self.hits.pop(old, None)
            self.results.pop(old, None)
            self.selected_refs.pop(old, None)
            self.chosen_ref.pop(old, None)
            self.confirmed.pop(old, None)
        else:
            for store in (self.hits, self.selected_refs, self.chosen_ref, self.confirmed):
                if old in store:
                    store[new] = store.pop(old)
            if old in self.results:
                self.results[new] = self.results.pop(old)
            # SeqInput 与结果对象自身的 seq_id 同步改（导出文件名取自 res.seq_id）
            for s in self.sequences:
                if s.seq_id == old:
                    s.seq_id = new
            for res in self.results.get(new, {}).values():
                if getattr(res, "seq_id", None) == old:
                    res.seq_id = new
        self.update_summary()

    def reset_results(self):
        self.results.clear()
        self.hits.clear()
        self.chosen_ref.clear()
        self.selected_refs.clear()
        self.confirmed.clear()
        self.update_summary()

    # ---- 配置 ----
    def _blast_concurrency(self) -> int:
        """BLAST 并发提交数（Settings 项 blast_concurrency，夹在 1-4，默认 3）。"""
        try:
            n = int(self.settings.get("blast_concurrency", 3) or 3)
        except (TypeError, ValueError):
            n = 3
        return min(4, max(1, n))

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
        gen = self.blast_queue.gen
        for s in self.sequences:
            if s.seq_id in self.hits:
                continue
            self.blast_queue.submit(BlastWorker(s, self.make_config(),
                                                self.blast_queue, gen))
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
        """按（序列 × 选中参考）成对提交：同一序列对多个参考各注释一次，
        结果按 ref_key 落账，供审核页对比与采纳。"""
        self.annotate_queue.reset()
        self._annotate_pending = 0
        gen = self.annotate_queue.gen
        for s in self.sequences:
            selected = (self.selected_refs.get(s.seq_id) or [])[:5]
            if not selected:
                self.log(f"[{s.seq_id}] no reference chosen - skipped")
                continue
            for acc in selected:
                # 行内勾选存的是 accession：与已知命中匹配时按命中走
                # （保留 BLAST HSP 窗口截取信息），否则走直接下载通道（§6.1）
                hit = next((h for h in self.hits.get(s.seq_id, [])
                            if h.accession == acc), None)
                hits = [hit] if hit is not None else None
                ref_acc = None if hit is not None else acc
                self.annotate_queue.submit(AnnotateWorker(s, self.make_config(),
                                                          self.annotate_queue, gen,
                                                          hits=hits,
                                                          reference_accession=ref_acc,
                                                          ref_key=acc))
                self._annotate_pending += 1
        if self._annotate_pending == 0:
            self.log("Nothing to annotate.")
            self.page_reference.on_queue_finished()
        else:
            self.page_reference.progress.setMaximum(self._annotate_pending)
            self.page_reference.progress.setValue(0)

    # gen（批次代次号）不匹配 = 项目丢弃后迟到的回调：整条丢弃，不碰任何状态
    def _on_blast_finished(self, gen: int, seq_id: str, ref_key: str, hits: list):
        if gen != self.blast_queue.gen:
            return
        self._blast_running.discard(seq_id)
        if any(s.seq_id == seq_id for s in self.sequences):
            self.hits[seq_id] = hits         # 序列已被丢弃则不落陈旧命中
        self._after_blast_task()

    def _on_blast_failed(self, gen: int, seq_id: str, ref_key: str, message: str):
        self.log(f"[{seq_id}] Failed: {message.splitlines()[-1] if message else ''}")
        if gen != self.blast_queue.gen:
            return
        self._blast_running.discard(seq_id)
        self._after_blast_task()

    def _on_blast_skipped(self, gen: int, seq_id: str, ref_key: str):
        if gen != self.blast_queue.gen:
            return
        self._blast_running.discard(seq_id)
        self._after_blast_task()

    def _after_blast_task(self):
        """每条 BLAST 任务（完成/失败/跳过）统一走这里：计数只在此递减，
        三条路径严格对称——否则 pending 永不归零，Start 按钮永久禁用。"""
        self.update_summary()
        self._blast_pending -= 1
        self.page_import.progress.setValue(
            self.page_import.progress.maximum() - max(self._blast_pending, 0))
        self.page_import.refresh()           # 清单里该序列的 BLAST 状态即时更新
        if self._blast_pending <= 0:
            self.page_import.on_queue_finished()
            if self.sequences:               # 项目已丢弃则不再强制跳转
                self.go_page(1)              # BLAST 排空 → 自动进入参考选择

    def _on_annotate_finished(self, gen: int, seq_id: str, ref_key: str, result: object):
        if gen != self.annotate_queue.gen:
            return
        if any(s.seq_id == seq_id for s in self.sequences):
            self.results.setdefault(seq_id, {})[ref_key] = result
            # 首个返回者默认采纳（按排名序提交，通常即推荐命中）；可随后在审核页改采
            self.chosen_ref.setdefault(seq_id, ref_key)
        self._after_annotate_task()

    def _on_annotate_failed(self, gen: int, seq_id: str, ref_key: str, message: str):
        self.log(f"[{seq_id}] Failed vs {ref_key}: "
                 f"{message.splitlines()[-1] if message else ''}")
        if gen != self.annotate_queue.gen:
            return
        self._after_annotate_task()

    def _on_annotate_skipped(self, gen: int, seq_id: str, ref_key: str):
        if gen != self.annotate_queue.gen:
            return
        self._after_annotate_task()

    def _reconcile_chosen(self):
        """队列排空后校正采纳者：采纳的 variant 失败/被跳过时回落到首个可用者。"""
        for sid, variants in self.results.items():
            if not variants:
                self.chosen_ref.pop(sid, None)
            elif self.chosen_ref.get(sid) not in variants:
                self.chosen_ref[sid] = next(iter(variants))

    def _after_annotate_task(self):
        self.update_summary()
        self._annotate_pending -= 1
        self.page_reference.progress.setValue(
            self.page_reference.progress.maximum() - max(self._annotate_pending, 0))
        if self._annotate_pending <= 0:
            self._reconcile_chosen()
            self.page_reference.on_queue_finished()

    def _on_worker_progress(self, seq_id: str, stage: str, frac: float):
        self.log(f"[{seq_id}] {stage} {frac:.0%}")

    # ---- 项目与设置 ----
    def _abandon_queues(self):
        """丢弃当前项目态（New/Open/Clear 公共路径）：取消两个队列并作废在途回调，
        迟到的 finished/failed 不会写进新项目数据、也不会消耗新批次的计数。"""
        self.blast_queue.invalidate()
        self.annotate_queue.invalidate()
        self._blast_pending = 0
        self._annotate_pending = 0
        self._blast_running.clear()

    def _open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.values()
            save_settings(self.settings)
            self.blast_queue.set_max_threads(self._blast_concurrency())
            self.page_import.refresh()
            self.log("Settings saved.")

    def _show_app_guide(self):
        """菜单 Guide：全软件使用指南（四步流程、设置、状态规则、提交路径）；
        单页的操作细节由各页按钮区的 Help 提供，两者不混用。"""
        show_app_guide(self)

    def _show_about(self):
        from .. import __version__
        AboutDialog(__version__, self).exec()
