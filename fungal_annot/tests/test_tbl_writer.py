"""§6.7 五列表格式测试：join 多段 / 互补链降序 / partial 标记 / .fsa 配对 / 报告列。"""
from fungal_annot.core.models import Feature, FeaturePart
from fungal_annot.core.tbl_writer import (REPORT_COLUMNS, feature_lines, write_combined_tbl,
                                          write_fsa, write_report_csv, write_tbl)


def _plus_cds():
    f = Feature(ftype="CDS", strand=1,
                parts=[FeaturePart(1, 300, partial_low=True, ref_start=301, ref_end=600),
                       FeaturePart(401, 849, ref_start=701, ref_end=1149)],
                qualifiers={"gene": ["tef1"], "codon_start": ["3"]})
    return f


def test_plus_join_and_partial():
    tbl = write_tbl([_plus_cds()], "seq1")
    lines = tbl.splitlines()
    assert lines[0] == ">Feature seq1"
    assert "<1\t300\tCDS" in lines
    assert "401\t849\tCDS" in lines
    assert "\t\t\tgene\ttef1" in lines           # 五列：1-3 列空，qualifier 第 4 列
    assert "\t\t\tcodon_start\t3" in lines
    # qualifier 只出现在最后一个区段行之后
    assert lines.index("\t\t\tgene\ttef1") > lines.index("401\t849\tCDS")


def test_minus_descending_and_markers():
    f = Feature(ftype="CDS", strand=-1,
                parts=[FeaturePart(452, 900),
                       FeaturePart(1001, 1300, partial_high=True)],
                qualifiers={})
    lines = feature_lines(f)
    assert lines[0] == ">1300\t1001\tCDS"   # 互补链降序；5' partial 在高坐标端
    assert lines[1] == "900\t452\tCDS"


def test_source_first_and_gene_before_cds():
    src = Feature(ftype="source", strand=1, parts=[FeaturePart(1, 1300)],
                  qualifiers={"organism": ["X"]})
    gene = Feature(ftype="gene", strand=1, parts=[FeaturePart(1, 849)])
    tbl = write_tbl([_plus_cds(), gene, src], "seq1")
    lines = tbl.splitlines()
    assert lines[1].endswith("\tsource")
    assert lines.index("1\t849\tgene") < lines.index("<1\t300\tCDS")


def test_fsa_pairing():
    seq = "ACGT" * 25     # 100bp
    fsa = write_fsa("seq1", seq)
    lines = fsa.splitlines()
    assert lines[0] == ">seq1"
    assert len(lines[1]) == 70 and len(lines[2]) == 30
    assert "".join(lines[1:]) == seq


def test_combined_tbl_multi_record():
    """汇总多记录格式：各 >Feature 块顺序拼接；缺尾换行的块自动补齐，
    不与下一记录头粘连。"""
    t1 = write_tbl([_plus_cds()], "seq1")
    t2 = write_tbl([], "seq2")
    assert write_combined_tbl([t1, t2]) == t1 + t2
    assert write_combined_tbl([">Feature a\n1\t2\tgene", ">Feature b\n"]) == \
        ">Feature a\n1\t2\tgene\n>Feature b\n"
    assert write_combined_tbl([]) == ""


def test_report_has_provenance_columns():
    csv_text = write_report_csv([{"seq_id": "a", "status": "green",
                                  "reference": "ABCD01000000.1", "region": "100..2100",
                                  "orientation": "reverse", "pident": 99.2,
                                  "qcovs": 100.0, "nt_identity": "0.9988"}])
    header = csv_text.splitlines()[0]
    for col in REPORT_COLUMNS:
        assert col in header
