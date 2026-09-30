"""离线端到端（M1 验收路径）：本地参考 GB → 迁移 → .tbl，含 P0 断言。"""
import io
import os

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord

from fungal_annot.core.align_mapper import revcomp
from fungal_annot.core.models import Feature, FeaturePart, SeqInput
from fungal_annot.core.tbl_writer import write_tbl
from fungal_annot.services.pipeline import (PipelineConfig, SeqResult,
                                            annotate_sequence, write_outputs)
from .conftest import query_plus_insertion

CFG = PipelineConfig(online=False)


def _mk(seq, seq_id="user_seq", gene_type="tef1"):
    return SeqInput(seq_id=seq_id, seq=seq, gene_type=gene_type,
                    source_qualifiers={"organism": "Fusarium testicum",
                                       "strain": "USER001", "country": "China",
                                       "collection_date": "2021-Mar",
                                       "lat_lon": "30.5 N 114.3 E"})


def test_end_to_end_plus(ref_record_seq, ref_gb_text, tmp_path):
    seq, _ = ref_record_seq
    q = query_plus_insertion(seq)
    res = annotate_sequence(_mk(q), CFG, reference_gb_text=ref_gb_text)
    # 区段超出扩增区属常态且已按 partial 处理 → info，不再把序列染黄
    assert res.status == "green", [f"{i.level}: {i.message}" for i in res.issues]
    assert any(i.code == "exon_outside_aligned" and i.level == "info"
               for i in res.issues)
    tbl = res.tbl_text

    assert tbl.startswith(">Feature user_seq")
    assert "<1\t300\tCDS" in tbl                  # exon1 裁剪 + partial
    assert "401\t852" in tbl and "401\t852\tCDS" not in tbl  # exon2 行不带 key（NCBI 规范）
    assert tbl.count("\tCDS") == 1                # join CDS 只有一个 feature key
    assert "\t\t\tcodon_start\t3" in tbl          # m=100 → codon_start=3（五列格式）
    assert "\t\t\tgene\ttef1" in tbl
    assert "\t\t\tproduct\ttranslation elongation factor 1-alpha" in tbl

    # §6.5 三分表：参考标识类不迁移；BankIt 门户模式不含 source
    for banned in ("NP_999", "REF_0001", "GeneID", "translation\t",
                   "REF001", "referenceus", "taxon:999999",
                   "mol_type", "organism", "strain"):
        assert banned not in tbl, banned

    # 溯源（§6.7）
    row = res.report_row()
    assert row["source"] == "local-gb"
    assert row["orientation"] == "forward"
    assert row["reference"] == "REF00001.1"
    assert res.provenance.nt_identity > 0.99

    write_outputs([res], str(tmp_path), [_mk(q)])
    assert (tmp_path / "user_seq.tbl").exists()
    assert (tmp_path / "user_seq.fsa").exists()
    assert (tmp_path / "user_seq.fsa").read_text(encoding="utf-8").startswith(">user_seq")
    assert (tmp_path / "validation_report.csv").exists()
    # 多记录汇总：单序列时内容与 per-seq .tbl 一致
    assert (tmp_path / "all_features.tbl").read_text(encoding="utf-8") == \
        (tmp_path / "user_seq.tbl").read_text(encoding="utf-8")
    # 默认 = BankIt 门户模式：.tbl 只含 gene/CDS 等 feature，不含 source
    tbl_text = (tmp_path / "user_seq.tbl").read_text(encoding="utf-8")
    assert "\tsource" not in tbl_text and "organism" not in tbl_text
    assert "CDS" in tbl_text


def test_detect_from_titles_word_boundary():
    from fungal_annot.core.presets import detect_from_titles
    assert detect_from_titles(
        ["Fusarium oxysporum translation elongation factor 1-alpha (EEF1A1) gene, partial cds"]
    ).name == "tef1"
    assert detect_from_titles(
        ["Alternaria alternata actin (ACT) gene, complete cds"]).name == "act"
    assert detect_from_titles(
        ["Aspergillus nidulans chitin synthase B (chsB) gene, partial cds"]).name == "chs"
    # 词边界："chs" 单独成词才命中，"chs1"/"chsB" 需显式别名
    assert detect_from_titles(
        ["Candida albicans chitin synthase 3 (CHS3) mRNA, complete cds"]).name == "chs"
    # 词边界："extract"/"reaction" 不得命中 "act"
    assert detect_from_titles(
        ["Some random scaffold extract of a reaction protein"]) is None


