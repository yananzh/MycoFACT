"""审核页编辑往返的溯源回归（P0）。

背景（历史缺陷）：`FeatureTable.to_features()` 曾经只还原坐标与 qualifier 文本，
丢掉 `ref_key` 与各区段的参考坐标（`ref_start/ref_end`）。而 validator 正是靠
`ref_key` 把迁移后的 CDS 配回来源参考 CDS，靠参考坐标算核苷酸 identity，于是
**用户在审核页改任何一格之后**，三项依赖参考的校验会同时静默消失：

1. `/transl_table` 与参考不一致的冲突提示（§2.3）；
2. "翻译产物与参考蛋白 identity ≥ 95%" 的蛋白回检（§6.6）；
3. 核苷酸 identity 阈值门禁（§6.6，低相似必须红灯强制人工确认）。

实测（修复前）：参考 /transl_table=1、用户选 4 号表 → 编辑前 yellow
（transl_table_conflict），编辑后变 green 且无任何 issue。

本文件用**真实编辑器路径**（build_from_features → 改一格 → to_features）锁死
上述行为；另有 GUI 级回归确保导出的是编辑后的表，而不是缓存里的旧文本。
"""
from fungal_annot.core.models import Feature, FeaturePart, SeqInput
from fungal_annot.core.tbl_writer import write_tbl
from fungal_annot.core.validator import validate
from fungal_annot.services.pipeline import PipelineConfig, annotate_sequence
from fungal_annot.ui.widgets.feature_table import FeatureTable


def _annotate(q, cfg, ref_gb_text, sid="rt1"):
    return annotate_sequence(SeqInput(seq_id=sid, seq=q, gene_type="tef1"), cfg,
                             reference_gb_text=ref_gb_text)


def _codes(features, res, cfg, q, sid="rt1"):
    """按审核页重验的调用方式跑 validator，返回 issue code 集合。"""
    issues = validate(SeqInput(seq_id=sid, seq=q, gene_type="tef1"), features,
                      res.detail.mapping, res.detail.ref_features, res.detail.ref_seq,
                      res.detail.preset, cfg)
    return {i.code for i in issues}


def _roundtrip(qtbot, res, edit=True):
    """走真实编辑器往返：build_from_features → （可选）改一格 qualifier → to_features。"""
    table = FeatureTable()
    qtbot.addWidget(table)
    table.build_from_features(res.features)
    if edit:
        item = table.item(0, 3)
        item.setText(item.text() + "\nnote: touched by user")
    return table.to_features()


def _strip_provenance(features):
    """对照用：主动抹掉溯源，等价于修复前 to_features() 的行为。"""
    return [Feature(ftype=f.ftype, strand=f.strand,
                    parts=[FeaturePart(p.start, p.end, p.partial_low, p.partial_high)
                           for p in f.parts],
                    qualifiers={k: list(v) for k, v in f.qualifiers.items()},
                    ref_key=None) for f in features]


# ---- 编辑器往返本身 ---------------------------------------------------------

def test_to_features_preserves_provenance(qtbot):
    """ref_key 与各区段参考坐标必须随行往返，坐标/partial 语义不受影响。"""
    src = Feature(ftype="CDS", strand=1,
                  parts=[FeaturePart(1, 300, partial_low=True, ref_start=301, ref_end=600),
                         FeaturePart(401, 852, ref_start=701, ref_end=1149)],
                  qualifiers={"gene": ["tef1"], "codon_start": ["3"]},
                  ref_key=(301, 1149))
    table = FeatureTable()
    qtbot.addWidget(table)
    table.build_from_features([src])

    out = table.to_features()
    assert len(out) == 1
    assert out[0].ref_key == (301, 1149)
    assert [(p.ref_start, p.ref_end) for p in out[0].parts] == [(301, 600), (701, 1149)]
    assert out[0].parts[0].partial_low is True
    assert out[0].qualifiers["codon_start"] == ["3"]


def test_new_row_has_no_provenance(qtbot):
    """用户手工新增的行没有参考来源：ref_key 为 None、参考坐标为 0（由
    validator 的 ref_context_missing 提示，而不是假装通过）。"""
    table = FeatureTable()
    qtbot.addWidget(table)
    table.add_feature("CDS", "1..100")
    out = table.to_features()
    assert out[0].ref_key is None
    assert [(p.ref_start, p.ref_end) for p in out[0].parts] == [(0, 0)]


def test_manual_row_is_reported_as_uncheckable(ref_record_seq, ref_gb_text):
    """只有手工行（无参考坐标）时，validator 必须显式提示"查不了"而非静默跳过。"""
    seq, _ = ref_record_seq
    q = seq[300:1600]
    cfg = PipelineConfig(online=False)
    res = _annotate(q, cfg, ref_gb_text)
    manual = Feature(ftype="CDS", strand=1,
                     parts=[FeaturePart(1, 300), FeaturePart(401, 852)],
                     qualifiers={"codon_start": ["1"]})
    assert "ref_context_missing" in _codes([manual], res, cfg, q)


# ---- 三项依赖参考的校验：编辑后必须仍然生效 --------------------------------

