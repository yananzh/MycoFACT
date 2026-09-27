"""离线端到端（M1 验收路径）：本地参考 GB → 迁移 → .tbl，含 P0 断言。"""
from fungal_annot.core.align_mapper import revcomp
from fungal_annot.core.models import SeqInput
from fungal_annot.services.pipeline import (PipelineConfig, annotate_sequence,
                                            write_outputs)
from .conftest import query_plus_insertion

CFG = PipelineConfig(online=False)


def _mk(seq, seq_id="user_seq"):
    return SeqInput(seq_id=seq_id, seq=seq, gene_type="tef1",
                    source_qualifiers={"organism": "Fusarium testicum",
                                       "strain": "USER001", "country": "China",
                                       "collection_date": "2021-Mar",
                                       "lat_lon": "30.5 N 114.3 E"})


def test_end_to_end_plus(ref_record_seq, ref_gb_text, tmp_path):
    seq, _ = ref_record_seq
    q = query_plus_insertion(seq)
    res = annotate_sequence(_mk(q), CFG, reference_gb_text=ref_gb_text)
    assert res.status == "yellow", [i.message for i in res.issues]
    tbl = res.tbl_text

    assert tbl.startswith(">Feature user_seq")
    assert "<1\t300\tCDS" in tbl                  # exon1 裁剪 + partial
    assert "401\t852\tCDS" in tbl                 # exon2（含 3bp 插入偏移）
    assert "\t\tcodon_start\t3" in tbl            # m=100 → codon_start=3
    assert "\t\tgene\ttef1" in tbl
    assert "\t\tproduct\ttranslation elongation factor 1-alpha" in tbl

    # §6.5 三分表：参考标识类不迁移
    for banned in ("NP_999", "REF_0001", "GeneID", "translation\t",
                   "REF001", "referenceus", "taxon:999999"):
        assert banned not in tbl, banned
    # source 只含用户输入
    assert "\t\torganism\tFusarium testicum" in tbl
    assert "\t\tstrain\tUSER001" in tbl

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


def test_end_to_end_reverse(ref_record_seq, ref_gb_text):
    seq, _ = ref_record_seq
    q = revcomp(seq[300:1600])
    res = annotate_sequence(_mk(q), CFG, reference_gb_text=ref_gb_text)
    assert res.status == "yellow"
    assert res.provenance.orientation == "reverse"
    # 互补链：区段降序 + partial 标记在高坐标端
    assert ">1300\t1001\tCDS" in res.tbl_text
    assert "900\t452\tCDS" in res.tbl_text
    assert "\t\tcodon_start\t3" in res.tbl_text


def test_end_to_end_complete_cds_green(ref_record_seq, ref_gb_text):
    """查询恰为完整 CDS 区间：翻译/相位全通过 → 绿灯，CDS 无 partial 标记。"""
    seq, _ = ref_record_seq
    q = seq[200:1149]
    res = annotate_sequence(_mk(q), CFG, reference_gb_text=ref_gb_text)
    assert res.status == "green", [f"{i.level}:{i.message}" for i in res.issues]
    assert "1\t400\tCDS" in res.tbl_text
    assert "501\t949\tCDS" in res.tbl_text
    assert "<1\t400" not in res.tbl_text and "949>\t" not in res.tbl_text
