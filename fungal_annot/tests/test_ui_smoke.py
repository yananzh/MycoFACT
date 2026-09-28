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
    expect = ["1. Import & BLAST", "2. Select Reference", "3. Review Annotation",
              "4. Export Results"]
    for got, exp in zip(titles, expect):     # 前缀是步骤标记（▶/✓/•），只比标题
        assert got.strip().endswith(exp), (got, exp)
    assert "▶" in titles[0] and "•" in titles[1]   # 初始：第 1 步当前、后续锁定
    # 默认窗口大小夹取（≤1060x700，≥最小尺寸）
    assert window.size().width() <= 1060 and window.size().height() <= 700
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
    assert not window.page_import.b_stop.isEnabled()
    assert window.page_import.b_blast.isEnabled()


def test_blast_failure_drain_jumps(window):
    """worker 失败同样消耗 pending：队列排空 → 恢复按钮 → 跳 Reference。"""
    from fungal_annot.core.models import SeqInput

    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 60, gene_type="tef1"))
    window.page_import.progress.setMaximum(1)
    window._blast_pending = 1
    window._on_worker_failed("s1", "boom")
    assert window._blast_pending == 0
    assert window.stack.currentIndex() == 1
    assert not window.page_import.b_stop.isEnabled()


def test_blast_success_drain_jumps(window):
    """worker 正常完成（最常见路径）：命中落盘 → 排空 → 跳 Reference。"""
    from fungal_annot.core.blast_runner import BlastHit
    from fungal_annot.core.models import SeqInput

    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 60, gene_type="tef1"))
    window.page_import.progress.setMaximum(1)
    window._blast_pending = 1
    hit = BlastHit(accession="AA000001", title="hit", pident=99.0,
                   qcovs=100.0, subject_len=100, flags={})
    window._on_worker_finished("s1", [hit])
    assert window._blast_pending == 0
    assert window.hits["s1"] == [hit]
    assert window.stack.currentIndex() == 1
    assert not window.page_import.b_stop.isEnabled()


def test_blast_finish_after_discard_stays_put(window):
    """项目被丢弃后 worker 完成：不写陈旧命中、不强制跳 Reference。"""
    from fungal_annot.core.blast_runner import BlastHit
    from fungal_annot.core.models import SeqInput

    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 60, gene_type="tef1"))
    window.page_import.progress.setMaximum(1)
    window._blast_pending = 1
    window.sequences.clear()               # 模拟运行中 New/Clear（绕过 QMessageBox）
    window._on_worker_finished("s1", [BlastHit(accession="AA000001", title="hit",
                                               pident=99.0, qcovs=100.0,
                                               subject_len=100, flags={})])
    assert window._blast_pending == 0
    assert "s1" not in window.hits
    assert window.stack.currentIndex() == 0


def test_start_blast_disabled_while_queue_running(window):
    """队列运行中 refresh() 不得把 Start 重新点亮（防双重提交）。"""
    from fungal_annot.core.models import SeqInput

    window.settings["email"] = "a@example.org"
    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 60, gene_type="tef1"))
    window._blast_pending = 1
    window.page_import.refresh()
    assert not window.page_import.b_blast.isEnabled()
    window._blast_pending = 0
    window.page_import.refresh()
    assert window.page_import.b_blast.isEnabled()


def test_import_and_remove(window):
    from fungal_annot.core.models import SeqInput
    window.add_sequence(SeqInput(seq_id="t1", seq="ACGT" * 25, gene_type="tef1"))
    assert window.sequences[0].seq_id == "t1"
    window.remove_sequence("t1")
    assert window.sequences == []


def test_gui_has_no_offline_entry(window):
    """验收：GUI 无任何本地参考入口（离线仅 CLI --ref-gb）。"""
    from fungal_annot.core.models import SeqInput

    assert not hasattr(window, "local_ref_text")
    assert not hasattr(window, "local_ref_name")
    assert not hasattr(window, "load_local_reference")
    assert not hasattr(window.page_reference, "lbl_offline")

    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 100, gene_type="tef1"))
    window.page_reference.refresh()
    assert not window.page_reference.b_annotate.isEnabled()   # 无 hits → 不就绪


