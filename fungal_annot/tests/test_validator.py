"""§6.6 验证器测试：翻译判级（P0-4）/ identity 门禁 / 修饰符格式 / SeqID / N 区段。"""
from fungal_annot.core.models import SeqInput
from fungal_annot.services.pipeline import PipelineConfig, annotate_sequence

CFG = PipelineConfig(online=False)


def _run(seq, ref_gb_text, seq_id="test_seq", **cfg_kw):
    s = SeqInput(seq_id=seq_id, seq=seq, gene_type="tef1",
                 source_qualifiers={"organism": "Fusarium testicum", "strain": "USER001",
                                    "country": "China", "collection_date": "2021-Mar",
                                    "lat_lon": "30.5 N 114.3 E"})
    cfg = PipelineConfig(online=False, **cfg_kw)
    return annotate_sequence(s, cfg, reference_gb_text=ref_gb_text)


def _codes(res, level=None):
    return {i.code for i in res.issues if level is None or i.level == level}


def test_internal_stop_is_error_when_table_certain(ref_record_seq, ref_gb_text):
    """表确定（参考 qualifier=预设=1）时，框内插入终止子 → error（红灯）。"""
    seq, _ = ref_record_seq
    q = seq[300:1600]
    q = q[:402] + "TAA" + q[402:]     # 与 GCA 插入同位（读码框内）
    res = _run(q, ref_gb_text)
    assert "internal_stop" in _codes(res, "error")
    assert res.status == "red"


def test_low_identity_gate(ref_record_seq, ref_gb_text):
    seq, _ = ref_record_seq
    q = list(seq[300:1600])
    # 仅内部突变：局部比对会裁掉持续错配的末端（该行为本身正确），突变放内部
    for i in range(20, len(q) - 20, 13):   # ~7.5% 突变 → exon identity < 97%
        q[i] = "A" if q[i] != "A" else "C"
    res = _run("".join(q), ref_gb_text)
    assert "low_identity" in _codes(res, "error")
    assert res.status == "red"


def test_seqid_invalid(ref_record_seq, ref_gb_text):
    seq, _ = ref_record_seq
    q = seq[300:1600]
    res = _run(q, ref_gb_text, seq_id="my seq")
    assert "seqid_invalid" in _codes(res, "error")


def test_n_boundary_warning(ref_record_seq, ref_gb_text):
    seq, _ = ref_record_seq
    q = list(seq[300:1600])
    # N 区段横跨 exon2 起点（query pos 401），位于序列内部
    for i in range(398, 403):
        q[i] = "N"
    res = _run("".join(q), ref_gb_text)
    assert "n_boundary" in _codes(res, "warning")


def test_transl_table_conflict_warning(ref_record_seq, ref_gb_text):
    """§2.3：用户选择与参考 qualifier 不一致 → 不静默取其一，warning。"""
    seq, _ = ref_record_seq
    q = seq[300:1600]
    res = _run(q, ref_gb_text, user_transl_table=4)
    assert "transl_table_conflict" in _codes(res, "warning")


def test_preset_unknown_is_red():
    s = SeqInput(seq_id="x", seq="ACGT", gene_type="nonexist")
    res = annotate_sequence(s, CFG, reference_gb_text="dummy")
    assert res.status == "red"
    assert any(i.code == "preset_unknown" for i in res.issues)
