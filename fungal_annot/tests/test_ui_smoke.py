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
    """原图标工具栏（New/Open/Save/Settings/Log）改为文字菜单栏；
    后精简为 Settings / Guide / About 三个直接动作，无子菜单、无快捷键
    （软件不设快捷键；更新检查入口在 About 弹窗内，不单列菜单项）。"""
    from PyQt6.QtWidgets import QToolBar

    assert window.findChildren(QToolBar) == []
    actions = window.menuBar().actions()
    assert [a.text() for a in actions] == ["Settings", "Guide", "About"]
    assert all(a.menu() is None for a in actions)          # 直接动作，无下拉
    assert all(a.shortcut().toString() == "" for a in actions)   # 不注册快捷键


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
    assert "no sequences" in window.nav.item(1).toolTip()   # 锁定原因悬停可见

    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 100, gene_type="tef1"))
    window.go_page(0)
    assert window._step_states()[0] is False            # 有序列但无 hits
    assert window._step_locked(1)[0]                    # Reference 仍锁
    assert "BLAST hits" in window.nav.item(1).toolTip() # 原因随状态细化

    window.hits["s1"] = [BlastHit(accession="AA000001", title="hit", pident=99.0,
                                  qcovs=100.0, subject_len=100, flags={})]
    assert window._step_states()[0] is True
    assert not window._step_locked(1)[0]                # Reference 解锁
    assert window._step_locked(2)[0]                    # Review 仍锁（未注释）
    window._refresh_nav()
    assert window.nav.item(1).toolTip() == ""           # 解锁后提示清空
    assert "annotation" in window.nav.item(2).toolTip()

    window.results["s1"] = {"REF00001.1": SimpleNamespace(status="red")}
    window._refresh_nav()
    assert not window._step_locked(3)[0]                # 红灯不再锁 Export（确认挪到导出弹窗）
    assert "reviewed" not in window.nav.item(3).toolTip()
    window.confirmed["s1"] = True
    assert not window._step_locked(3)[0]                # 仍解锁（confirmed 在导出时使用）
    window._refresh_nav()
    assert window.nav.item(3).toolTip() == ""

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
    window._on_blast_failed(0, "s1", "", "boom")     # gen 0 == 当前批次
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
    window._on_blast_finished(0, "s1", "", [hit])
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
    window._on_blast_finished(0, "s1", "", [BlastHit(accession="AA000001", title="hit",
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
    window.results["u1"] = {"REF00001.1": res}

    page = window.page_review
    page.refresh()
    page.load_result("u1")
    features = page.feature_table.to_features()
    assert [f.ftype for f in features] == ["gene", "CDS"]
    # P4 编辑重验：不加改动重验，状态应保持
    page.current = "u1"
    page._auto_revalidate()
    assert window.results["u1"]["REF00001.1"].status == res.status


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
    window.results["u2"] = {"REF00001.1": res}
    page = window.page_review
    page.refresh()
    page.current = "u2"
    page.load_result("u2")

    # 编辑：CDS 坐标改到超出序列长度
    row = next(r for r in range(page.feature_table.rowCount())
               if page.feature_table.item(r, 0).text() == "CDS")
    page.feature_table.item(row, 2).setText("1..300, 401..99999")
    page._auto_revalidate()
    assert window.results["u2"]["REF00001.1"].status == "red"
    assert any(i.code == "coord_out_of_range"
               for i in window.results["u2"]["REF00001.1"].issues)


def test_project_save_load_roundtrip(window, tmp_path, ref_record_seq, ref_gb_text):
    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence
    from fungal_annot.services.project_store import load_project, save_project

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="p1", seq=seq[300:1600], gene_type="tef1",
                                 source_qualifiers={"organism": "F. t"}))
    res = annotate_sequence(window.sequences[0], window.make_config(),
                            reference_gb_text=ref_gb_text)
    window.results["p1"] = {"REF00001.1": res}
    window.confirmed["p1"] = True       # 红灯确认与导出标记必须跨会话保留
    window.exported = True
    path = str(tmp_path / "proj.json")
    save_project(path, window.sequences, window.hits, window.selected_refs,
                 window.results, window.settings,
                 confirmed=window.confirmed, exported=window.exported)
    (sequences, hits, selected_refs, results, settings,
     confirmed, exported, chosen_ref) = load_project(path)
    assert [s.seq_id for s in sequences] == ["p1"]
    assert chosen_ref == {"p1": "REF00001.1"}
    assert results["p1"]["REF00001.1"].status == res.status
    assert results["p1"]["REF00001.1"].tbl_text == res.tbl_text
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
    window.results["a"] = {"REF00001.1": res}
    window.page_review.current = "a"
    text = window.page_review._reference_features_text()
    assert text is not None
    assert text.startswith(">Feature REF00001.1")
    # join 的后续区段行不带 feature key（NCBI feature_table 规范）
    assert "201\t600\tCDS" in text and "701\t1149" in text and "701\t1149\tCDS" not in text
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
    assert window.page_import.b_blast.isEnabled()

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
    assert [b.text() for b in buttons] == ["BLAST", "Browse", "Example", "Clear",
                                           "STOP", "Help"]
    assert buttons[0].objectName() == "PrimaryButton"      # BLAST 主行动
    assert all(b.objectName() == "" for b in buttons[1:])  # 其余默认描边
    actions = buttons[:5]                                  # 五个动作按钮等宽（Help 除外）
    widths = {(b.minimumWidth(), b.maximumWidth()) for b in actions}
    assert len(widths) == 1 and actions[0].minimumWidth() == actions[0].maximumWidth()
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
    save_project(path, [s], {}, {}, {"u4": {"REF00001.1": res}}, {})
    (sequences, _hits, _sel, results, _st,
     _confirmed, _exported, _chosen) = load_project(path)

    lite = results["u4"]["REF00001.1"]
    assert [f.ftype for f in lite.features] == ["gene", "CDS"]  # feature 已恢复
    assert set(lite.report_row()) == set(res.report_row())                # 报告行同构
    assert lite.report_row()["n_features"] == 2
    written = write_outputs([lite], str(tmp_path / "out"), sequences)
    assert any(w.endswith("u4.tbl") for w in written)
    # 门户模式：.tbl 不含 source，输出与注释时的 tbl_text 一致
    out_tbl = (tmp_path / "out" / "u4.tbl").read_text(encoding="utf-8")
    assert "\tsource" not in out_tbl and "CDS" in out_tbl
    assert out_tbl == res.tbl_text


def test_hit_table_title_tooltip_wrapped(qtbot):
    """回归：Title 列 tooltip 必须折行——GenBank 定义行可达数百字符，单行 tooltip
    会横跨屏幕；且推荐行不得覆盖标题全文（两者需合并）。"""
    from fungal_annot.core.blast_runner import BlastHit
    from fungal_annot.ui.widgets import hit_table as ht

    long_title = ("Fusarium oxysporum f. sp. lycopersici strain Fol4287 chromosome 1, "
                  "complete sequence, whole genome shotgun sequence") * 2
    table = ht.HitTable()
    qtbot.addWidget(table)
    table.populate([BlastHit(accession="NC_000001.1", title=long_title, pident=99.0,
                             qcovs=100.0, subject_len=1000, flags={}),
                    BlastHit(accession="AA000002", title="short title", pident=98.0,
                             qcovs=100.0, subject_len=1000, flags={})],
                   query_len=900)
    tip = table.item(0, 1).toolTip()
    assert "\n" in tip                                        # 已折行
    assert max(len(line) for line in tip.splitlines()) <= 78  # 宽度受控
    table.mark_recommended(0)
    merged = table.item(0, 1).toolTip()
    assert "Recommended" in merged and long_title[:40] in merged   # 合并而非覆盖
    table.mark_recommended(0)                                 # 重复调用幂等
    assert table.item(0, 1).toolTip().count("Recommended") == 1
    assert table.item(1, 1).toolTip() == ""                   # 短标题不设冗余提示


def test_reference_row_multi_select_default_and_toggle(window):
    """多参考对比：命中表每行复选框，默认勾前 N（default_refs=3，命中 2 条 → 全选）；
    勾选即生效；至少保留 1 个。"""
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

    # 默认勾前 N（默认 3 > 命中数 2 → 全选，按排名序）
    assert window.selected_refs["r1"] == ["AA000001", "AA000002"]
    assert page.b_annotate.isEnabled()
    # 取消第二个 → 只剩第一个
    page.hit_table._checks[1].setChecked(False)
    assert window.selected_refs["r1"] == ["AA000001"]
    # 至少保留 1 个：取消最后一个被拒绝，勾选状态回滚
    page.hit_table._checks[0].setChecked(False)
    assert window.selected_refs["r1"] == ["AA000001"]
    assert page.hit_table._checks[0].isChecked()
    # 再勾上第二个 → 恢复两个
    page.hit_table._checks[1].setChecked(True)
    assert window.selected_refs["r1"] == ["AA000001", "AA000002"]
    # "Use recommended for all" 按钮已移除：默认勾选逻辑在 refresh() 中，兜底由
    # View match 清空回落承担（test_enter_accessions_applies_values 覆盖）


def test_reference_multi_select_limit_five(window):
    """上限 5：勾第 6 个被拒绝并回滚（日志提示），其余勾选不受影响。"""
    from fungal_annot.core.blast_runner import BlastHit
    from fungal_annot.core.models import SeqInput

    window.add_sequence(SeqInput(seq_id="r2", seq="ACGT" * 60, gene_type="tef1"))
    window.hits["r2"] = [BlastHit(accession=f"AB{i:06d}", title=f"hit {i}",
                                  pident=99.0, qcovs=100.0, subject_len=60, flags={})
                         for i in range(6)]
    page = window.page_reference
    page.refresh()
    page.seq_list.setCurrentRow(0)
    assert window.selected_refs["r2"] == [f"AB{i:06d}" for i in range(3)]  # 默认前 3
    for i in range(3, 6):
        page.hit_table._checks[i].setChecked(True)
    assert window.selected_refs["r2"] == [f"AB{i:06d}" for i in range(5)]
    page.hit_table._checks[5].setChecked(True)      # 第 6 个 → 拒绝
    assert window.selected_refs["r2"] == [f"AB{i:06d}" for i in range(5)]
    assert not page.hit_table._checks[5].isChecked()  # 勾选回滚


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
    window.page_reference.refresh()          # 自动勾选前 N → selected_refs 就绪
    window.page_reference.seq_list.setCurrentRow(0)

    window.page_reference._start_annotate()  # 真实按钮处理器（含队列提交）
    assert window._annotate_pending == 1
    qtbot.waitUntil(lambda: "u1" in window.results, timeout=60000)
    qtbot.waitUntil(lambda: window._annotate_pending <= 0, timeout=60000)
    assert window.results["u1"]["REF00001.1"].status in ("green", "yellow")
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
    window.results["old"] = {"REF00001.1": SimpleNamespace(seq_id="old", status="green")}
    window.confirmed["old"] = True
    window.rename_sequence("old", "new")
    assert window.sequences[0].seq_id == "new"
    assert "new" in window.hits and "old" not in window.hits
    assert window.results["new"]["REF00001.1"].seq_id == "new"
    assert window.confirmed.get("new") is True


def test_review_auto_revalidate_on_edit(window, qtbot, ref_record_seq, ref_gb_text):
    """编辑坐标后防抖自动重验：无需点 Re-validate，红灯即时反映。"""
    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="u2", seq=seq[300:1600], gene_type="tef1",
                                 source_qualifiers={"organism": "F. t",
                                                    "country": "China"}))
    window.results["u2"] = {"REF00001.1": annotate_sequence(
        window.sequences[0], window.make_config(), reference_gb_text=ref_gb_text)}
    page = window.page_review
    page.refresh()
    page.current = "u2"
    page.load_result("u2")
    row = next(r for r in range(page.feature_table.rowCount())
               if page.feature_table.item(r, 0).text() == "CDS")
    page.feature_table.item(row, 2).setText("1..300, 401..99999")
    qtbot.waitUntil(lambda: window.results["u2"]["REF00001.1"].status == "red", timeout=5000)
    assert any(i.code == "coord_out_of_range" for i in window.results["u2"]["REF00001.1"].issues)

    # 非法坐标：状态栏提示（不弹窗）、上次结果保留
    page.feature_table.item(row, 2).setText("garbage")
    qtbot.waitUntil(lambda: window.statusBar().currentMessage().startswith("⚠"),
                    timeout=5000)
    assert window.results["u2"]["REF00001.1"].status == "red"


