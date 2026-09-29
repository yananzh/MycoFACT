"""后台任务封装（§7.3）：QThreadPool + QRunnable + 信号驱动 UI。

BLAST/下载限速：QThreadPool maxThreadCount=1 串行执行队列（§6.1 限速队列）。
单条 BLAST 进行中无法中断（NCBIWWW 阻塞调用）；STOP 后尚未开始的任务在 run()
入口被跳过（skipped 信号），进行中的一条做完即排空。

信号带批次代次号（gen）：项目丢弃（New/Open/Clear）会作废旧批次，迟到的
finished/failed 由 UI 按代次号丢弃，不会写进新项目数据。
"""
import traceback

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from ..core.blast_runner import rank_hits, run_blast
from ..core.presets import get as get_preset
from .pipeline import annotate_sequence


class WorkerSignals(QObject):
    progress = pyqtSignal(str, str, float)   # seq_id, stage, fraction
    log = pyqtSignal(str)
    finished = pyqtSignal(int, str, object)  # gen, seq_id, payload（hits list / SeqResult）
    failed = pyqtSignal(int, str, str)       # gen, seq_id, 错误摘要
    skipped = pyqtSignal(int, str)           # gen, seq_id（取消/作废后未执行的任务）


class _QueueWorker(QRunnable):
    """TaskQueue 成员的公共骨架：取消检查 + 执行完自释放包装引用。

    队列持有已提交 QRunnable 的 Python 引用——否则包装器可能在执行中被 GC，
    触发段错误（PyQt QRunnable 的经典崩溃模式）；引用只在执行前需要，
    因此由 worker 在 run() 结束时自行 release，不靠会误删在途任务的兜底清理。
    """

    def __init__(self, seq_input, queue: "TaskQueue", gen: int):
        super().__init__()
        self.seq = seq_input
        self.queue = queue
        self.gen = gen
        self.signals = queue.signals

    def _cancelled(self) -> bool:
        """STOP（cancel）或批次已作废（项目丢弃导致代次号变更）→ 本任务不执行。"""
        return self.queue.cancel_requested or self.gen != self.queue.gen

    def _skip(self):
        self.signals.log.emit(f"[{self.seq.seq_id}] Cancelled - skipped")
        self.signals.skipped.emit(self.gen, self.seq.seq_id)


class AnnotateWorker(_QueueWorker):
    def __init__(self, seq_input, cfg, queue: "TaskQueue", gen: int,
                 hits=None, reference_gb_text=None, reference_accession=None):
        super().__init__(seq_input, queue, gen)
        self.cfg = cfg
        self.hits = hits
        self.reference_gb_text = reference_gb_text
        self.reference_accession = reference_accession

    def run(self):  # noqa: D102 线程入口
        try:
            if self._cancelled():
                self._skip()
                return
            self.signals.log.emit(f"[{self.seq.seq_id}] Processing ({self.seq.gene_type})")

            def cb(stage, frac):
                self.signals.progress.emit(self.seq.seq_id, stage, float(frac))

            res = annotate_sequence(
                self.seq, self.cfg, hits=self.hits,
                reference_gb_text=self.reference_gb_text,
                reference_accession=self.reference_accession, progress=cb)
            self.signals.finished.emit(self.gen, self.seq.seq_id, res)
            self.signals.log.emit(f"[{self.seq.seq_id}] Done: status {res.status},"
                                  f" {len(res.issues)} issue(s)")
        except Exception:  # 后台线程兜底：任何异常都必须回到 UI 线程
            self.signals.failed.emit(self.gen, self.seq.seq_id,
                                     traceback.format_exc(limit=3))
            self.signals.log.emit(f"[{self.seq.seq_id}] Failed")
        finally:
            self.queue.release(self)


class BlastWorker(_QueueWorker):
    """P2：仅执行在线 BLAST 并排序（§6.1），不含下载与注释。"""

    def __init__(self, seq_input, cfg, queue: "TaskQueue", gen: int):
        super().__init__(seq_input, queue, gen)
        self.cfg = cfg

    def run(self):
        try:
            if self._cancelled():
                self._skip()
                return
            self.signals.log.emit(f"[{self.seq.seq_id}] Online BLAST running "
                                  "(~1-5 min per sequence, rate-limited serial queue)...")
            hits = run_blast(self.seq.seq, blast_db=self.cfg.blast_db,
                             organism=self.cfg.organism_filter,
                             hitlist_size=self.cfg.hitlist_size)
            preset = get_preset(self.seq.gene_type)
            hits = rank_hits(hits, preset)
            self.signals.finished.emit(self.gen, self.seq.seq_id, hits)
            self.signals.log.emit(f"[{self.seq.seq_id}] BLAST done: {len(hits)} hit(s)")
        except Exception:  # 网络/限流异常统一回 UI 线程
            self.signals.failed.emit(self.gen, self.seq.seq_id,
                                     traceback.format_exc(limit=3))
            self.signals.log.emit(f"[{self.seq.seq_id}] BLAST failed")
        finally:
            self.queue.release(self)


class TaskQueue:
    """页面持有的任务队列：串行（限速）或小并发，支持 STOP 跳过剩余任务。

    cancel() 后：进行中的一条无法中断（NCBIWWW 阻塞调用），做完照常计数；
    尚未开始的任务在 run() 入口检查 cancel_requested / 代次号后跳过（skipped），
    由 UI 走与失败相同的排空路径。invalidate() 额外推进代次号，用于项目丢弃时
    作废全部在途回调（含执行中那条的迟到结果）。
    """

    def __init__(self, max_threads: int = 1):
        self.gen = 0                     # 批次代次：reset/invalidate 时 +1
        self.cancel_requested = False
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(max_threads)
        self._signals = WorkerSignals()
        self._refs: list = []

    @property
    def signals(self) -> WorkerSignals:
        return self._signals

    def submit(self, worker):
        self._refs.append(worker)
        self._pool.start(worker)

    def release(self, worker):
        """任务执行完毕后移除其包装引用（_QueueWorker 在 run() 的 finally 调用）。"""
        try:
            self._refs.remove(worker)
        except ValueError:
            pass

    def cancel(self):
        self.cancel_requested = True
        self.signals.log.emit("Cancel requested - the running task will finish, "
                              "queued tasks are skipped")

    def invalidate(self):
        """作废整个批次（项目丢弃/清空）：未执行的任务跳过，已发出的回调按代次号作废。"""
        self.cancel_requested = True
        self.gen += 1

    def reset(self):
        """新一批发任务前调用（此时上一批必须已排空，迟到的旧回调不存在）。"""
        self.cancel_requested = False
        self.gen += 1

    def wait(self, msecs: int = 30000):
        self._pool.waitForDone(msecs)