def test_autodetect_from_offline_reference(partial_ref_gb):
    """gene_type 留空：从离线参考的 product/gene 注释自动判定为 tef1，
    且后续迁移（codon_start=2 不变式）不受影响。"""
    from Bio import SeqIO
    rec = SeqIO.read(io.StringIO(partial_ref_gb), "genbank")
    q = str(rec.seq)[300:1150]
    res = annotate_sequence(_mk(q, gene_type=""), CFG,
                            reference_gb_text=partial_ref_gb)
    assert res.seq_id and res.status in ("green", "yellow")
    codes = {i.code: i for i in res.issues}
    assert "gene_type_auto" in codes
    assert "auto-detected as 'tef1'" in codes["gene_type_auto"].message
    cds = next(f for f in res.features if f.ftype == "CDS")
    assert cds.qualifiers.get("codon_start") == ["2"]


def test_generic_fallback_when_gene_unrecognized(two_cds_gb):
    """不在预设列表的基因：Generic 兜底——宽白名单照常迁移，并给出要求人工
    确认的 warning；.tbl 不再输出 transl_table。"""
    rec = SeqIO.read(io.StringIO(two_cds_gb), "genbank")
    q = str(rec.seq)[1150:1850]                    # 覆盖 CDS-B
    res = annotate_sequence(_mk(q, gene_type=""), CFG,
                            reference_gb_text=two_cds_gb)
    codes = {i.code for i in res.issues}
    assert "gene_type_generic" in codes
    cds = [f for f in res.features if f.ftype == "CDS"]
    assert len(cds) == 1
    assert cds[0].qualifiers.get("transl_table") is None   # 输出不含 transl_table
    assert res.status in ("green", "yellow")


def test_generic_tag_retries_detection_after_preset_added(partial_ref_gb):
    """回归：曾落到 Generic 兜底的序列（gene_type 已固化为 "Generic"），在
    presets.json 补充新基因后重新注释必须重试自动判定——Generic 是兜底标签
    而非用户选择，否则补预设只对新导入的序列生效。"""
    rec = SeqIO.read(io.StringIO(partial_ref_gb), "genbank")
    q = str(rec.seq)[300:1150]
    res = annotate_sequence(_mk(q, gene_type="Generic"), CFG,
                            reference_gb_text=partial_ref_gb)
    codes = {i.code: i for i in res.issues}
    assert "gene_type_generic" not in codes
    assert "gene_type_auto" in codes
    assert "auto-detected as 'tef1'" in codes["gene_type_auto"].message


def test_explicit_unknown_gene_type_still_errors(two_cds_gb):
    """显式写了不存在的预设名 → 仍报错（自动判定只对留空生效，不覆盖用户意图）。"""
    rec = SeqIO.read(io.StringIO(two_cds_gb), "genbank")
    q = str(rec.seq)[1150:1850]
    res = annotate_sequence(_mk(q, gene_type="nonexist"), CFG,
                            reference_gb_text=two_cds_gb)
    assert res.status == "red"
    assert any(i.code == "preset_unknown" for i in res.issues)