def test_annotate_and_review(window, ref_record_seq, ref_gb_text):
    """参考下载 → 注释 → P4 表格回读 → 重验状态不变。"""
    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence

    seq, _ = ref_record_seq
    q = seq[300:1600]
    window.add_sequence(SeqInput(seq_id="u1", seq=q, gene_type="tef1",
                                 source_qualifiers={"organism": "Fusarium testicum",
                                                    "country": "China"}))
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
    page._auto_revalidate()
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
    page._auto_revalidate()
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
    window.confirmed["p1"] = True       # 红灯确认与导出标记必须跨会话保留
    window.exported = True
    path = str(tmp_path / "proj.json")
    save_project(path, window.sequences, window.hits, window.selected_ref,
                 window.results, window.settings,
                 confirmed=window.confirmed, exported=window.exported)
    (sequences, hits, selected_ref, results, settings,
     confirmed, exported) = load_project(path)
    assert [s.seq_id for s in sequences] == ["p1"]
    assert results["p1"].status == res.status
    assert results["p1"].tbl_text == res.tbl_text
    assert confirmed == {"p1": True}
    assert exported is True


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
    """View reference features —— 展示参考自身的五列 feature table
    （不含 source；保留参考原有 qualifier，如 protein_id）。"""
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
    assert "\tsource" not in text and "organism" not in text         # source 信息已去掉
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


def test_import_box_flow(window):
    """统一输入框：点 BLAST 自动导入框内文本并清空（预置 hits → 同步排空无网络）。"""
    from fungal_annot.core.blast_runner import BlastHit
    from fungal_annot.core.models import SeqInput

    hit = [BlastHit(accession="AA000001", title="hit", pident=99.0,
                    qcovs=100.0, subject_len=100, flags={})]
    window.add_sequence(SeqInput(seq_id="g1", seq="ACGT" * 50))
    window.hits["g1"] = hit                        # 防止真实网络请求
    window.settings["email"] = "a@example.org"
    window.page_import.refresh()
    assert window.page_import.lbl_count.text() == "1 sequence(s) imported"

    box = window.page_import.import_box
    box.setPlainText(">s9\nACGTACGTACGT")
    window.hits["s9"] = hit                        # 防止真实网络请求
    window.page_import.refresh()
    window.page_import._start()                    # BLAST = 自动导入 + 启动
    assert window.sequences[-1].seq_id == "s9"
    assert box.toPlainText() == ""                 # 导入成功后清空
    assert window.stack.currentIndex() == 1        # 全有 hits → 同步排空跳转


def test_import_page_sequence_list_and_buttons(window):
    """P1 序列清单（2026-09-28 恢复并增强）：ID/长度/基因型/BLAST/删除列；
    五按钮 BLAST/Browse/Example/Clear/STOP 水平排列，仅 BLAST 为主按钮样式。"""
    from PyQt6.QtWidgets import QPushButton, QTableWidget

    page = window.page_import
    tables = page.findChildren(QTableWidget)
    assert len(tables) == 1 and tables[0] is page.seq_table
    assert [page.seq_table.horizontalHeaderItem(i).text()
            for i in range(page.seq_table.columnCount())] == \
        ["Seq ID", "Length (bp)", "Marker", "BLAST", ""]
    buttons = page.findChildren(QPushButton)
    assert [b.text() for b in buttons] == ["BLAST", "Browse", "Example", "Clear", "STOP"]
    assert buttons[0].objectName() == "PrimaryButton"      # BLAST 主行动
    assert all(b.objectName() == "" for b in buttons[1:])  # 其余默认描边
    widths = {(b.minimumWidth(), b.maximumWidth()) for b in buttons}   # 五按钮等宽
    assert len(widths) == 1 and buttons[0].minimumWidth() == buttons[0].maximumWidth()
    assert not hasattr(page, "_remove_selected") and not hasattr(page, "_paste_clipboard")


def test_example_button_loads_demo_fasta(window):
    """Example 按钮：demo/example.fasta 载入输入框（追加、不触网），可正常解析；
    状态栏报出序列条数并说明需点 BLAST 导入。"""
    from fungal_annot.ui.pages.page_import import parse_pasted_input

    page = window.page_import
    page._load_example()
    text = page.import_box.toPlainText()
    assert text.startswith(">")
    seqs = parse_pasted_input(text)
    assert [s.seq_id for s in seqs] == ["ACT_G2", "TUB2_G2", "Gapdh_G2", "CAL_G2"]
    assert all(len(s.seq) > 100 for s in seqs)
    message = window.statusBar().currentMessage()
    assert "4 sequence(s)" in message and "click BLAST to run" in message


