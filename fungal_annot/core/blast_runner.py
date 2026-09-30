"""在线 BLAST（NCBIWWW）+ 命中解析 + 参考排序（§6.1）。

排序规则：qcovs==100 优先 → 注释完整度（title 线索）→ 模式菌株/培养物记录 →
pident 降序。RefSeq 仅对 rRNA 类预设加分（蛋白编码 marker 无 RefSeq 覆盖）。
"""
import re
import threading
import time
from io import StringIO

from Bio.Blast import NCBIXML, NCBIWWW

from .models import BlastHit
from .presets import GenePreset

_CULTURE_RE = re.compile(
    r"(CBS\s?\d|ATCC\s?\d|CMCC|NRRL|DAOM|MUCL|IFF\s?\d|JCM|VKM|"
    r"ex[- ]?type|holotype|neotype|epitype|paratype|isotype|type\s+strain)", re.I)
_REFSEQ_RE = re.compile(r"\b(?:NC|NR|NG)_[0-9]+")


class BlastError(Exception):
    pass


class _SubmitThrottle:
    """全局共享的 BLAST 提交节流：并发池下相邻两次提交仍间隔 ≥ min_interval。

    NCBI URL API 礼仪：提交间隔 ≥ ~10 s（状态轮询由 Biopython 内部控制）。
    gb_fetcher.Throttle 无锁（Entrez 本就串行调用）；这里的 wait() 会被多个
    工作线程同时调用，用锁保证排队线程拿到互相错开的提交时刻。
    """

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self, min_interval: float | None = None):
        with self._lock:
            if min_interval is not None:
                self.min_interval = min_interval
            dt = time.monotonic() - self._last
            if dt < self.min_interval:
                time.sleep(self.min_interval - dt)
            self._last = time.monotonic()


SUBMIT_SPACING = 10.0            # NCBI URL API：提交间隔 ≥ ~10 s
_submit_throttle = _SubmitThrottle(SUBMIT_SPACING)


def run_blast(seq: str, blast_db: str = "core_nt", organism: str = "",
              hitlist_size: int = 50, retries: int = 3,
              submit_interval: float = SUBMIT_SPACING) -> list[BlastHit]:
    """提交在线 BLAST 并解析。organism 非 0 时作为 Entrez query 限定命中范围。

    NCBI URL API 单条通常 1–5 分钟；submit_interval 是**全局**相邻提交的
    最小间隔（由共享节流器执行）——并发池同时跑多条时，提交时刻仍互相
    错开。默认库为 core_nt（NCBI 已将 nt 并入 core_nt，API 层目前仍接受
    nt 别名）；库名为空时回退默认——空 DATABASE 会被 NCBI 以 Message
    ID#56 拒绝。
    """
    blast_db = (blast_db or "").strip() or "core_nt"
    last_ex = None
    for attempt in range(retries):
        try:
            _submit_throttle.wait(submit_interval)
            kwargs = {"hitlist_size": hitlist_size}
            if organism.strip():
                kwargs["entrez_query"] = organism.strip()
            handle = NCBIWWW.qblast("blastn", blast_db, seq, **kwargs)
            xml = handle.read()
            handle.close()
            return parse_qblast_xml(xml, query_len=len(seq))
        except Exception as ex:  # 网络/限流类异常统一退避重试
            if "Database string" in str(ex):
                raise BlastError(
                    f"Online BLAST rejected the database name '{blast_db}' "
                    "(NCBI Message ID#56). Check Settings > BLAST database "
                    "(use core_nt).") from ex
            last_ex = ex
            if attempt < retries - 1:
                time.sleep(5 * (2 ** attempt))
    raise BlastError(f"Online BLAST failed after {retries} attempts: {last_ex}")


def parse_qblast_xml(xml: str, query_len: int) -> list[BlastHit]:
    hits = []
    for rec in NCBIXML.parse(StringIO(xml)):
        for aln in rec.alignments:
            best_pid, best_hsp = -1.0, None
            spans = []
            for hsp in aln.hsps:
                pid = 100.0 * hsp.identities / max(1, hsp.align_length)
                if pid > best_pid:
                    best_pid, best_hsp = pid, hsp
                spans.append((hsp.query_start, hsp.query_end))  # NCBIXML: 1-based
            qcovs = 100.0 * _merged_len(spans) / max(1, query_len)
            flags = {
                "refseq": bool(_REFSEQ_RE.search(aln.accession)),
                "culture": bool(_CULTURE_RE.search(aln.title or "")),
                "complete_cds": "complete cds" in (aln.title or "").lower(),
                "partial_cds": "partial cds" in (aln.title or "").lower(),
            }
            hits.append(BlastHit(
                accession=aln.accession,
                title=aln.title or aln.hit_def,
                pident=round(best_pid, 2),
                qcovs=round(qcovs, 2),
                evalue=best_hsp.expect if best_hsp else 0.0,
                subject_len=aln.length,
                subject_start=min(h.sbjct_start for h in aln.hsps),
                subject_end=max(h.sbjct_end for h in aln.hsps),
                flags=flags,
            ))
    return hits


def rank_hits(hits: list[BlastHit], preset: GenePreset | None) -> list[BlastHit]:
    """§6.1 排序：qcovs==100 → 注释完整度+培养物/模式菌株线索 → pident。"""

    def key(h: BlastHit):
        completeness = 0
        if h.flags.get("complete_cds"):
            completeness = 3
        elif h.flags.get("partial_cds"):
            completeness = 1
        if h.flags.get("culture"):
            completeness += 2
        refseq_bonus = 1 if (h.flags.get("refseq") and preset and preset.kind == "rRNA") else 0
        return (1 if h.qcovs >= 99.95 else 0,
                completeness + refseq_bonus,
                h.pident)

    return sorted(hits, key=key, reverse=True)


def _merged_len(spans) -> int:
    spans = sorted(spans)
    total, cur_s, cur_e = 0, None, None
    for s, e in spans:
        if cur_s is None:
            cur_s, cur_e = s, e
        elif s <= cur_e + 1:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s + 1
            cur_s, cur_e = s, e
    if cur_s is not None:
        total += cur_e - cur_s + 1
    return total