def test_feature_add_and_delete_row(window, qtbot, ref_record_seq, ref_gb_text):
    """feature 行增删：source 行禁止删除（合成行验证守卫）；增删触发自动重验。"""
    from fungal_annot.core.models import Feature, FeaturePart, SeqInput
    from fungal_annot.services.pipeline import annotate_sequence

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="u3", seq=seq[300:1600], gene_type="tef1",
                                 source_qualifiers={"organism": "F. t",
                                                    "country": "China"}))
    window.results["u3"] = {"REF00001.1": annotate_sequence(
        window.sequences[0], window.make_config(), reference_gb_text=ref_gb_text)}
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


def test_issue_details_in_results_tooltip(window):
    """Issues 列表已并入结果列表：Issues 列悬停可见完整问题（级别 + 信息 + 建议）。"""
    from fungal_annot.core.models import Issue, Provenance, SeqInput
    from fungal_annot.services.pipeline import SeqResult

    window.add_sequence(SeqInput(seq_id="u4", seq="ACGT" * 100, gene_type="tef1"))
    res = SeqResult(seq_id="u4", status="red",
                    issues=[Issue("error", "low_identity", "identity 90% < threshold")],
                    provenance=Provenance())
    window.results["u4"] = {"REF00001.1": res}
    page = window.page_review
    page.refresh()
    page.current = "u4"
    page.load_result("u4")
    item = page.variant_table.item(0, 3)
    assert item.text().startswith("1")              # 计数 + 级别细分
    tip = item.toolTip()
    assert "Error: identity 90% < threshold" in tip
    assert "accept it knowingly" in tip or "closer" in tip   # HINTS 建议动作
    # 清空问题 → tooltip 为空
    res.issues = []
    res.status = "green"
    page.load_result("u4")
    assert page.variant_table.item(0, 3).toolTip() == ""