def test_import_page_blast_section(window):
    """合并页：四按钮 BLAST/Browse/Clear/STOP；无 chips、无页标题、无 Import 键；
    BLAST 禁用条件（无序列且框空 / 无 email / 队列运行中）。"""
    from PyQt6.QtWidgets import QLabel
    from fungal_annot.core.models import SeqInput

    page = window.page_import
    assert hasattr(page, "b_blast") and page.b_blast.text() == "BLAST"
    assert hasattr(page, "b_stop") and page.b_stop.text() == "STOP"
    assert hasattr(page, "progress") and hasattr(page, "on_queue_finished")
    assert hasattr(page, "lbl_hint")
    assert not hasattr(page, "chip_db") and not hasattr(page, "chip_queue")
    assert not hasattr(page, "b_import") and not hasattr(page, "b_cancel")
    assert not hasattr(page, "b_start")
    titles = [l for l in page.findChildren(QLabel) if l.objectName() == "PageTitle"]
    assert titles == []                             # 页标题标签已移除

    page.refresh()
    assert not page.b_blast.isEnabled()             # 无序列且框为空
    window.settings["email"] = ""                    # 隔离用户本机已保存的 Settings
    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 60, gene_type="tef1"))
    page.refresh()
    assert not page.b_blast.isEnabled()             # 未设 email
    assert "Settings" in page.b_blast.toolTip()
    window.settings["email"] = "a@example.org"
    page.refresh()
    assert page.b_blast.isEnabled()
    assert not page.b_stop.isEnabled()
    # 框内有文本 → 无序列也可点（点击时自动导入）
    window.sequences.clear()
    page.refresh()
    assert not page.b_blast.isEnabled()
    page.import_box.setPlainText(">x\nACGTACGTACGT")   # textChanged → 自动 refresh
    assert page.b_blast.isEnabled()


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
    (sequences, _hits, _sel, results, _st,
     _confirmed, _exported) = load_project(path)

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
    assert page.b_annotate.isEnabled()
    # Reference choice 区域已删：直接输入 accession 的入口不存在
    assert not hasattr(page, "lbl_choice") and not hasattr(page, "accession_edit")
    # 点第二行的单选框 → 选择切换
    page.hit_table._radios[1].setChecked(True)
    assert window.selected_ref["r1"] == "AA000002"
    # 单选互斥：第一行已取消勾选
    assert not page.hit_table._radios[0].isChecked()
    # Use recommended for all → 回到第一行
    page._use_recommended_all()
    assert window.selected_ref["r1"] == "AA000001"


def test_start_annotation_button_flow(qtbot, window, ref_record_seq, ref_gb_text, monkeypatch):
    """§8 M4/M5 验收：命中路径 + 桩下载 → 真实按钮 → 自动进入审核页（索引 2）。"""
    from fungal_annot.core.blast_runner import BlastHit
    from fungal_annot.core.models import SeqInput

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="u1", seq=seq[300:1600], gene_type="tef1",
                                 source_qualifiers={"organism": "Fusarium testicum",
                                                    "country": "China"}))
    window.hits["u1"] = [BlastHit(accession="REF00001.1",
                                  title="Fusarium referenceus tef1 gene",
                                  pident=99.0, qcovs=100.0, subject_len=2000, flags={})]
    monkeypatch.setattr("fungal_annot.services.pipeline.fetch_gb_text",
                        lambda accession, **kw: (ref_gb_text, "full"))
    window.page_reference.refresh()          # 自动选中推荐 → selected_ref 就绪
    window.page_reference.seq_list.setCurrentRow(0)

    window.page_reference._start_annotate()  # 真实按钮处理器（含队列提交）
    assert window._annotate_pending == 1
    qtbot.waitUntil(lambda: "u1" in window.results, timeout=60000)
    qtbot.waitUntil(lambda: window._annotate_pending <= 0, timeout=60000)
    assert window.results["u1"].status in ("green", "yellow")
    assert window.stack.currentIndex() == 2  # 完成后自动进入审核页（4 步向导）


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


# ---- P0/P1 修复回归（2026-09-28）----

