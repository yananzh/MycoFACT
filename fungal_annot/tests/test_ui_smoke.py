"""UI 冒烟测试（§9.2 pytest-qt）：窗口创建、页面流转、导入、P4 编辑重验、项目存取。

离屏渲染（QT_QPA_PLATFORM=offscreen），不依赖真实显示器。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture
def window(qtbot):
    from fungal_annot.ui.main_window import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    yield win


def test_window_has_five_pages(window):
    assert window.stack.count() == 5
    titles = [window.nav.item(i).text() for i in range(window.nav.count())]
    expect = ["1. Import", "2. BLAST / Reference", "3. Reference Selection",
              "4. Review & Edit", "5. Summary & Export"]
    for got, exp in zip(titles, expect):     # 前缀是步骤标记（▶/✓/•），只比标题
        assert got.strip().endswith(exp), (got, exp)
    assert "▶" in titles[0] and "•" in titles[1]   # 初始：第 1 步当前、后续锁定


def test_step_nav_states_and_locking(window):
    """Phase 2 步骤检查条：未完成前置步骤时后续导航锁定。"""
    from PyQt6.QtCore import Qt

    states = window._step_states()
    assert states == [False, False, False, False, False]
    # 初始（未导入）时第 2 步锁定
    locked, reason = window._step_locked(1)
    assert locked
    # 导入序列后：第 1 步完成、第 2 步解锁、第 3 步仍锁定
    from fungal_annot.core.models import SeqInput
    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 100, gene_type="tef1"))
    window.go_page(0)
    states = window._step_states()
    assert states[0] is True and states[1] is False
    locked, _ = window._step_locked(1)
    assert not locked
    locked, _ = window._step_locked(2)
    assert locked
    # 当前步在导航中带 ▶ 标记
    assert "▶" in window.nav.item(0).text()


def test_import_and_gene_type(window):
    from fungal_annot.core.models import SeqInput
    window.add_sequence(SeqInput(seq_id="t1", seq="ACGT" * 25, gene_type="tef1"))
    assert window.sequences[0].seq_id == "t1"
    window.set_gene_type("t1", "rpb2")
    assert window.sequences[0].gene_type == "rpb2"
    window.remove_sequence("t1")
    assert window.sequences == []


def test_offline_annotate_and_review(window, ref_record_seq, ref_gb_text):
    """离线参考 → 注释 → P4 表格回读 → 重验状态不变。"""
    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence

    seq, _ = ref_record_seq
    q = seq[300:1600]
    window.add_sequence(SeqInput(seq_id="u1", seq=q, gene_type="tef1",
                                 source_qualifiers={"organism": "Fusarium testicum",
                                                    "country": "China"}))
    window.local_ref_text = ref_gb_text
    res = annotate_sequence(window.sequences[0], window.make_config(),
                            reference_gb_text=ref_gb_text)
    window.results["u1"] = res

    page = window.page_review
    page.refresh()
    page.load_result("u1")
    features = page.feature_table.to_features()
    assert [f.ftype for f in features] == ["source", "gene", "CDS"]
    # P4 编辑重验：不加改动重验，状态应保持
    page.current = "u1"
    page._revalidate()
    assert window.results["u1"].status == res.status


def test_review_edit_revalidate_detects_error(window, ref_record_seq, ref_gb_text):
    """§8 M5 验收：手工编辑坐标后即时重验——把 CDS 改成越界坐标应报 error。"""
    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence

    seq, _ = ref_record_seq
    q = seq[300:1600]
    window.add_sequence(SeqInput(seq_id="u2", seq=q, gene_type="tef1",
                                 source_qualifiers={"organism": "Fusarium testicum",
                                                    "country": "China"}))
    window.local_ref_text = ref_gb_text
    res = annotate_sequence(window.sequences[0], window.make_config(),
                            reference_gb_text=ref_gb_text)
    window.results["u2"] = res
    page = window.page_review
    page.refresh()
    page.current = "u2"
    page.load_result("u2")

    # 编辑：CDS 坐标改到超出序列长度
    row = next(r for r in range(page.feature_table.rowCount())
               if page.feature_table.item(r, 0).text() == "CDS")
    page.feature_table.item(row, 2).setText("1..300, 401..99999")
    page._revalidate()
    assert window.results["u2"].status == "red"
    assert any(i.code == "coord_out_of_range" for i in window.results["u2"].issues)


def test_project_save_load_roundtrip(window, tmp_path, ref_record_seq, ref_gb_text):
    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence
    from fungal_annot.services.project_store import load_project, save_project

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="p1", seq=seq[300:1600], gene_type="tef1",
                                 source_qualifiers={"organism": "F. t"}))
    res = annotate_sequence(window.sequences[0], window.make_config(),
                            reference_gb_text=ref_gb_text)
    window.results["p1"] = res
    path = str(tmp_path / "proj.json")
    save_project(path, window.sequences, window.hits, window.selected_ref,
                 window.results, window.settings)
    sequences, hits, selected_ref, results, settings = load_project(path)
    assert [s.seq_id for s in sequences] == ["p1"]
    assert results["p1"].status == res.status
    assert results["p1"].tbl_text == res.tbl_text


def test_start_annotation_button_flow(qtbot, window, ref_record_seq, ref_gb_text):
    """§8 M4/M5 验收：点击 Start Annotation（真实按钮处理器）→ 后台注释 →
    结果落盘 → 自动跳转审核页。回归点：曾因 _Worker 改名漏改导致点击即崩。"""
    from fungal_annot.core.models import SeqInput

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="u1", seq=seq[300:1600], gene_type="tef1",
                                 source_qualifiers={"organism": "Fusarium testicum",
                                                    "country": "China"}))
    window.local_ref_text = ref_gb_text
    window.page_reference.refresh()
    window.page_reference.seq_list.setCurrentRow(0)

    window.page_reference._start_annotate()      # 真实按钮处理器（含队列提交）
    assert window._annotate_pending == 1
    qtbot.waitUntil(lambda: "u1" in window.results, timeout=60000)
    qtbot.waitUntil(lambda: window._annotate_pending <= 0, timeout=60000)
    assert window.results["u1"].status in ("green", "yellow")
    assert window.stack.currentIndex() == 3      # 完成后自动进入审核页


def test_alignment_view_text(window, ref_record_seq, ref_gb_text):
    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence
    from fungal_annot.ui.pages.page_review import _alignment_text

    seq, _ = ref_record_seq
    res = annotate_sequence(SeqInput(seq_id="a", seq=seq[300:1600], gene_type="tef1"),
                            window.make_config(), reference_gb_text=ref_gb_text)
    text = _alignment_text(res.detail.mapping, res.detail.ref_seq)
    assert "Orientation: forward" in text
    assert "|" in text          # 存在匹配标记
