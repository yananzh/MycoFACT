"""局部比对（Smith-Waterman）+ ref→query 坐标映射（§6.4 核心算法）。

比对范围约束：调用方必须传入已截取的参考窗口（短参考可整体），
禁止对未截取的长记录做全序列比对。
"""
from Bio.Align import PairwiseAligner
from Bio.Seq import Seq

from .models import Mapping


class AlignmentError(Exception):
    pass


def revcomp(s: str) -> str:
    return str(Seq(s).reverse_complement())


def _make_aligner():
    """Smith-Waterman 局部比对。查询是参考（BLAST 窗口或 marker 记录）的内部片段，
    局部比对天然把非匹配侧翼排除在比对之外。

    实测（Biopython 1.86）：计划最初设想的 "global + target end gap=0" 的 glocal
    写法会把查询错位锚定到侧翼（总体得分反而更低），不可用；"查询 100% 覆盖"
    改由 _blocks_and_map 的覆盖断言保证，断言失败即 AlignmentError。
    """
    al = PairwiseAligner()
    al.mode = "local"
    al.match_score = 2
    al.mismatch_score = -1
    al.open_gap_score = -5
    al.extend_gap_score = -1
    return al


def _blocks_and_map(alignment, query_used: str):
    t_arr, q_arr = alignment.aligned
    blocks, d = [], {}
    for (ts, te), (qs, qe) in zip(t_arr, q_arr):
        blocks.append((ts + 1, te, qs + 1, qe))
        for i in range(te - ts):
            d[ts + 1 + i] = qs + 1 + i
    # 查询 100% 进入比对的判定用 coordinates（含 gap 列）：查询中插入参考的碱基
    # 比对到参考 gap，不出现在 aligned 块里，但确实被比对消费。
    coords = alignment.coordinates
    q_span = coords[1]
    if (not blocks or int(q_span[0]) != 0 or int(q_span[-1]) != len(query_used)):
        raise AlignmentError(
            "Query was not 100% contained in the alignment (ends trimmed): the reference does not cover the full query, or the sequence is anomalous")
    blocks.sort()
    return blocks, d


def build_mapping(ref_seq: str, query_seq: str) -> Mapping:
    """正向/反向互补各比一次，取得分高者（并列取正向）。

    反向时映射字典的值处于 RC 空间，query_seq 字段存 RC 序列；
    坐标换算由 feature_transfer 统一处理。
    注意：不得对 alignments 对象调用 len()——end gap 置 0 时最优解数量是
    天文数字，len 会溢出；.score 与 [0] 均为惰性求值，安全。
    """
    if len(ref_seq) < len(query_seq):
        raise AlignmentError(
            f"Reference ({len(ref_seq)} bp) is shorter than query ({len(query_seq)} bp): reference must cover the whole query")
    al = _make_aligner()
    fwd = al.align(ref_seq, query_seq)
    qry_rc = revcomp(query_seq)
    rev = al.align(ref_seq, qry_rc)
    if rev.score > fwd.score:
        blocks, d = _blocks_and_map(rev[0], qry_rc)
        m = Mapping(orientation="reverse", ref_to_query=d, blocks=blocks,
                    ref_seq=ref_seq, query_seq=qry_rc)
    else:
        blocks, d = _blocks_and_map(fwd[0], query_seq)
        m = Mapping(orientation="forward", ref_to_query=d, blocks=blocks,
                    ref_seq=ref_seq, query_seq=query_seq)
    m._sorted_refs = sorted(d)
    return m


def to_native(pos_rc: int, query_len: int) -> int:
    """RC 空间坐标 → 宿主（FASTA 原始方向）坐标。"""
    return query_len + 1 - pos_rc