def test_partial_reference_codon_start_invariant(partial_ref_gb):
    """不变式（回归 A1）：查询与参考 CDS 完全一致 → 输出 codon_start 必须等于参考值；
    同时 5' 端必须带 partial 标记，且 product/note 的 "complete cds" 断言被改写。

    历史缺陷：折叠参考相位时把 codon_start-1 当作缺失碱基数（模 3 互补关系搞反），
    导致 5' partial 参考模板的相位整体错位一格。"""
    rec = SeqIO.read(io.StringIO(partial_ref_gb), "genbank")
    q = str(rec.seq)[300:1150]                    # 850 bp，与参考 CDS 完全一致
    res = annotate_sequence(_mk(q), CFG, reference_gb_text=partial_ref_gb)
    assert res.status in ("green", "yellow"), [f"{i.level}: {i.message}" for i in res.issues]
    cds = next(f for f in res.features if f.ftype == "CDS")
    assert cds.qualifiers.get("codon_start") == ["2"]      # 不变式
    assert cds.parts[0].partial_low is True                # 5' 截断语义
    assert cds.parts[-1].partial_high is False             # 3' 端完整（止于 TAA）
    assert res.tbl_text.count("\t\tcomplete cds") == 0      # 完整性断言已改写
    codes = {i.code for i in res.issues}
    assert "internal_stop" not in codes and "cds_phase" not in codes


def test_dropped_exon_sets_partial_marker(ref_record_seq, ref_gb_text):
    """回归 A2：查询起点落在内含子内、相邻 exon 完全在覆盖区外时，保留段必须在对应
    坐标端带 partial 标记，否则会导出"既无 <> 又带 codon_start"的自相矛盾记录。"""
    seq, _ = ref_record_seq
    q = seq[670:1600]                              # 起点在内含子 601..700 内
    res = annotate_sequence(_mk(q), CFG, reference_gb_text=ref_gb_text)
    cds = next(f for f in res.features if f.ftype == "CDS")
    assert len(cds.parts) == 1                     # 仅 exon2 保留
    assert cds.parts[0].partial_low is True        # 5' 截断语义已传递
    assert cds.qualifiers.get("codon_start") == ["3"]   # 缺 exon1 的 400 bp（mod 3 = 1）
    assert cds.qualifiers.get("note") == ["partial cds"]


def test_cds_pairing_by_reference_coordinates(two_cds_gb):
    """回归 B1：参考含两个 CDS 时，配对必须按参考坐标——蛋白回检不能取到被跳过的
    那个 CDS（历史上按下标配对，会给出错误的 identity 警告与密码表）。"""
    rec = SeqIO.read(io.StringIO(two_cds_gb), "genbank")
    q = str(rec.seq)[1150:1850]                    # 只覆盖 CDS-B（1201..1800）
    res = annotate_sequence(_mk(q), CFG, reference_gb_text=two_cds_gb)
    cds = [f for f in res.features if f.ftype == "CDS"]
    assert len(cds) == 1                           # CDS-A 在覆盖区外，已跳过
    assert cds[0].qualifiers.get("transl_table") is None   # 输出不含 transl_table
    codes = {i.code for i in res.issues}
    assert "protein_identity" not in codes         # 配对错误时该警告会误报
    assert "transl_table_conflict" not in codes


def test_complete_cds_tbl_codon_start_no_transl_table(ref_record_seq, ref_gb_text):
    """用户验收：.tbl 的 CDS 恒显式写 codon_start（含 =1），且不输出 transl_table。"""
    seq, _ = ref_record_seq
    q = seq[200:1149]                              # 完整 CDS 区间（m=0 → codon_start=1）
    res = annotate_sequence(_mk(q), CFG, reference_gb_text=ref_gb_text)
    tbl = res.tbl_text
    assert "\t\t\tcodon_start\t1" in tbl
    assert "\t\t\ttransl_table" not in tbl


def test_end_to_end_reverse(ref_record_seq, ref_gb_text):
    seq, _ = ref_record_seq
    q = revcomp(seq[300:1600])
    res = annotate_sequence(_mk(q), CFG, reference_gb_text=ref_gb_text)
    # 裁剪区段 → info（常态，不染黄），状态为 green
    assert res.status == "green", [f"{i.level}: {i.message}" for i in res.issues]
    assert res.provenance.orientation == "reverse"
    # 互补链：区段降序；'<'（5' partial）恒在第 1 列 → 高坐标端（负链 5' 端）
    assert "<1300\t1001\tCDS" in res.tbl_text
    assert "900\t452" in res.tbl_text and "900\t452\tCDS" not in res.tbl_text
    assert "\t\t\tcodon_start\t3" in res.tbl_text