def test_accession_dialog_layout(window):
    """View match 弹窗：序列名只读、第二列预填当前选择、values() 含全部行。"""
    from PyQt6.QtCore import Qt

    from fungal_annot.core.models import SeqInput
    from fungal_annot.ui.pages.page_reference import AccessionDialog

    window.add_sequence(SeqInput(seq_id="d1", seq="ACGT" * 10))
    window.add_sequence(SeqInput(seq_id="d2", seq="ACGT" * 10))
    dlg = AccessionDialog(window.sequences, {"d2": ["MZ123456.1"]}, window)
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
    assert window.selected_refs["m2"] == ["AA000001"]       # refresh 自动取前 N 推荐

    class StubDialog:
        def __init__(self, sequences, current, parent=None):
            self.sequences, self.current = sequences, current
        def exec(self):
            return pr_mod.QDialog.DialogCode.Accepted
        def values(self):
            return {"m1": "MZ123456.1", "m2": ""}        # m2 清空 → 回落推荐
    monkeypatch.setattr(pr_mod, "AccessionDialog", StubDialog)
    page._enter_accessions()
    assert window.selected_refs["m1"] == ["MZ123456.1"]     # 手填覆盖
    assert window.selected_refs["m2"] == ["AA000001"]       # 清空 → 回落推荐

    # 取消（Rejected）→ 不应用
    class StubCancel(StubDialog):
        def exec(self):
            return pr_mod.QDialog.DialogCode.Rejected
    monkeypatch.setattr(pr_mod, "AccessionDialog", StubCancel)
    window.selected_refs["m1"] = ["AA000001"]
    page._enter_accessions()
    assert window.selected_refs["m1"] == ["AA000001"]