def test_edit_keeps_transl_table_conflict(qtbot, ref_record_seq, ref_gb_text):
    """用户把码表覆盖成 4（参考是 1）→ 冲突提示在编辑后仍然存在。"""
    seq, _ = ref_record_seq
    q = seq[300:1600]
    cfg = PipelineConfig(online=False, user_transl_table=4)
    res = _annotate(q, cfg, ref_gb_text)
    assert "transl_table_conflict" in {i.code for i in res.issues}

    edited = _roundtrip(qtbot, res)
    assert "transl_table_conflict" in _codes(edited, res, cfg, q)
    # 对照：溯源被抹掉后该提示消失（即修复前的行为）
    assert "transl_table_conflict" not in _codes(_strip_provenance(edited), res, cfg, q)


def test_edit_keeps_identity_gate(qtbot, ref_record_seq, ref_gb_text):
    """低相似序列（阈值 100%）在编辑后仍必须红：identity 门禁不得消失。"""
    seq, _ = ref_record_seq
    q = list(seq[300:1600])
    for i in range(30, len(q) - 30, 97):        # 掺入错配，压低核苷酸一致性
        q[i] = "A" if q[i] != "A" else "C"
    q = "".join(q)
    cfg = PipelineConfig(online=False, identity_threshold=100.0)
    res = _annotate(q, cfg, ref_gb_text)
    assert "low_identity" in {i.code for i in res.issues}

    edited = _roundtrip(qtbot, res)
    assert "low_identity" in _codes(edited, res, cfg, q)


def test_edit_keeps_protein_identity_backcheck(qtbot, ref_record_seq, ref_gb_text):
    """用户手改坐标造成移码：蛋白回检必须仍然报出与参考蛋白不符。"""
    seq, _ = ref_record_seq
    q = seq[300:1600]
    cfg = PipelineConfig(online=False)
    res = _annotate(q, cfg, ref_gb_text)

    table = FeatureTable()
    qtbot.addWidget(table)
    table.build_from_features(res.features)
    row = next(r for r in range(table.rowCount())
               if table.item(r, 0).text() == "CDS")
    head, sep, tail = table.item(row, 2).text().partition(",")
    start, end = head.strip().lstrip("<>").split("..")
    table.item(row, 2).setText(f"{int(start) + 1}..{end}" + (sep + tail if sep else ""))
    edited = table.to_features()

    assert "protein_identity" in _codes(edited, res, cfg, q)
    # 对照：溯源被抹掉后回检不执行（即修复前的行为）
    assert "protein_identity" not in _codes(_strip_provenance(edited), res, cfg, q)


# ---- GUI 级：导出的必须是编辑后的表 ----------------------------------------

def test_gui_export_reflects_just_made_edit(window, tmp_path,
                                            ref_record_seq, ref_gb_text, monkeypatch):
    """回归（P0）：在防抖窗口内（不等待 600ms）改一格后立即导出，
    导出的 .tbl 必须包含这次编辑——不能写出缓存里的旧文本。"""
    from PyQt6.QtWidgets import QMessageBox

    seq, _ = ref_record_seq
    q = seq[300:1600]
    window.add_sequence(SeqInput(seq_id="x1", seq=q, gene_type="tef1"))
    window.results["x1"] = {"REF00001.1": _annotate(q, window.make_config(),
                                                    ref_gb_text, sid="x1")}
    page = window.page_review
    page.refresh()
    page.seq_list.setCurrentRow(0)
    assert page.current == "x1"

    item = page.feature_table.item(0, 3)
    item.setText(item.text() + "\ngene_synonym: edited_marker")
    assert page._reval_timer.isActive()          # 仍在防抖窗口内

    out = tmp_path / "out"
    page_export = window.page_export
    page_export.refresh()
    page_export.dir_edit.setText(str(out))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    page_export._export()

    text = (out / "x1.tbl").read_text(encoding="utf-8")
    assert "edited_marker" in text
    res = window.results["x1"]["REF00001.1"]
    assert text == write_tbl(res.features, "x1")


def test_gui_export_skips_zero_feature_sequence(window, tmp_path,
                                               ref_record_seq, ref_gb_text, monkeypatch):
    """零产出序列导出时不写文件，并在完成弹窗里点名（不产生空 .tbl）。"""
    from PyQt6.QtWidgets import QMessageBox

    from fungal_annot.services.pipeline import SeqResult

    seq, _ = ref_record_seq
    q = seq[300:1600]
    window.add_sequence(SeqInput(seq_id="ok1", seq=q, gene_type="tef1"))
    window.add_sequence(SeqInput(seq_id="none1", seq=q, gene_type="tef1"))
    window.results["ok1"] = {"REF00001.1": _annotate(q, window.make_config(),
                                                     ref_gb_text, sid="ok1")}
    window.results["none1"] = {"REF00001.1": SeqResult(seq_id="none1", status="red")}

    out = tmp_path / "out"
    page_export = window.page_export
    page_export.refresh()
    page_export.dir_edit.setText(str(out))
    shown = []
    # 红灯序列会先弹知情确认：离屏下必须桩掉，否则模态阻塞
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(a[2] if len(a) > 2 else "")
                                     or QMessageBox.StandardButton.Ok))
    page_export._export()

    assert sorted(p.name for p in out.glob("*.tbl")) == ["all_features.tbl", "ok1.tbl"]
    assert shown and "none1" in shown[0]