def test_end_to_end_complete_cds_green(ref_record_seq, ref_gb_text):
    """查询恰为完整 CDS 区间：翻译/相位全通过 → 绿灯，CDS 无 partial 标记。"""
    seq, _ = ref_record_seq
    q = seq[200:1149]
    res = annotate_sequence(_mk(q), CFG, reference_gb_text=ref_gb_text)
    assert res.status == "green", [f"{i.level}:{i.message}" for i in res.issues]
    assert "1\t400\tCDS" in res.tbl_text
    assert "501\t949" in res.tbl_text and "501\t949\tCDS" not in res.tbl_text
    assert "<1\t400" not in res.tbl_text and "949>\t" not in res.tbl_text


# ---- 输入兜底修复回归（2026-09-29：非法字符 / 文件名清洗）----

def test_seqinput_rejects_non_nucleotide():
    """SeqInput 导入期校验：gap/终止符等非法字符即拒绝（快速失败，
    避免流入翻译/写盘等深处才炸）。"""
    import pytest

    with pytest.raises(ValueError):
        SeqInput(seq_id="s", seq="ACGT-ACGT")     # 比对软件导出的 gap
    with pytest.raises(ValueError):
        SeqInput(seq_id="s", seq="ACGT*")         # 翻译终止符
    s = SeqInput(seq_id="s", seq=" acgt\r\nn ")   # 空白剥除后合法
    assert s.seq == "ACGTN"


def test_gap_in_query_becomes_structured_error(ref_record_seq, ref_gb_text):
    """回归：查询含 '-'（比对导出 gap）→ 结构化 error，不抛 TranslationError
    使 CLI 整批崩溃（TranslationError 不是 ValueError 子类，此前无人兜底）。"""
    seq, _ = ref_record_seq
    s = _mk(seq[300:1600])
    s.seq = s.seq[:500] + "-" + s.seq[501:]   # 绕过导入校验（落在 CDS 读码框内）
    res = annotate_sequence(s, CFG, reference_gb_text=ref_gb_text)
    assert res.status == "red"
    assert any(i.code == "invalid_residue" for i in res.issues)


def test_write_outputs_sanitises_windows_unsafe_seq_id(tmp_path):
    """回归：Seq ID 含 '|' / ':'（GenBank 合法、Windows 非法文件名字符）时
    导出不崩溃，且清洗后同名的两条不得互相覆盖。"""
    def _mk_res(sid):
        feats = [Feature(ftype="gene", parts=[FeaturePart(1, 100)])]
        return SeqResult(seq_id=sid, features=feats), write_tbl(feats, sid)

    res1, t1 = _mk_res("gi|123|ref|X.1")
    res2, t2 = _mk_res("chr1:100-200")
    res3, t3 = _mk_res("a|b")
    res4, t4 = _mk_res("a:b")
    written = write_outputs([res1, res2, res3, res4], str(tmp_path))
    names = {os.path.basename(p) for p in written}
    # '|' 与 ':' 都替换为 '_'；"a|b" 与 "a:b" 清洗后冲突 → 后者追加序号（tbl/fsa 同步）
    assert names == {"gi_123_ref_X.1.tbl", "gi_123_ref_X.1.fsa",
                     "chr1_100-200.tbl", "chr1_100-200.fsa",
                     "a_b.tbl", "a_b.fsa", "a_b_2.tbl", "a_b_2.fsa",
                     "all_features.tbl", "validation_report.csv"}
    assert (tmp_path / "a_b.tbl").read_text(encoding="utf-8") == t3
    assert (tmp_path / "a_b_2.tbl").read_text(encoding="utf-8") == t4
    # 汇总文件按原始 Seq ID 保留各 >Feature 记录头（>Feature 块顺序拼接）
    combined = (tmp_path / "all_features.tbl").read_text(encoding="utf-8")
    assert combined == t1 + t2 + t3 + t4