def test_review_status_wording_and_confirm(window, ref_record_seq, ref_gb_text):
    """Review 页不再有 Confirm 按钮（红灯确认挪到导出页弹窗），列表用新标记。"""
    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="w1", seq=seq[300:1600], gene_type="tef1",
                                 source_qualifiers={"organism": "F. t", "country": "China"}))
    window.results["w1"] = {"REF00001.1": annotate_sequence(
        window.sequences[0], window.make_config(), reference_gb_text=ref_gb_text)}
    page = window.page_review
    page.refresh()
    page.current = "w1"
    page.load_result("w1")
    # Confirm 按钮及其确认流程已移除：红灯序列在导出页导出弹窗里确认
    assert getattr(page, "b_confirm", None) is None
    assert not hasattr(page, "_manual_confirm")

    # 列表标记用新文案
    item_text = page.seq_list.item(0).text()
    assert any(m in item_text for m in ("✓ Ready", "⚠ Warnings", "✗ Needs review"))
    # Re-check all 已从界面移除，但重查逻辑保留（批量重验入口被测试直接调用）
    page._recheck_all()
    assert "Re-checked" in window.statusBar().currentMessage()



def test_export_page_writes_tbl_only(window, tmp_path, ref_record_seq, ref_gb_text, monkeypatch):
    """P5 导出只写 .tbl（每条序列一个 + 多记录汇总 all_features.tbl）：
    不再产生 .fsa 与验证报告 CSV。"""
    from PyQt6.QtWidgets import QMessageBox

    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="e1", seq=seq[300:1600], gene_type="tef1"))
    window.results["e1"] = {"REF00001.1": annotate_sequence(
        window.sequences[0], window.make_config(), reference_gb_text=ref_gb_text)}
    page = window.page_export
    page.refresh()
    out = tmp_path / "only_tbl"
    page.dir_edit.setText(str(out))
    # 屏蔽导出成功后的模态弹窗（离屏环境下 exec() 永远阻塞）
    shown = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(a[1] if len(a) > 1 else "")
                                     or QMessageBox.StandardButton.Ok))
    page._export()

    files = sorted(p.name for p in out.iterdir())
    assert files == ["all_features.tbl", "e1.tbl"], files
    content = (out / "e1.tbl").read_text(encoding="utf-8")
    assert content.startswith(">Feature e1") and "CDS" in content
    # 单序列：汇总文件与 per-seq .tbl 内容一致
    assert (out / "all_features.tbl").read_text(encoding="utf-8") == content
    assert shown and "Export done" in shown[0]


def test_export_confirms_red_sequences(window, tmp_path, ref_record_seq, ref_gb_text, monkeypatch):
    """红灯序列导出时弹知情确认（原 Review 页 Confirm 按钮的替代流程）：
    拒绝 → 不导出且不记 confirmed；同意 → 记 confirmed 并放行导出。"""
    from PyQt6.QtWidgets import QMessageBox

    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="r1", seq=seq[300:1600], gene_type="tef1",
                                 source_qualifiers={"organism": "F. t", "country": "China"}))
    window.results["r1"] = {"REF00001.1": annotate_sequence(
        window.sequences[0], window.make_config(), reference_gb_text=ref_gb_text)}
    window.results["r1"]["REF00001.1"].status = "red"   # 强制红灯走确认分支
    page = window.page_export
    page.refresh()
    out = tmp_path / "red_confirm"
    page.dir_edit.setText(str(out))

    questions = []

    def fake_question(*a, **k):
        questions.append(a[2] if len(a) > 2 else "")
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    page._export()
    assert not out.exists() and window.confirmed.get("r1") is None
    assert questions and "r1" in questions[0]

    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    page._export()
    assert window.confirmed["r1"] is True
    assert (out / "r1.tbl").exists()