def test_import_dedupe_ids(window):
    """整体查重：用户命名重复报错；pasted_seq 冲突自动编号。"""
    from fungal_annot.core.models import SeqInput

    page = window.page_import
    window.add_sequence(SeqInput(seq_id="user_seq", seq="ACGT"))
    with pytest.raises(ValueError):
        page._dedupe_ids([SeqInput(seq_id="user_seq", seq="ACGT")])
    seqs = [SeqInput(seq_id="pasted_seq", seq="ACGT"),
            SeqInput(seq_id="pasted_seq", seq="TTTT")]
    page._dedupe_ids(seqs)
    assert [s.seq_id for s in seqs] == ["pasted_seq", "pasted_seq_2"]


def test_start_blast_imports_box_and_lists_sequences(window, monkeypatch):
    """BLAST 一键导入成功后清空输入框，序列出现在清单表里。"""
    from PyQt6.QtCore import Qt

    window.settings["email"] = "a@example.org"
    monkeypatch.setattr(window, "start_blast", lambda: None)   # 不发网络请求
    page = window.page_import
    page.import_box.setPlainText("ACGTACGTACGT")
    page._start()
    assert [s.seq_id for s in window.sequences] == ["pasted_seq"]
    assert page.import_box.toPlainText() == ""
    assert page.seq_table.isVisibleTo(page)
    assert page.seq_table.rowCount() == 1
    assert page.seq_table.item(0, 0).text() == "pasted_seq"
    # 长度/基因型/状态列只读
    assert not page.seq_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEditable


def test_rename_sequence_moves_stores_and_result(window):
    """改名：SeqInput/命中/结果/确认随新名迁移，res.seq_id 同步。"""
    from types import SimpleNamespace

    from fungal_annot.core.models import SeqInput

    window.add_sequence(SeqInput(seq_id="old", seq="ACGT" * 5))
    window.hits["old"] = []
    window.results["old"] = SimpleNamespace(seq_id="old", status="green")
    window.confirmed["old"] = True
    window.rename_sequence("old", "new")
    assert window.sequences[0].seq_id == "new"
    assert "new" in window.hits and "old" not in window.hits
    assert window.results["new"].seq_id == "new"
    assert window.confirmed.get("new") is True


def test_review_auto_revalidate_on_edit(window, qtbot, ref_record_seq, ref_gb_text):
    """编辑坐标后防抖自动重验：无需点 Re-validate，红灯即时反映。"""
    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="u2", seq=seq[300:1600], gene_type="tef1",
                                 source_qualifiers={"organism": "F. t",
                                                    "country": "China"}))
    window.results["u2"] = annotate_sequence(window.sequences[0], window.make_config(),
                                             reference_gb_text=ref_gb_text)
    page = window.page_review
    page.refresh()
    page.current = "u2"
    page.load_result("u2")
    row = next(r for r in range(page.feature_table.rowCount())
               if page.feature_table.item(r, 0).text() == "CDS")
    page.feature_table.item(row, 2).setText("1..300, 401..99999")
    qtbot.waitUntil(lambda: window.results["u2"].status == "red", timeout=5000)
    assert any(i.code == "coord_out_of_range" for i in window.results["u2"].issues)

    # 非法坐标：行内提示、不弹窗、上次结果保留
    page.feature_table.item(row, 2).setText("garbage")
    qtbot.waitUntil(lambda: page.lbl_status.text().startswith("⚠"), timeout=5000)
    assert window.results["u2"].status == "red"


def test_feature_add_and_delete_row(window, qtbot, ref_record_seq, ref_gb_text):
    """feature 行增删：source 行禁止删除（合成行验证守卫）；增删触发自动重验。"""
    from fungal_annot.core.models import Feature, FeaturePart, SeqInput
    from fungal_annot.services.pipeline import annotate_sequence

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="u3", seq=seq[300:1600], gene_type="tef1",
                                 source_qualifiers={"organism": "F. t",
                                                    "country": "China"}))
    window.results["u3"] = annotate_sequence(window.sequences[0], window.make_config(),
                                             reference_gb_text=ref_gb_text)
    page = window.page_review
    page.refresh()
    page.current = "u3"
    page.load_result("u3")
    n0 = page.feature_table.rowCount()

    # source 行不可删（正常注释结果不含 source，用合成行验证守卫）
    page.feature_table.build_from_features(
        [Feature(ftype="source", strand=1, parts=[FeaturePart(1, 100)])])
    page.feature_table.selectRow(0)
    assert page.feature_table.remove_rows(page.feature_table.selected_rows())
    page.load_result("u3")

    # 删除 CDS 行 → 行数减少
    cds_row = next(r for r in range(n0) if page.feature_table.item(r, 0).text() == "CDS")
    page.feature_table.selectRow(cds_row)
    page._delete_feature()
    assert page.feature_table.rowCount() == n0 - 1

    # 新增一行 CDS（覆盖全长）→ 防抖重验跑完并写日志
    page._add_feature()
    assert page.feature_table.rowCount() == n0
    last = page.feature_table.rowCount() - 1
    assert page.feature_table.item(last, 0).text() == "CDS"
    qtbot.waitUntil(lambda: "Auto re-validated" in window.statusBar().currentMessage(),
                    timeout=5000)