def test_write_outputs_combined_summary_skips_failed(tmp_path):
    """汇总 all_features.tbl：多记录块按序拼接；**零产出序列（失败或没有可迁移
    feature）不写 .tbl/.fsa**，只在验证报告里留证并计入 skipped（可选输出参数）。"""
    def _mk_res(sid):
        feats = [Feature(ftype="gene", parts=[FeaturePart(1, 100)])]
        return SeqResult(seq_id=sid, features=feats)

    res1, res2 = _mk_res("s1"), _mk_res("s2")
    failed = SeqResult(seq_id="s3")                 # 管线失败：无 feature
    skipped = []
    written = write_outputs([res1, failed, res2], str(tmp_path), with_fsa=False,
                            skipped=skipped)
    combined = tmp_path / "all_features.tbl"
    assert combined.read_text(encoding="utf-8") == \
        write_tbl(res1.features, "s1") + write_tbl(res2.features, "s2")
    assert {os.path.basename(p) for p in written} == \
        {"s1.tbl", "s2.tbl", "all_features.tbl", "validation_report.csv"}
    assert skipped == ["s3"]
    assert not (tmp_path / "s3.tbl").exists()       # 0 字节 .tbl 不得出现在产物里
    # 失败也要留证据：报告仍逐条记录
    assert "s3" in (tmp_path / "validation_report.csv").read_text(encoding="utf-8")

    all_failed = write_outputs([SeqResult(seq_id="s4")], str(tmp_path / "out2"),
                               with_fsa=False)
    assert not (tmp_path / "out2" / "all_features.tbl").exists()
    assert {os.path.basename(p) for p in all_failed} == {"validation_report.csv"}


def test_export_text_is_derived_from_features(tmp_path, ref_record_seq, ref_gb_text):
    """回归（P0）：结果上缓存的 tbl_text 落后于 features 时，导出必须按 features
    现算——历史缺陷：审核页改完坐标立即导出，写出的是改前的表。"""
    seq, _ = ref_record_seq
    q = seq[300:1600]
    res = annotate_sequence(_mk(q, seq_id="d1"), CFG, reference_gb_text=ref_gb_text)
    stale = res.tbl_text
    cds = next(f for f in res.features if f.ftype == "CDS")
    cds.qualifiers["note"] = ["changed after render"]   # 模拟编辑后 features 已变
    write_outputs([res], str(tmp_path), with_fsa=False)
    text = (tmp_path / "d1.tbl").read_text(encoding="utf-8")
    assert "changed after render" in text
    assert text == write_tbl(res.features, "d1")
    assert text != stale


def test_no_transferable_feature_is_error_and_writes_nothing(tmp_path):
    """参考记录没有任何匹配白名单的 feature（例如只标注了 ITS 的记录）：
    必须报 error 而不是"绿灯 + 空表"，也不写出只有记录头的 .tbl（BankIt 拒收）。"""
    rec = SeqRecord(Seq("ACGT" * 300), id="EMPTY0001.1", name="EMPTY0001",
                    description="synthetic record with no transferable feature")
    rec.annotations["molecule_type"] = "DNA"
    src = SeqFeature(SimpleLocation(0, 1200, strand=1), type="source")
    src.qualifiers = {"organism": ["Testus fungus"]}
    misc = SeqFeature(SimpleLocation(100, 400, strand=1), type="misc_feature")
    misc.qualifiers = {"note": ["internal transcribed spacer 1"]}
    rec.features = [src, misc]
    buf = io.StringIO()
    SeqIO.write(rec, buf, "genbank")

    res = annotate_sequence(_mk(("ACGT" * 300)[50:600], seq_id="n1"), CFG,
                            reference_gb_text=buf.getvalue())
    assert "no_reference_features" in {i.code for i in res.issues}
    assert res.status == "red"
    assert res.tbl_text == ""            # 零产出不留"只有记录头"的文本

    skipped = []
    written = write_outputs([res], str(tmp_path), skipped=skipped)
    assert skipped == ["n1"]
    assert not (tmp_path / "n1.tbl").exists()
    assert not (tmp_path / "n1.fsa").exists()
    assert not (tmp_path / "all_features.tbl").exists()
    assert {os.path.basename(p) for p in written} == {"validation_report.csv"}