def test_recheck_preserves_pipeline_issues(window, ref_record_seq, ref_gb_text):
    """重验只替换 validate() 的输出：管线早期/迁移期提示（base_issues）不得丢失，
    否则初次注释的 warning 在 Re-check all / 自动重验后凭空消失、黄变绿。"""
    from fungal_annot.core.models import Issue, SeqInput
    from fungal_annot.services.pipeline import annotate_sequence

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="b1", seq=seq[300:1600], gene_type="tef1",
                                 source_qualifiers={"organism": "F. t", "country": "China"}))
    res = annotate_sequence(window.sequences[0], window.make_config(),
                            reference_gb_text=ref_gb_text)
    window.results["b1"] = {"REF00001.1": res}
    # 模拟迁移期 warning（正常由 transfer_features 产生并进入 base_issues）
    transfer_issue = Issue("warning", "exon_outside_aligned",
                           "CDS: 1 segment(s) outside the query-covered region")
    res.detail.base_issues = list(res.detail.base_issues) + [transfer_issue]
    res.issues = list(res.detail.base_issues) + list(res.issues)
    res.status = "yellow"

    page = window.page_review
    page.refresh()
    page.current = "b1"
    page.load_result("b1")
    page._recheck_all()
    codes = {i.code for i in window.results["b1"]["REF00001.1"].issues}
    assert "exon_outside_aligned" in codes            # 重查后仍在
    assert window.results["b1"]["REF00001.1"].status == "yellow"    # 不会黄变绿

    # 自动重验（编辑路径）同样保留
    page.feature_table.item(0, 3).setText(page.feature_table.item(0, 3).text() + " ")
    page._auto_revalidate()
    codes = {i.code for i in window.results["b1"]["REF00001.1"].issues}
    assert "exon_outside_aligned" in codes


def test_page_help_buttons_and_guides(window):
    """四页按钮区各有一个 Help 按钮；PAGE_HELP 四篇指南可构建富文本弹窗。"""
    from PyQt6.QtWidgets import QPushButton

    from fungal_annot.ui.pages.page_export import PageExport as _PE
    from fungal_annot.ui.pages.page_import import PageImport as _PI
    from fungal_annot.ui.pages.page_reference import PageReference as _PR
    from fungal_annot.ui.pages.page_review import PageReview as _PV
    from fungal_annot.ui.widgets.help import PAGE_HELP, build_page_help_dialog

    assert set(PAGE_HELP) == {"page_import", "page_reference",
                              "page_review", "page_export"}
    for page, term in ((window.page_import, "page_import"),
                       (window.page_reference, "page_reference"),
                       (window.page_review, "page_review"),
                       (window.page_export, "page_export")):
        helps = [b for b in page.findChildren(QPushButton) if b.text() == "Help"]
        assert len(helps) == 1, (type(page).__name__, helps)
    # 每篇指南含三段结构与关键内容，弹窗可构建
    dlg = build_page_help_dialog("page_import", window)
    assert dlg.windowTitle() == "How to use: Import & BLAST"
    for term, must_have in (("page_import", "BLAST"),
                            ("page_reference", "Use"),
                            ("page_review", "Needs review"),
                            ("page_export", "BankIt")):
        html = PAGE_HELP[term][1]
        assert "How to use" in html and "Terms" in html and "Tips" in html
        assert must_have in html


def test_app_guide_term_and_about_dialogs(window, qtbot):
    """菜单 Guide 是全软件使用指南（非单页）：四步流程、设置、状态规则、
    提交路径齐备且不含快捷键说明；术语词条与 About 弹窗均可构建
    （About 为原生控件 widgets/about.py，不走 HTML 外壳）。"""
    from PyQt6.QtWidgets import QDialog, QLabel

    from fungal_annot.paths import resource_path
    from fungal_annot.ui.widgets.about import build_about_dialog
    from fungal_annot.ui.widgets.help import (APP_GUIDE, build_app_guide_dialog,
                                              build_term_help_dialog)

    dlg = build_app_guide_dialog(window)
    assert dlg.windowTitle() == "User Guide"
    body = APP_GUIDE[1]
    for must in ("Import", "Select Reference", "Review Annotation",
                 "Export Results", "BankIt", "Ready"):
        assert must in body, must
    for banned in ("F1", "Ctrl+,", "shortcut", "Shortcut"):
        assert banned not in body, banned            # 软件不设快捷键，文案同步
    # 术语词条也能构建
    assert build_term_help_dialog("codon_start", window).windowTitle() == "codon_start"

    # About：原生控件弹窗——标题/版本 objectName 有对应 qss 规则，版本号可见
    about = build_about_dialog("9.9.9", window)
    qtbot.addWidget(about)
    assert isinstance(about, QDialog) and about.windowTitle() == "About"
    title = about.findChild(QLabel, "AboutTitle")
    ver = about.findChild(QLabel, "AboutVersion")
    assert title is not None and title.text() == "MycoFACT"
    assert ver is not None and "9.9.9" in ver.text()
    qss = open(resource_path("fungal_annot", "resources", "style.qss"),
               encoding="utf-8").read()
    for sel in ("QLabel#AboutTitle", "QLabel#AboutVersion"):
        assert sel in qss, sel


