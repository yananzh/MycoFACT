"""内部数据模型（纯 Python，不承载 Qt/Biopython 对象）。

坐标一律 1-based 闭区间（GenBank 风格）。
"""
from dataclasses import dataclass, field

# IUPAC 核苷酸歧义码（与 UI 导入框的裸序列校验同一字符集）；
# 比对导出的 gap '-' 与终止符 '*' 不在其中，导入时即拒绝
NUC_CHARS = frozenset("ACGTUNRYKMSWBDHV")


@dataclass
class SeqInput:
    seq_id: str
    seq: str
    gene_type: str = ""
    source_qualifiers: dict = field(default_factory=dict)  # key -> str

    def __post_init__(self):
        self.seq = "".join(self.seq.upper().split())
        bad = set(self.seq) - NUC_CHARS
        if bad:
            # 尽早失败（导入/改名处即报错），避免流入翻译/导出等深处才炸
            raise ValueError(
                f"'{self.seq_id}': non-nucleotide characters in the sequence: "
                + "".join(sorted(bad))[:10]
                + " (remove gaps/asterisks, e.g. from an alignment export)")


@dataclass
class BlastHit:
    accession: str
    title: str
    pident: float = 0.0
    qcovs: float = 0.0
    evalue: float = 0.0
    subject_len: int = 0
    subject_start: int = 0    # 最佳 HSP 在参考上的区间（1-based，供窗口截取）
    subject_end: int = 0
    flags: dict = field(default_factory=dict)


@dataclass
class FeaturePart:
    """单个连续区段。partial_low/high 绑定低/高坐标端（而非 5'/3' 端），
    反向互补转换时两标记对调——即计划 §6.5 的 '<'/'>' 换端语义。"""
    start: int
    end: int
    partial_low: bool = False
    partial_high: bool = False
    ref_start: int = 0        # 对应参考坐标（分 exon identity / 溯源用）
    ref_end: int = 0


@dataclass
class Feature:
    ftype: str
    strand: int = 1                                 # +1 / -1（宿主序列坐标系）
    parts: list = field(default_factory=list)       # [FeaturePart]，按 start 升序
    qualifiers: dict = field(default_factory=dict)  # key -> [str, ...]
    ref_key: tuple | None = None                    # 迁移结果：来源参考 feature 的坐标区间

    @property
    def start(self):
        return self.parts[0].start

    @property
    def end(self):
        return self.parts[-1].end


@dataclass
class Issue:
    level: str    # error / warning / info
    code: str
    message: str


@dataclass
class Provenance:
    """结果溯源（§6.7 验证报告）：参考来源、窗口、比对指标。"""
    source: str = ""            # blast / accession / local-gb
    reference: str = ""         # accession（尽量带版本号）
    region: str = ""            # "full" 或 "a..b"（窗口截取区间）
    orientation: str = "forward"
    pident: float | None = None
    qcovs: float | None = None
    nt_identity: float | None = None


@dataclass
class Mapping:
    """参考→查询坐标映射（§6.4）。反向互补时查询坐标处于 RC 空间，
    由 feature_transfer 统一换算回宿主坐标。"""
    orientation: str = "forward"   # forward / reverse
    ref_to_query: dict = field(default_factory=dict)
    blocks: list = field(default_factory=list)   # (ref_s, ref_e, q_s, q_e)，1-based 闭区间
    ref_seq: str = ""
    query_seq: str = ""            # 与映射同空间（reverse 时为 RC 序列）
    _sorted_refs: list = field(default_factory=list, repr=False)

    @property
    def aligned_ref_interval(self):
        """查询覆盖到的参考区间（1-based 闭区间）——§6.5 exon 内/外判定的基准。"""
        return (self.blocks[0][0], self.blocks[-1][1])

    def map_point(self, ref_pos: int, direction: str):
        """精确映射；否则按 direction（'right'/'left'）收缩到最近可映射碱基。
        返回 (query_pos, shrunk)；区间外或无候选返回 (None, False)。"""
        q = self.ref_to_query.get(ref_pos)
        if q is not None:
            return q, False
        lo, hi = self.aligned_ref_interval
        if not (lo <= ref_pos <= hi):
            return None, False
        import bisect
        i = bisect.bisect_left(self._sorted_refs, ref_pos)
        if direction == "right" and i < len(self._sorted_refs):
            return self.ref_to_query[self._sorted_refs[i]], True
        if direction == "left" and i > 0:
            return self.ref_to_query[self._sorted_refs[i - 1]], True
        return None, False

    def identity(self, ref_span=None):
        """比对恒等度；ref_span=(起,止) 时只统计该参考区间（分 exon identity 用）。"""
        tot = eq = 0
        for (rs, re_, _qs, _qe) in self.blocks:
            s = rs if ref_span is None else max(rs, ref_span[0])
            e = re_ if ref_span is None else min(re_, ref_span[1])
            for p in range(s, e + 1):
                tot += 1
                if self.ref_seq[p - 1] == self.query_seq[self.ref_to_query[p] - 1]:
                    eq += 1
        return (eq / tot) if tot else None