def test_issue_click_opens_glossary(window, qtbot, monkeypatch):
    """带术语卡的 issue（low_identity 等）点击弹出解释卡。"""
    from fungal_annot.core.models import Issue, Provenance, SeqInput
    from fungal_annot.services.pipeline import SeqResult

    window.add_sequence(SeqInput(seq_id="u4", seq="ACGT" * 100, gene_type="tef1"))
    res = SeqResult(seq_id="u4", status="red",
                    issues=[Issue("error", "low_identity", "identity 90% < threshold")],
                    provenance=Provenance())
    window.results["u4"] = res
    page = window.page_review
    page.refresh()
    page.current = "u4"
    page.load_result("u4")
    shown = []
    # page_review 里是 `from ..widgets.help import show_help`，须 patch 其模块引用
    monkeypatch.setattr("fungal_annot.ui.pages.page_review.show_help",
                        lambda term, parent=None: shown.append(term))
    item = page.issue_list.item(0)
    page._on_issue_clicked(item)
    assert shown == ["identity"]


def test_accession_dialog_layout(window):
    """View match 弹窗：序列名只读、第二列预填当前选择、values() 含全部行。"""
    from PyQt6.QtCore import Qt

    from fungal_annot.core.models import SeqInput
    from fungal_annot.ui.pages.page_reference import AccessionDialog

    window.add_sequence(SeqInput(seq_id="d1", seq="ACGT" * 10))
    window.add_sequence(SeqInput(seq_id="d2", seq="ACGT" * 10))
    dlg = AccessionDialog(window.sequences, {"d2": "MZ123456.1"}, window)
    assert dlg.table.rowCount() == 2
    assert dlg.table.item(0, 0).text() == "d1"
    assert dlg.table.item(0, 1).text() == ""            # 无选择 → 空白
    assert dlg.table.item(1, 1).text() == "MZ123456.1"  # 预填当前选择
    assert not dlg.table.item(0, 0).flags() & Qt.ItemFlag.ItemIsEditable
    dlg.table.item(0, 1).setText(" PP227174.1 ")
    assert dlg.values() == {"d1": "PP227174.1", "d2": "MZ123456.1"}


def test_enter_accessions_applies_values(window, monkeypatch):
    """View match：非空行手动指定参考，清空行回落推荐命中；取消不应用。"""
    from fungal_annot.core.blast_runner import BlastHit
    from fungal_annot.core.models import SeqInput
    from fungal_annot.ui.pages import page_reference as pr_mod

    for sid in ("m1", "m2"):
        window.add_sequence(SeqInput(seq_id=sid, seq="ACGT" * 60, gene_type="tef1"))
        window.hits[sid] = [BlastHit(accession="AA000001", title="hit", pident=99.0,
                                     qcovs=100.0, subject_len=60, flags={})]
    page = window.page_reference
    page.refresh()
    assert window.selected_ref["m2"] == "AA000001"       # refresh 自动取推荐

    class StubDialog:
        def __init__(self, sequences, current, parent=None):
            self.sequences, self.current = sequences, current
        def exec(self):
            return pr_mod.QDialog.DialogCode.Accepted
        def values(self):
            return {"m1": "MZ123456.1", "m2": ""}        # m2 清空 → 回落推荐
    monkeypatch.setattr(pr_mod, "AccessionDialog", StubDialog)
    page._enter_accessions()
    assert window.selected_ref["m1"] == "MZ123456.1"     # 手填覆盖
    assert window.selected_ref["m2"] == "AA000001"       # 清空 → 回落推荐

    # 取消（Rejected）→ 不应用
    class StubCancel(StubDialog):
        def exec(self):
            return pr_mod.QDialog.DialogCode.Rejected
    monkeypatch.setattr(pr_mod, "AccessionDialog", StubCancel)
    window.selected_ref["m1"] = "AA000001"
    page._enter_accessions()
    assert window.selected_ref["m1"] == "AA000001"