def test_about_dialog_update_flow(window, qtbot, monkeypatch):
    """About 更新检查两条路径 + 失败路径：有新版 → 弹 UpdateAvailableDialog
    （stub 掉 exec 防阻塞）；已最新 → 就地提示；异常 → QMessageBox 警告。"""
    from PyQt6.QtWidgets import QMessageBox

    from fungal_annot.core import updater
    from fungal_annot.ui.widgets.about import AboutDialog

    dlg = AboutDialog("0.1.0", window)
    qtbot.addWidget(dlg)

    shown = []

    class _StubUpdate:
        def __init__(self, *a, **k):
            shown.append(self)
            self.execed = False

        def exec(self):
            self.execed = True

    monkeypatch.setattr("fungal_annot.ui.widgets.about.UpdateAvailableDialog",
                        _StubUpdate)

    # 有新版本：后台线程返回 info → 弹出 UpdateAvailableDialog，按钮恢复可用
    info = {"version": "0.2.0", "url": "https://example.com/rel",
            "name": "v0.2.0", "published_at": "", "notes": "- fix a\n- add b"}
    monkeypatch.setattr(updater, "check_for_update", lambda v, **kw: info)
    dlg.check_updates()
    qtbot.waitUntil(lambda: bool(shown) and shown[0].execed
                    and dlg.b_check.isEnabled())
    assert dlg.update_status.text() == ""

    # 已最新：就地提示，不弹任何窗
    monkeypatch.setattr(updater, "check_for_update", lambda v, **kw: None)
    dlg.check_updates()
    qtbot.waitUntil(lambda: dlg.b_check.isEnabled()
                    and "up to date" in dlg.update_status.text())
    assert len(shown) == 1

    # 失败：QMessageBox 警告（stub 掉静态方法），按钮恢复可用
    warned = []

    def _fake_warning(*a, **k):
        warned.append(True)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(_fake_warning))
    monkeypatch.setattr(updater, "check_for_update",
                        lambda v, **kw: (_ for _ in ()).throw(
                            updater.UpdateCheckError("offline")))
    dlg.check_updates()
    qtbot.waitUntil(lambda: dlg.b_check.isEnabled() and bool(warned))


# ---- 队列生命周期修复回归（2026-09-29：STOP 取消 / 失败对称 / 项目切换作废）----

def test_stop_cancels_remaining_blast_tasks(qtbot, window, monkeypatch):
    """STOP：进行中的一条做完后，其余任务在 run() 入口被跳过（skipped），
    pending 排空、STOP 复位——此前 cancel 标志无人读取，STOP 完全无效。"""
    import threading

    from fungal_annot.core.models import SeqInput

    entered = threading.Event()
    release = threading.Event()

    def fake_run_blast(seq, **kw):
        entered.set()
        release.wait(10)        # 模拟阻塞中的在线 BLAST（进行中无法中断）
        return []
    monkeypatch.setattr("fungal_annot.services.worker.run_blast", fake_run_blast)

    window.settings["email"] = "a@example.org"
    window.blast_queue.set_max_threads(1)   # 本测试验证 STOP 的跳过语义，
    for i in range(3):                      # 固定串行（默认并发池为 3，跳过时机不同）
        window.add_sequence(SeqInput(seq_id=f"c{i}", seq="ACGT" * 20, gene_type="tef1"))
    window.page_import.refresh()
    window.page_import._start()
    assert window._blast_pending == 3
    qtbot.waitUntil(entered.is_set, timeout=5000)   # 第一条已进入（阻塞中的）BLAST
    window.page_import._cancel()                    # STOP
    release.set()                                   # 放行进行中的那条
    qtbot.waitUntil(lambda: window._blast_pending <= 0, timeout=10000)
    assert window._blast_pending == 0
    assert not window.page_import.b_stop.isEnabled()
    assert "c0" in window.hits                      # 进行中的那条正常返回
    assert "c1" not in window.hits and "c2" not in window.hits   # 其余被跳过


def test_annotate_failure_drains_queue(window):
    """注释 worker 失败同样消耗 pending（成功/失败路径对称，此前失败分支
    要求序列仍存在才递减，删除序列 + 失败会让界面永久卡死）。"""
    window.page_reference.progress.setMaximum(1)
    window._annotate_pending = 1
    window._on_annotate_failed(0, "s1", "REF00001.1", "boom")
    assert window._annotate_pending == 0


def test_start_annotate_disabled_while_queue_running(window):
    """注释队列运行中 refresh() 不得重新点亮 Start Annotation（防双重提交，
    与第 1 页 test_start_blast_disabled_while_queue_running 对称）。"""
    from fungal_annot.core.blast_runner import BlastHit
    from fungal_annot.core.models import SeqInput

    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 60, gene_type="tef1"))
    window.hits["s1"] = [BlastHit(accession="AA000001", title="hit", pident=99.0,
                                  qcovs=100.0, subject_len=60, flags={})]
    window._annotate_pending = 1
    window.page_reference.refresh()
    assert not window.page_reference.b_annotate.isEnabled()
    window._annotate_pending = 0
    window.page_reference.refresh()
    assert window.page_reference.b_annotate.isEnabled()


