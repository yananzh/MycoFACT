"""§6.5 迁移规则单元测试：partial / join 逐段 / codon_start 公式 / 链组合 /
qualifier 三分表 / exon 内外规则拆分（P0 回归）。"""
import io

from Bio import SeqIO

from fungal_annot.core.align_mapper import build_mapping, revcomp
from fungal_annot.core.feature_parser import extract_features
from fungal_annot.core.feature_transfer import codon_start_for, transfer_features
from fungal_annot.core.presets import get


def _setup(ref_gb_text, query):
    rec = SeqIO.read(io.StringIO(ref_gb_text), "genbank")
    preset = get("tef1")
    feats = extract_features(rec, preset)
    m = build_mapping(str(rec.seq).upper(), query)
    return feats, m, preset


def test_codon_start_formula():
    """§2.1：codon_start = ((3 − m mod 3) mod 3) + 1（缺 1→3，缺 2→2，缺整密码子→1）。"""
    assert [codon_start_for(m) for m in range(7)] == [1, 3, 2, 1, 3, 2, 1]
    assert codon_start_for(100) == 3
    # 参考 CDS 自身 5' partial 时：codon_start 与缺失数是模 3 互补关系，
    # 不变式 = 完全一致的查询必须复现参考自身的 codon_start
    assert codon_start_for(0, ref_codon_start=1) == 1
    assert codon_start_for(0, ref_codon_start=2) == 2
    assert codon_start_for(0, ref_codon_start=3) == 3
    assert codon_start_for(1, ref_codon_start=2) == 1
    assert codon_start_for(2, ref_codon_start=2) == 3


def test_qualifier_triage(ref_record_seq, ref_gb_text):
    """§6.5 三分表：product/gene 继承；protein_id/locus_tag/db_xref/translation 丢弃；
    codon_start 重算不继承；note 的 complete 断言改写。"""
    seq, _ = ref_record_seq
    q = seq[300:1600]
    feats, m, preset = _setup(ref_gb_text, q)
    out = transfer_features(feats, m, len(q), preset, query_seq=q)
    cds = next(f for f in out.features if f.ftype == "CDS")
    assert cds.qualifiers["gene"] == ["tef1"]
    assert cds.qualifiers["product"] == ["translation elongation factor 1-alpha"]
    assert "protein_id" not in cds.qualifiers
    assert "locus_tag" not in cds.qualifiers
    assert "db_xref" not in cds.qualifiers
    assert "translation" not in cds.qualifiers
    assert cds.qualifiers["transl_table"] == ["1"]
    assert cds.qualifiers["codon_start"] == ["3"]
    assert cds.qualifiers["note"] == ["partial cds"]


def test_partial_and_coordinates(ref_record_seq, ref_gb_text):
    seq, _ = ref_record_seq
    q = seq[300:1600]
    feats, m, preset = _setup(ref_gb_text, q)
    out = transfer_features(feats, m, len(q), preset, query_seq=q)
    cds = next(f for f in out.features if f.ftype == "CDS")
    gene = next(f for f in out.features if f.ftype == "gene")
    # exon1 5' 侧在覆盖区外 → 裁剪 + partial；exon2 完整映射
    assert [(p.start, p.end) for p in cds.parts] == [(1, 300), (401, 849)]
    assert cds.parts[0].partial_low is True
    assert cds.parts[-1].partial_high is False
    # gene 单区间跨内含子：201..1149 裁剪后 1..849
    assert (gene.parts[0].start, gene.parts[0].end) == (1, 849)
    codes = {i.code for i in out.issues}
    assert "exon_outside_aligned" in codes      # 区段外 = warning
    assert "exon_map_fail" not in codes


def test_reverse_strand_combination(ref_record_seq, ref_gb_text):
    """反向互补查询 × 参考正链 CDS → 宿主负链；'<'/'> ' 随坐标端对调（§6.5）。"""
    seq, _ = ref_record_seq
    q = revcomp(seq[300:1600])
    feats, m, preset = _setup(ref_gb_text, q)
    assert m.orientation == "reverse"
    out = transfer_features(feats, m, len(q), preset, query_seq=q)
    cds = next(f for f in out.features if f.ftype == "CDS")
    assert cds.strand == -1
    assert [(p.start, p.end) for p in cds.parts] == [(452, 900), (1001, 1300)]
    # 5' 端缺失（m=100）→ 负链 feature 的 partial 在高坐标端
    assert cds.parts[-1].partial_high is True
    assert cds.parts[0].partial_low is False
    assert cds.qualifiers["codon_start"] == ["3"]


def test_exon_map_fail_is_error(ref_record_seq, ref_gb_text):
    """区间内的 exon 整段落入查询缺失缺口 → 丢弃 + error（§6.5 拆分后的真失败分支）。"""
    seq, _ = ref_record_seq
    q = seq[300:700] + seq[1149:1600]           # 查询缺失 exon2 对应区域
    feats, m, preset = _setup(ref_gb_text, q)
    out = transfer_features(feats, m, len(q), preset, query_seq=q)
    codes = {i.code for i in out.issues}
    assert "exon_map_fail" in codes
    assert any(i.level == "error" for i in out.issues if i.code == "exon_map_fail")
    cds = next(f for f in out.features if f.ftype == "CDS")
    assert len(cds.parts) == 1                  # exon2 已丢弃，exon1 保留


def test_complete_cds_partial_exemption(ref_record_seq, ref_gb_text):
    """§2.1 豁免：完整起止密码子且翻译通过时，触及端点不自动标 partial。"""
    seq, _ = ref_record_seq
    q = seq[200:1149]                            # 完整 CDS 区间（含内含子）
    feats, m, preset = _setup(ref_gb_text, q)
    out = transfer_features(feats, m, len(q), preset, query_seq=q)
    cds = next(f for f in out.features if f.ftype == "CDS")
    assert [(p.start, p.end) for p in cds.parts] == [(1, 400), (501, 949)]
    assert cds.parts[0].partial_low is False
    assert cds.parts[-1].partial_high is False
    assert "codon_start" not in cds.qualifiers   # m=0 → 省略（默认 1）


def test_auto_partial_off(ref_record_seq, ref_gb_text):
    seq, _ = ref_record_seq
    q = seq[300:1600]
    feats, m, preset = _setup(ref_gb_text, q)
    out = transfer_features(feats, m, len(q), preset, auto_partial=False, query_seq=q)
    gene = next(f for f in out.features if f.ftype == "gene")
    assert gene.parts[0].partial_low is True     # 结构性 partial（裁剪）仍在
    # CDS 5' 结构性 partial 来自裁剪，保持；无额外 auto 标记
    cds = next(f for f in out.features if f.ftype == "CDS")
    assert cds.parts[0].partial_low is True
