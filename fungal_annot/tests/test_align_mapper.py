"""§6.4 坐标映射单元测试：完全一致 / indel / 末端截断 / 反向互补 / 长参考窗口。"""
import random

import pytest

from fungal_annot.core.align_mapper import AlignmentError, build_mapping, revcomp, to_native


def test_forward_internal_fragment(ref_record_seq):
    seq, _ = ref_record_seq
    q = seq[300:1600]
    m = build_mapping(seq, q)
    assert m.orientation == "forward"
    assert m.aligned_ref_interval == (301, 1600)
    assert m.identity() == pytest.approx(1.0)
    assert m.ref_to_query[301] == 1
    assert m.ref_to_query[1600] == 1300


def test_reverse_orientation(ref_record_seq):
    seq, _ = ref_record_seq
    q = revcomp(seq[300:1600])
    m = build_mapping(seq, q)
    assert m.orientation == "reverse"
    assert m.ref_to_query[301] == 1            # RC 空间坐标
    assert to_native(m.ref_to_query[301], len(q)) == 1300
    assert to_native(m.ref_to_query[1600], len(q)) == 1


def test_insertion_mapping(ref_record_seq):
    seq, _ = ref_record_seq
    q = seq[300:1600]
    q = q[:402] + "GCA" + q[402:]
    m = build_mapping(seq, q)
    assert m.aligned_ref_interval == (301, 1600)
    d = m.ref_to_query
    assert len(d) == 1300                            # 参考侧全部有映射
    missing_q = sorted(set(range(1, 1304)) - set(d.values()))
    assert len(missing_q) == 3                       # 恰好 3 个查询碱基（插入）无参考对应
    assert m.identity() > 0.99


def test_deletion_mapping(ref_record_seq):
    seq, _ = ref_record_seq
    q = seq[300:1600]
    q = q[:500] + q[503:]                            # 删除 3bp（对应 ref 801..803）
    m = build_mapping(seq, q)
    d = m.ref_to_query
    assert m.aligned_ref_interval == (301, 1600)
    missing_ref = [p for p in range(301, 1601) if p not in d]
    assert len(missing_ref) == 3                     # 恰好 3 个参考碱基落入 gap，无映射
    assert sorted(d.values()) == list(range(1, len(q) + 1))   # 查询侧无空洞
    assert m.identity() > 0.99


def test_long_reference_window_scale(ref_record_seq):
    """查询仅为长参考（~22.6kb）的内部片段：§6.4 禁止全序列比对的前提是先窗口截取，
    此处验证对长参考本身做一次 glocal 比对的坐标正确性。"""
    seq, _ = ref_record_seq
    rng = random.Random(7)
    big = ("".join(rng.choice("ACGT") for _ in range(10000))
           + seq
           + "".join(rng.choice("ACGT") for _ in range(10000)))
    q = seq[300:1600]
    m = build_mapping(big, q)
    assert m.aligned_ref_interval == (10301, 11600)
    assert m.ref_to_query[10301] == 1
    assert m.identity() == pytest.approx(1.0)


def test_ref_shorter_than_query_rejected(ref_record_seq):
    seq, _ = ref_record_seq
    with pytest.raises(AlignmentError):
        build_mapping(seq[300:1600], seq[200:1700])