def test_abandon_queues_ignores_late_callbacks(window):
    """项目丢弃（New/Open/Clear 公共路径）后在途回调按代次号作废：
    迟到的 finished 不写陈旧命中、不消耗计数、不触发跳页。"""
    from fungal_annot.core.blast_runner import BlastHit
    from fungal_annot.core.models import SeqInput

    window.add_sequence(SeqInput(seq_id="s1", seq="ACGT" * 60, gene_type="tef1"))
    window.page_import.progress.setMaximum(1)
    window._blast_pending = 1
    window._abandon_queues()
    assert window._blast_pending == 0
    stale_gen = window.blast_queue.gen - 1
    window._on_blast_finished(stale_gen, "s1", "",
                              [BlastHit(accession="AA000001", title="hit", pident=99.0,
                                        qcovs=100.0, subject_len=60, flags={})])
    assert "s1" not in window.hits
    assert window._blast_pending == 0
    assert window.stack.currentIndex() == 0


def test_late_annotate_result_for_removed_sequence_dropped(window, ref_record_seq,
                                                           ref_gb_text):
    """回归：注释运行中删除序列后，迟到的结果不得写入 results——否则导出页
    会为界面上已不存在的序列写出 .tbl（幽灵文件）。"""
    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import annotate_sequence

    seq, _ = ref_record_seq
    s = SeqInput(seq_id="u9", seq=seq[300:1600], gene_type="tef1")
    window.add_sequence(s)
    res = annotate_sequence(s, window.make_config(), reference_gb_text=ref_gb_text)
    window.page_reference.progress.setMaximum(1)
    window._annotate_pending = 1
    window.sequences.clear()               # 模拟注释运行中删除该序列
    window._on_annotate_finished(0, "u9", "REF00001.1", res)
    assert "u9" not in window.results
    assert window._annotate_pending == 0


def test_rename_blocked_while_queue_running(window, monkeypatch):
    """队列运行中禁止改名：worker 结果按提交时的 seq_id 返回，改名会让它找不到归宿。"""
    from PyQt6.QtWidgets import QMessageBox

    from fungal_annot.core.models import SeqInput

    window.add_sequence(SeqInput(seq_id="rn1", seq="ACGT" * 10, gene_type="tef1"))
    window.page_import.refresh()
    window._annotate_pending = 1
    warned = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **k: warned.append(k.get("text", a[2] if len(a) > 2 else ""))
                     or QMessageBox.StandardButton.Ok))
    page = window.page_import
    page.seq_table.item(0, 0).setText("rn2")       # itemChanged → 守卫 → 拒绝
    assert window.sequences[0].seq_id == "rn1"     # 未改名
    assert warned and "renaming" in warned[0]      # 弹窗提示等待队列
    assert page.seq_table.item(0, 0).text() == "rn1"   # 单元格回滚


def test_review_refresh_preserves_selection(window):
    """回归：refresh 后选中停在原序列——此前 clear() 之后才读 currentRow（恒 -1），
    Re-check all / 确认导出 / 切页后浏览位置都会跳回第 1 条。"""
    from fungal_annot.core.models import SeqInput

    for sid in ("rv1", "rv2", "rv3"):
        window.add_sequence(SeqInput(seq_id=sid, seq="ACGT" * 30, gene_type="tef1"))
    page = window.page_review
    page.refresh()
    page.seq_list.setCurrentRow(2)
    assert page.current == "rv3"
    page.refresh()                                  # Re-check all / 确认后都会走这里
    assert page.seq_list.currentRow() == 2
    assert page.current == "rv3"


# ---- 多参考对比（2026-09-29）：1-5 参考 → 对比 → 采纳其一 → 导出 ----

