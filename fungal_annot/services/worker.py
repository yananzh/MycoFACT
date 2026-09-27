"""后台任务封装（§7.3）：QThreadPool + QRunnable + 信号驱动 UI。

BLAST/下载限速：QThreadPool maxThreadCount=1 串行执行队列（§6.1 限速队列）；
单条 BLAST 进行中无法中断（NCBIWWW 阻塞调用），"取消"阻止剩余序列入队。
"""
import traceback

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from ..core.blast_runner import rank_hits, run_blast
from ..core.presets import get as get_preset
from .pipeline import annotate_sequence


class WorkerSignals(QObject):
    progress = pyqtSignal(str, str, float)   # seq_id, stage, fraction
    log = pyqtSignal(str)
    finished = pyqtSignal(str, object)       # seq_id, SeqResult
    failed = pyqtSignal(str, str)            # seq_id, 错误摘要


class AnnotateWorker(QRunnable):
    def __init__(self, seq_input, cfg, signals: WorkerSignals,
                 hits=None, reference_gb_text=None, reference_accession=None):
        super().__init__()
        self.seq = seq_input
        self.cfg = cfg
        self.signals = signals
        self.hits = hits
        self.reference_gb_text = reference_gb_text
        self.reference_accession = reference_accession

    def run(self):  # noqa: D102 线程入口
        try:
            self.signals.log.emit(f"[{self.seq.seq_id}] Processing ({self.seq.gene_type})")

            def cb(stage, frac):
                self.signals.progress.emit(self.seq.seq_id, stage, float(frac))

            res = annotate_sequence(
                self.seq, self.cfg, hits=self.hits,
                reference_gb_text=self.reference_gb_text,
                reference_accession=self.reference_accession, progress=cb)
            self.signals.finished.emit(self.seq.seq_id, res)
            self.signals.log.emit(f"[{self.seq.seq_id}] Done: status {res.status},"
                                  f"{len(res.issues)} issue(s)")
        except Exception:  # 后台线程兜底：任何异常都必须回到 UI 线程
            self.signals.failed.emit(self.seq.seq_id, traceback.format_exc(limit=3))
            self.signals.log.emit(f"[{self.seq.seq_id}] Failed")


class BlastWorker(QRunnable):
    """P2：仅执行在线 BLAST 并排序（§6.1），不含下载与注释。"""

    def __init__(self, seq_input, cfg, signals: WorkerSignals):
        super().__init__()
        self.seq = seq_input
        self.cfg = cfg
        self.signals = signals

    def run(self):
        try:
            self.signals.log.emit(f"[{self.seq.seq_id}] Online BLAST running"
                                  "(~1-5 min per sequence, rate-limited serial queue)...")
            hits = run_blast(self.seq.seq, blast_db=self.cfg.blast_db,
                             organism=self.cfg.organism_filter,
                             hitlist_size=self.cfg.hitlist_size)
            preset = get_preset(self.seq.gene_type)
            hits = rank_hits(hits, preset)
            self.signals.finished.emit(self.seq.seq_id, hits)
            self.signals.log.emit(f"[{self.seq.seq_id}] BLAST done: {len(hits)} hit(s)")
        except Exception:  # 网络/限流异常统一回 UI 线程
            self.signals.failed.emit(self.seq.seq_id, traceback.format_exc(limit=3))
            self.signals.log.emit(f"[{self.seq.seq_id}] BLAST failed")


class TaskQueue:
    """页面持有的任务队列：串行（限速）或小并发，支持阻止剩余任务入队。

    队列持有已提交 QRunnable 的 Python 引用——否则包装器可能在执行中被 GC，
    触发段错误（PyQt QRunnable 的经典崩溃模式）。
    """

    def __init__(self, max_threads: int = 1):
        self.cancel_requested = False
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(max_threads)
        self._signals = WorkerSignals()
        self._refs: list = []

    @property
    def signals(self) -> WorkerSignals:
        return self._signals

    def submit(self, worker: AnnotateWorker):
        if self.cancel_requested:
            self.signals.log.emit("Cancelled: skipping remaining tasks")
            return
        self._refs.append(worker)
        if len(self._refs) > 500:          # 兜底清理，防止长会话无限增长
            del self._refs[:250]
        self._pool.start(worker)

    def cancel(self):
        self.cancel_requested = True

    def reset(self):
        self.cancel_requested = False

    def wait(self, msecs: int = 30000):
        self._pool.waitForDone(msecs)
