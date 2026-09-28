"""UI 冒烟测试（§9.2 pytest-qt）：窗口创建、页面流转、导入、P4 编辑重验、项目存取。

离屏渲染（QT_QPA_PLATFORM=offscreen），不依赖真实显示器。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from PyQt6.QtWidgets import QLabel, QPlainTextEdit


@pytest.fixture
def window(qtbot):
    from fungal_annot.ui.main_window import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    yield win


def test_window_has_four_pages(window):
    assert window.stack.count() == 4
    assert not hasattr(window, "page_blast")
    titles = [window.nav.item(i).text() for i in range(window.nav.count())]
    expect = ["1. Import & BLAST", "2. Reference", "3. Review", "4. Export"]
    for got, exp in zip(titles, expect):     # 前缀是步骤标记（▶/✓/•），只比标题
        assert got.strip().endswith(exp), (got, exp)
    assert "▶" in titles[0] and "•" in titles[1]   # 初始：第 1 步当前、后续锁定
    # 默认窗口大小夹取（≤1180x760，≥最小尺寸）
    assert window.size().width() <= 1180 and window.size().height() <= 760
    assert window.minimumSize().width() == 860 and window.minimumSize().height() == 560


def test_steps_laid_out_horizontally(qtbot, window):
    """四步水平排列：单行等宽平铺，随窗口宽度平分。"""
    from PyQt6.QtWidgets import QListView

    assert window.nav.flow() == QListView.Flow.LeftToRight
    assert not window.nav.isWrapping()
    window.resize(1100, 700)
    window.show()
    qtbot.waitUntil(lambda: window.nav.visualItemRect(window.nav.item(0)).width() > 0,
                    timeout=5000)
    rects = [window.nav.visualItemRect(window.nav.item(i))
             for i in range(window.nav.count())]
    assert len({r.y() for r in rects}) == 1                       # 同一行
    assert len({r.width() for r in rects}) == 1                   # 等宽
    assert [r.x() for r in rects] == sorted(r.x() for r in rects)
    assert rects[-1].right() <= window.nav.viewport().width() + 1  # 不超出可视区


def test_icon_toolbar_replaced_by_menu_bar(window):
    """原图标工具栏（New/Open/Save/Settings/Log）改为文字菜单栏。"""
    from PyQt6.QtWidgets import QToolBar

    assert window.findChildren(QToolBar) == []
    labels = [a.text() for a in window.menuBar().actions()]
    assert labels == ["&File", "&Tools"]
    file_items = [a.text() for a in window.menuBar().actions()[0].menu().actions()
                  if a.text()]
    assert file_items == ["New Project", "Open Project...", "Save Project...", "Exit"]


def test_log_dock_removed_status_bar_summarises(window):
    """去掉日志坞：消息落到状态栏左侧，右侧仅一个单格摘要（序列数/基因型 + 注释告警）。"""
    from PyQt6.QtWidgets import QDockWidget

    assert window.findChildren(QDockWidget) == []            # 无日志坞
    # 右侧常驻摘要只有 1 格（原 Step/序列/参考/注释/导出 5 格已合并/移除）
    summary = [w for w in window.statusBar().findChildren(QLabel)
               if w.objectName() == "StatusAlerts"]
    assert len(summary) == 1 and summary[0] is window.status_summary
    assert window.status_summary.text() == "no sequences"

    window.log("hello status bar")                            # 原 log() 通道
    assert window.statusBar().currentMessage() == "hello status bar"

    from fungal_annot.core.models import SeqInput
    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 30, gene_type="tef1"))
    window.exported = True
    window.update_summary()
    assert window.status_summary.text() == "1 sequence(s) · tef1"   # 未注释，无 ann 段


def test_step_nav_states_and_locking(window):
    """4 步检查条：步骤1 需序列+hits；其后依次需注释、审核、导出。"""
    from types import SimpleNamespace

    from fungal_annot.core.blast_runner import BlastHit
    from fungal_annot.core.models import SeqInput

    assert window._step_states() == [False, False, False, False]
    assert window._step_locked(1)[0]                    # 初始全锁

    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 100, gene_type="tef1"))
    window.go_page(0)
    assert window._step_states()[0] is False            # 有序列但无 hits
    assert window._step_locked(1)[0]                    # Reference 仍锁

    window.hits["s1"] = [BlastHit(accession="AA000001", title="hit", pident=99.0,
                                  qcovs=100.0, subject_len=100, flags={})]
    assert window._step_states()[0] is True
    assert not window._step_locked(1)[0]                # Reference 解锁
    assert window._step_locked(2)[0]                    # Review 仍锁（未注释）

    window.results["s1"] = SimpleNamespace(status="red")
    assert window._step_locked(3)[0]                    # 红灯未确认 → Export 锁
    window.confirmed["s1"] = True
    assert not window._step_locked(3)[0]                # 确认后 Export 解锁

    assert "▶" in window.nav.item(0).text()


def test_blast_all_have_hits_jumps_immediately(window):
    """全部序列已有 hits：Start 不发网络请求，直接排空并跳 Reference。"""
    from fungal_annot.core.blast_runner import BlastHit
    from fungal_annot.core.models import SeqInput

    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 60, gene_type="tef1"))
    window.hits["s1"] = [BlastHit(accession="AA000001", title="hit", pident=99.0,
                                  qcovs=100.0, subject_len=100, flags={})]
    window.settings["email"] = "a@example.org"
    window.page_import.refresh()
    window.page_import._start()
    assert window.stack.currentIndex() == 1          # 自动进入 Reference
    assert not window.page_import.b_cancel.isEnabled()
    assert window.page_import.b_start.isEnabled()


def test_blast_failure_drain_jumps(window):
    """worker 失败同样消耗 pending：队列排空 → 恢复按钮 → 跳 Reference。"""
    from fungal_annot.core.models import SeqInput

    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 60, gene_type="tef1"))
    window.page_import.progress.setMaximum(1)
    window._blast_pending = 1
    window._on_worker_failed("s1", "boom")
    assert window._blast_pending == 0
    assert window.stack.currentIndex() == 1
    assert not window.page_import.b_cancel.isEnabled()


def test_import_and_remove(window):
    from fungal_annot.core.models import SeqInput
    window.add_sequence(SeqInput(seq_id="t1", seq="ACGT" * 25, gene_type="tef1"))
    assert window.sequences[0].seq_id == "t1"
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
    assert [f.ftype for f in features] == ["gene", "CDS"]
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


def test_alignment_text_columns_truly_aligned(window, ref_record_seq, ref_gb_text):
    """回归：比对视图三行前缀等宽、'|' 与碱基逐列对齐（此前标记行偏移 1 列）。"""
    from fungal_annot.core.align_mapper import revcomp
    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence
    from fungal_annot.ui.pages.page_review import _alignment_text

    seq, _ = ref_record_seq
    # 含插入的查询（内部 indel 会产生 gap 列）
    q = seq[300:1600]
    q = q[:402] + "GCA" + q[402:]
    for query, orient in ((q, "forward"), (revcomp(q), "reverse")):
        res = annotate_sequence(SeqInput(seq_id="a", seq=query, gene_type="tef1"),
                                window.make_config(), reference_gb_text=ref_gb_text)
        text = _alignment_text(res.detail.mapping, res.detail.ref_seq)
        body = text.splitlines()[2:]          # 跳过头部与空行
        groups = [body[i:i + 4] for i in range(0, len(body) - 3, 4)]
        assert groups and all(len(g) == 4 for g in groups)
        for ref_l, m_l, q_l, blank in groups:
            assert blank == "" or blank is None
            assert len(ref_l) == len(m_l) == len(q_l)          # 三行等长
            rseq, mseq, qseq = ref_l[11:], m_l[11:], q_l[11:]  # 前缀 11 列
            assert len(rseq) == len(mseq) == len(qseq)
            for a, mk, b in zip(rseq, mseq, qseq):
                if mk == "|":
                    assert a == b and a != "-"                 # '|' 处碱基必须相同
            # 行首坐标为真实坐标（数字且单调不减）
            import re as _re
            r_lab = _re.match(r"R\s+(\d+|-)", ref_l)
            assert r_lab and r_lab.group(1) != "-"


def test_alignment_viewer_uses_monospace(qtbot, window, ref_record_seq, ref_gb_text):
    """回归：比对视图必须用等宽字体——全局 QSS 的比例字体会让 | 标记视觉错位。"""
    from fungal_annot.ui.pages.page_review import AlignmentDialog

    dlg = AlignmentDialog("title", "R       1  ACGT\n          |\nQ       1  ACGT")
    qtbot.addWidget(dlg)
    view = dlg.findChild(QPlainTextEdit)
    assert view is not None and view.objectName() == "MonoViewer"
    assert dlg.windowTitle() == "title"
    qss = open("fungal_annot/resources/style.qss", encoding="utf-8").read()
    assert "QPlainTextEdit#MonoViewer" in qss and "monospace" in qss


def test_reference_features_text(window, ref_record_seq, ref_gb_text):
    """Phase 3：View reference features —— 展示参考自身的五列 feature table
    （含 source 修饰符与参考原有 qualifier，如 protein_id）。"""
    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence

    seq, _ = ref_record_seq
    res = annotate_sequence(SeqInput(seq_id="a", seq=seq[300:1600], gene_type="tef1"),
                            window.make_config(), reference_gb_text=ref_gb_text)
    window.results["a"] = res
    window.page_review.current = "a"
    text = window.page_review._reference_features_text()
    assert text is not None
    assert text.startswith(">Feature REF00001.1")
    assert "201\t600\tCDS" in text and "701\t1149\tCDS" in text      # 参考坐标原样
    assert "\t\t\torganism\tFusarium referenceus" in text            # 合成 source 行（五列）
    assert "\t\t\tprotein_id\tNP_999.1" in text                      # 参考原有 qualifier 保留
    assert "codon_start" not in text                                 # 参考 CDS 完整，无该限定符



def test_parse_pasted_input():
    """统一导入框的文本解析：FASTA 多条 / 裸序列 / 非法输入。"""
    import pytest as _pytest
    from fungal_annot.ui.pages.page_import import parse_pasted_input

    seqs = parse_pasted_input(">a\nACGTACGT\n>b\nTTTTGGGG")
    assert [(s.seq_id, s.seq) for s in seqs] == [("a", "ACGTACGT"), ("b", "TTTTGGGG")]
    seqs = parse_pasted_input("  acgt acgt\n ")
    assert len(seqs) == 1 and seqs[0].seq_id == "pasted_seq"
    assert seqs[0].seq == "ACGTACGT"
    with _pytest.raises(ValueError):
        parse_pasted_input("")
    with _pytest.raises(ValueError):
        parse_pasted_input("ACGTX")   # X 非核苷酸字符


def test_import_box_flow(window, tmp_path):
    """统一输入框：文件拖入读入框内 → Import 解析入库并清空。"""
    from fungal_annot.core.models import SeqInput

    window.add_sequence(SeqInput(seq_id="g1", seq="ACGT" * 50))
    window.page_import.refresh()
    assert window.page_import.lbl_count.text() == "1 sequence(s) imported"

    box = window.page_import.import_box
    box.setPlainText(">s9\nACGTACGTACGT")
    window.page_import._import_box()
    assert window.sequences[-1].seq_id == "s9"
    assert box.toPlainText() == ""          # 导入成功后清空
    # 重复导入同一 Seq ID → 报错且不清空
    box.setPlainText(">s9\nACGTACGTACGT")
    window.page_import._import_box()
    assert box.toPlainText() != ""


def test_import_page_has_no_sequence_table(window):
    """P1 简化：去掉序列表格与 Paste from clipboard / Remove selected 按钮；
    导入三键统一主按钮样式、单词标签（BLAST 区按钮为合并页新增，另计）。"""
    from PyQt6.QtWidgets import QPushButton, QTableWidget

    page = window.page_import
    assert page.findChildren(QTableWidget) == []
    buttons = page.findChildren(QPushButton)
    assert [b.text() for b in buttons] == ["Import", "Browse", "Clear",
                                           "Start BLAST", "Cancel pending"]
    assert buttons[0].objectName() == "PrimaryButton"
    assert buttons[1].objectName() == "PrimaryButton"
    assert buttons[2].objectName() == "PrimaryButton"
    assert buttons[3].objectName() == "PrimaryButton"      # Start BLAST 主按钮
    assert not hasattr(page, "_remove_selected") and not hasattr(page, "_paste_clipboard")


def test_import_page_blast_section(window):
    """合并页 BLAST 区：无模式卡片/无 Next 按钮；Start 禁用条件（无序列/无 email）。"""
    from fungal_annot.core.models import SeqInput

    page = window.page_import
    assert hasattr(page, "b_start") and page.b_start.text() == "Start BLAST"
    assert hasattr(page, "b_cancel") and hasattr(page, "progress")
    assert hasattr(page, "chip_db") and hasattr(page, "chip_queue")
    assert hasattr(page, "lbl_hint") and hasattr(page, "on_queue_finished")
    assert not hasattr(page, "btn_mode_offline") and not hasattr(page, "mode_stack")
    assert not hasattr(page, "b_next") and not hasattr(page, "chip_mode")

    page.refresh()
    assert not page.b_start.isEnabled()                 # 无序列
    window.settings["email"] = ""                       # 隔离用户本机已保存的 Settings
    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 60, gene_type="tef1"))
    page.refresh()
    assert not page.b_start.isEnabled()                 # 未设 email
    assert "Settings" in page.b_start.toolTip()
    window.settings["email"] = "a@example.org"
    page.refresh()
    assert page.b_start.isEnabled()
    assert not page.b_cancel.isEnabled()


def test_import_box_loads_dropped_file(window, ref_record_seq, ref_gb_text, tmp_path):
    """文件拖入输入框：内容读入框内（裸序列文件自动补 FASTA 头）。"""
    seq, _ = ref_record_seq
    fa = tmp_path / "q.fasta"
    fa.write_text(">q1\n" + seq[300:900] + "\n", encoding="utf-8")
    bare = tmp_path / "bare.txt"
    bare.write_text(seq[300:900] + "\n", encoding="utf-8")

    box = window.page_import.import_box
    box.load_paths([str(fa)])
    assert ">q1" in box.toPlainText()
    box.load_paths([str(bare)])
    assert ">bare" in box.toPlainText()     # 裸序列文件自动补头


def test_loaded_project_reexports_without_crash(window, tmp_path, ref_record_seq, ref_gb_text):
    """回归 U4：加载项目后再次导出不得崩溃（SeqResultLite 需具备 report_row），
    且 features 应从项目文件恢复（审核表格与导出汇总正确）。"""
    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence, write_outputs
    from fungal_annot.services.project_store import load_project, save_project

    seq, _ = ref_record_seq
    s = SeqInput(seq_id="u4", seq=seq[300:1600], gene_type="tef1",
                 source_qualifiers={"organism": "F. t", "country": "China"})
    res = annotate_sequence(s, window.make_config(), reference_gb_text=ref_gb_text)
    path = str(tmp_path / "p.json")
    save_project(path, [s], {}, {}, {"u4": res}, {})
    sequences, _hits, _sel, results, _st = load_project(path)

    lite = results["u4"]
    assert [f.ftype for f in lite.features] == ["gene", "CDS"]  # feature 已恢复
    assert set(lite.report_row()) == set(res.report_row())                # 报告行同构
    assert lite.report_row()["n_features"] == 2
    written = write_outputs([lite], str(tmp_path / "out"), sequences)
    assert any(w.endswith("u4.tbl") for w in written)
    # 门户模式：.tbl 不含 source，输出与注释时的 tbl_text 一致
    out_tbl = (tmp_path / "out" / "u4.tbl").read_text(encoding="utf-8")
    assert "\tsource" not in out_tbl and "CDS" in out_tbl
    assert out_tbl == res.tbl_text


def test_reference_row_radio_default_and_pick(window):
    """Phase 2 简化：命中表每行单选框，默认第一行（推荐），点选即生效。"""
    from fungal_annot.core.blast_runner import BlastHit
    from fungal_annot.core.models import SeqInput

    window.add_sequence(SeqInput(seq_id="r1", seq="ACGT" * 60, gene_type="tef1"))
    window.hits["r1"] = [
        BlastHit(accession="AA000001", title="hit one, partial cds", pident=99.0,
                 qcovs=100.0, subject_len=60, flags={}),
        BlastHit(accession="AA000002", title="hit two, complete cds", pident=98.0,
                 qcovs=100.0, subject_len=60, flags={}),
    ]
    page = window.page_reference
    page.refresh()
    page.seq_list.setCurrentRow(0)

    # 默认选中第一行（推荐），且选择即写入状态
    assert window.selected_ref["r1"] == "AA000001"
    assert page.lbl_choice.text() == "Reference: AA000001"
    assert page.b_annotate.isEnabled()
    # 点第二行的单选框 → 选择切换
    page.hit_table._radios[1].setChecked(True)
    assert window.selected_ref["r1"] == "AA000002"
    # 单选互斥：第一行已取消勾选
    assert not page.hit_table._radios[0].isChecked()
    # Use recommended for all → 回到第一行
    page._use_recommended_all()
    assert window.selected_ref["r1"] == "AA000001"


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