def test_multi_reference_compare_adopt_and_export(qtbot, window, tmp_path,
                                                  ref_record_seq, ref_gb_text,
                                                  monkeypatch):
    """端到端：同一序列对两个参考各注释一次 → 对比表两行 → 采纳第二个 →
    导出只写采纳者（m1.tbl）+ 多记录汇总。"""
    from PyQt6.QtWidgets import QMessageBox

    from fungal_annot.core.models import SeqInput

    seq, _ = ref_record_seq
    window.add_sequence(SeqInput(seq_id="m1", seq=seq[300:1600], gene_type="tef1",
                                 source_qualifiers={"organism": "F. t",
                                                    "country": "China"}))
    window.selected_refs["m1"] = ["REF00001.1", "REF00002.1"]
    # 两个参考都必须覆盖整条查询，否则注释直接失败（比对裁端 → 红、空表）。
    # 因此第二参考用同源记录改 accession，而非 partial_ref_gb（背景与查询不同源）。
    alt_gb_text = ref_gb_text.replace("REF00001", "REF00002")
    refs = {"REF00001.1": ref_gb_text, "REF00002.1": alt_gb_text}
    monkeypatch.setattr("fungal_annot.services.pipeline.fetch_gb_text",
                        lambda accession, **kw: (refs[accession], "full"))

    window.start_annotation()                        # （序列 × 参考）成对提交
    assert window._annotate_pending == 2
    qtbot.waitUntil(lambda: window._annotate_pending <= 0, timeout=60000)
    variants = window.results["m1"]
    assert set(variants) == {"REF00001.1", "REF00002.1"}
    assert all(v.tbl_text for v in variants.values())   # 两个参考都注释成功
    assert window.chosen_accession("m1") in variants  # 首个返回者默认采纳

    page = window.page_review
    page.refresh()
    page.seq_list.setCurrentRow(0)
    assert page.variant_table.rowCount() == 2         # 对比表每个参考一行
    # 采纳另一个 variant（Adopt）
    other = "REF00002.1" if window.chosen_accession("m1") == "REF00001.1" else "REF00001.1"
    page._adopt(other)
    assert window.chosen_accession("m1") == other
    assert page.variant_table.cellWidget(
        next(r for r in range(page.variant_table.rowCount())
             if page.variant_table.item(r, 0).text() == other), 4).isChecked()

    # 导出：默认只写采纳者（文件名仍为 <seq_id>.tbl，BankIt 就绪）+ 汇总文件
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    window.confirmed["m1"] = True                     # 绕开红灯拦截（若有）
    page_export = window.page_export
    page_export.refresh()
    out = tmp_path / "out"
    page_export.dir_edit.setText(str(out))
    page_export._export()
    assert sorted(p.name for p in out.iterdir()) == ["all_features.tbl", "m1.tbl"]
    # 导出的是采纳的 variant；汇总只含采纳者（单序列时与 m1.tbl 内容一致）
    exported = (out / "m1.tbl").read_text(encoding="utf-8")
    assert exported == variants[window.chosen_accession("m1")].tbl_text
    assert (out / "all_features.tbl").read_text(encoding="utf-8") == exported
    assert window.exported is True


def test_review_inline_issues_hint(window):
    """审核页行内问题提示：error/warning 直接可见并附建议动作（点破移码），绿灯隐藏。"""
    from fungal_annot.core.models import Issue, SeqInput
    from fungal_annot.services.pipeline import SeqResult

    window.add_sequence(SeqInput(seq_id="vis1", seq="ACGT" * 30, gene_type="tef1"))
    res = SeqResult(seq_id="vis1", status="red",
                    issues=[Issue("error", "internal_stop",
                                  "CDS translation contains an internal stop codon")])
    window.results["vis1"] = {"REF00001.1": res}
    window.chosen_ref["vis1"] = "REF00001.1"
    page = window.page_review
    page.refresh()
    assert not page.lbl_issues.isHidden()
    assert "internal stop" in page.lbl_issues.text()
    assert "frameshift" in page.lbl_issues.text()          # 建议动作点破移码原因

    window.results["vis1"] = {"REF00001.1": SeqResult(seq_id="vis1", status="green")}
    page.load_result("vis1")
    assert page.lbl_issues.isHidden()                      # 绿灯不显示提示


def test_annotate_pair_accounting(window):
    """1 条序列 × 2 个参考：pending 按 pair 计数，结果分别按 ref_key 落账。"""
    from fungal_annot.core.models import SeqInput
    from fungal_annot.services.pipeline import SeqResult

    window.add_sequence(SeqInput(seq_id="p2", seq="ACGT" * 30, gene_type="tef1"))
    window.selected_refs["p2"] = ["REF00001.1", "REF00002.1"]
    window.page_reference.progress.setMaximum(2)
    window._annotate_pending = 2                     # 手动置为在途（同既有测试做法）
    window._on_annotate_finished(0, "p2", "REF00001.1", SeqResult(seq_id="p2"))
    assert window._annotate_pending == 1
    assert set(window.results["p2"]) == {"REF00001.1"}
    window._on_annotate_finished(0, "p2", "REF00002.1",
                                 SeqResult(seq_id="p2", status="yellow"))
    assert window._annotate_pending == 0
    assert set(window.results["p2"]) == {"REF00001.1", "REF00002.1"}


def test_blast_queue_concurrency_setting(window):
    """Settings 项 blast_concurrency 驱动 BLAST 队列并发度：默认 3、夹取 1-4、
    保存设置后即时生效（set_max_threads）。"""
    assert window.blast_queue._pool.maxThreadCount() == 3      # 默认并发 3

    window.blast_queue.set_max_threads(2)
    assert window.blast_queue._pool.maxThreadCount() == 2

    window.settings["blast_concurrency"] = "9"
    assert window._blast_concurrency() == 4                    # 上限夹取
    window.settings["blast_concurrency"] = "0"
    assert window._blast_concurrency() == 1                    # 下限夹取
    window.settings["blast_concurrency"] = "garbage"
    assert window._blast_concurrency() == 3                    # 非法值回默认

    window.settings["blast_concurrency"] = "4"
    # 模拟 _open_settings 保存后的生效路径（不弹对话框）
    window.blast_queue.set_max_threads(window._blast_concurrency())
    assert window.blast_queue._pool.maxThreadCount() == 4