def test_review_status_wording_and_confirm(window, ref_record_seq, ref_gb_text, monkeypatch):
    """状态文案动作化：Confirm 随状态变化（红灯必选→已确认禁用），列表用新标记。"""
    from PyQt6.QtWidgets import QInputDialog

    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="w1", seq=seq[300:1600], gene_type="tef1",
                                 source_qualifiers={"organism": "F. t", "country": "China"}))
    window.results["w1"] = annotate_sequence(window.sequences[0], window.make_config(),
                                             reference_gb_text=ref_gb_text)
    page = window.page_review
    page.refresh()
    page.current = "w1"
    page.load_result("w1")
    status = window.results["w1"].status
    if status == "red":
        assert "Needs review" in page.lbl_status.text()
        assert page.b_confirm.text() == "Confirm for export (required)"
        assert page.b_confirm.isEnabled()
    elif status == "yellow":
        assert "Ready" in page.lbl_status.text()
        assert page.b_confirm.text() == "Confirm for export (optional)"
    else:
        assert page.lbl_status.text() == "w1: Ready"
        assert not page.b_confirm.isEnabled()

    # 确认（黄/红）→ 按钮变为已确认并禁用；绿灯本就无需确认
    if status != "green":
        monkeypatch.setattr(QInputDialog, "getText",
                            staticmethod(lambda *a, **k: ("known issue", True)))
        page._manual_confirm()
        assert window.confirmed["w1"] is True
        assert page.b_confirm.text().startswith("Confirmed")
        assert not page.b_confirm.isEnabled()
        assert "manually confirmed" in page.lbl_status.text()

    # 列表标记用新文案
    item_text = page.seq_list.item(0).text()
    assert any(m in item_text for m in ("✓ Ready", "⚠ Warnings", "✗ Needs review"))
    # 图例链接与 Re-check all 就位
    assert "What do the colors mean?" in page.lbl_legend.text()
    page._recheck_all()
    assert "Re-checked" in window.statusBar().currentMessage()


def test_review_issues_hidden_when_clean(window, ref_record_seq, ref_gb_text, monkeypatch):
    """全绿时 Issues 区隐藏（不再撑一个大空框）；红灯时显示且点击跳转 feature 行。"""
    from PyQt6.QtWidgets import QInputDialog

    from fungal_annot.core.models import Issue, SeqInput
    from fungal_annot.services.pipeline import SeqResult, Provenance, annotate_sequence

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="g1", seq=seq[300:1600], gene_type="tef1",
                                 source_qualifiers={"organism": "F. t", "country": "China"}))
    res = annotate_sequence(window.sequences[0], window.make_config(),
                            reference_gb_text=ref_gb_text)
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("", True)))
    if res.status != "green":
        window.confirmed["g1"] = True
    window.results["g1"] = res
    page = window.page_review
    page.refresh()
    page.current = "g1"
    page.load_result("g1")

    # 构造红灯：加一条 error issue → Issues 区可见
    res.issues = [Issue("error", "cds_phase", "CDS is not marked partial at the 3' end")]
    res.status = "red"
    page.load_result("g1")
    assert page.lbl_issues.isVisibleTo(page) and page.issue_list.isVisibleTo(page)
    assert any("Error:" in page.issue_list.item(i).text()
               for i in range(page.issue_list.count()))
    # 点击 issue → 跳到 CDS 行
    page._on_issue_clicked(page.issue_list.item(0))
    selected = {i.row() for i in page.feature_table.selectedIndexes()}
    types = {page.feature_table.item(r, 0).text() for r in selected}
    assert "CDS" in types

    # 回到全绿 → Issues 区隐藏
    res.issues = []
    res.status = "green"
    page.load_result("g1")
    assert not page.lbl_issues.isVisibleTo(page)
    assert not page.issue_list.isVisibleTo(page)
