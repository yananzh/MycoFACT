"""P4 注释审核页（§7.2，核心交互页）：状态用动作化文案表达（Ready / Ready · review
warnings / Needs review），计数条附图例链接与 Re-check all；feature 表格支持增删行、
编辑后 600ms 防抖自动重验（无比对上下文的项目加载态禁编辑并给行内提示）；Issues 列表
带修复建议，点击展开术语卡并跳转相关 feature 行；红灯序列需 Confirm 后才能导出。"""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QTextCursor
from PyQt6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QMessageBox, QPlainTextEdit,
                             QPushButton, QVBoxLayout, QWidget)

from ...core.tbl_writer import write_tbl
from ...core.validator import status_of, validate
from ..widgets.feature_table import FeatureTable
from ..widgets.help import (STATUS_COLOR as _STATUS_COLOR,
                            STATUS_HINT as _STATUS_LABEL,
                            STATUS_MARK as _STATUS_MARK, show_help)
_SEVERITY = {"error": ("⛔ ", QColor("#cf222e")),
             "warning": ("⚠ ", QColor("#9a6700")),
             "info": ("ℹ ", QColor("#57606a"))}

# 已知问题 → 一句建议动作（§11：验证报告用自然语言解释）
HINTS = {
    "internal_stop": "Check the transl table (reference qualifier vs preset). A wrong "
                     "table can create false stop codons.",
    "exon_outside_aligned": "Normal for partial amplicons - your query simply does not "
                            "cover the whole gene. No action needed.",
    "exon_map_fail": "A reference exon has no counterpart in your sequence (indel/gap). "
                     "Review the affected segment manually.",
    "low_identity": "The reference may be too distant - pick a closer one in step 2, "
                    "or accept it knowingly.",
    "modifier_missing": "Fill the missing source qualifiers on the Import page "
                        "(batch apply) or edit the source row here.",
    "modifier_format": "Fix the format in the source row (see NCBI qualifier rules: "
                       "country, collection_date, lat_lon).",
    "country_unverified": "Check spelling against the official NCBI country list.",
    "seqid_invalid": "Rename the sequence on the Import page "
                     "(double-click its Seq ID in the sequence list).",
    "n_boundary": "Trim or resolve ambiguous N bases around the boundary before submission.",
    "transl_table_conflict": "Pick the intended genetic code for this CDS after checking "
                             "the reference record.",
    "no_start_codon": "Verify the 5' end is genuinely partial; otherwise the reference "
                      "annotation may be wrong.",
    "no_stop_codon": "Verify the 3' end is genuinely partial; otherwise the reference "
                     "annotation may be wrong.",
    "cds_phase": "Mark the 3' end partial, or check exon boundaries.",
    "protein_identity": "Protein differs a lot from the reference - it may be misannotated "
                        "or from a distant species.",
}

# issue code → 术语卡词条：点击该条 issue 直接展开解释
_ISSUE_HELP = {
    "internal_stop": "transl_table",
    "transl_table_conflict": "transl_table",
    "low_identity": "identity",
}

# issue code → 受影响的 feature 类型：点击 issue 跳转到表格中对应行
_ISSUE_ROW_TYPE = {
    "internal_stop": "CDS", "no_start_codon": "CDS", "no_stop_codon": "CDS",
    "cds_phase": "CDS", "protein_identity": "CDS", "transl_table_conflict": "CDS",
    "n_boundary": "CDS", "low_identity": "CDS",
    "modifier_missing": "source", "modifier_format": "source",
    "country_unverified": "source",
    "seqid_invalid": "gene",
}


def _alignment_text(mapping, ref_seq, width: int = 60) -> str:
    """参考 vs 查询（RC 空间）逐列比对文本。

    列坐标逐列跟踪：行首标签为该行第一个有坐标列的真实参考/查询坐标；
    仅渲染对齐区间（端部侧翼不显示，内部 indel 完整展示）。
    三行前缀宽度一致（11 列），'|' 与碱基逐列对齐。
    """
    r_chars, q_chars, m_chars = [], [], []
    r_coord, q_coord = [], []          # 每列的参考/查询坐标（gap 列为 None）
    prev_re = prev_qe = None
    for (rs, re_, qs, qe) in mapping.blocks:
        if prev_re is not None:
            gref = rs - prev_re - 1            # 查询侧缺失（deletion）
            gq = qs - prev_qe - 1              # 查询侧插入（insertion）
            w = max(gref, gq)
            rseg = ref_seq[prev_re:rs - 1]
            qseg = mapping.query_seq[prev_qe:qs - 1]
            for j in range(w):
                r_have = j < gref
                q_have = j >= (w - gq)
                r_chars.append(rseg[j] if r_have else "-")
                q_chars.append(qseg[j - (w - gq)] if q_have else "-")
                m_chars.append(" ")
                r_coord.append(prev_re + 1 + j if r_have else None)
                q_coord.append(prev_qe + 1 + (j - (w - gq)) if q_have else None)
        for k in range(re_ - rs + 1):
            a = ref_seq[rs - 1 + k]
            b = mapping.query_seq[qs - 1 + k]
            r_chars.append(a)
            q_chars.append(b)
            m_chars.append("|" if a == b else " ")
            r_coord.append(rs + k)
            q_coord.append(qs + k)
        prev_re, prev_qe = re_, qe

    total = len(r_chars)
    out = []
    for i in range(0, total, width):
        chunk = range(i, min(i + width, total))
        r_lab = next((str(r_coord[j]) for j in chunk if r_coord[j] is not None), "-")
        q_lab = next((str(q_coord[j]) for j in chunk if q_coord[j] is not None), "-")
        out.append(f"R {r_lab:>7}  {''.join(r_chars[i:i + width])}")
        out.append(f"{'':>9}  {''.join(m_chars[i:i + width])}")
        out.append(f"Q {q_lab:>7}  {''.join(q_chars[i:i + width])}")
        out.append("")
    head = ("Orientation: reverse complement (query shown on its RC strand)"
            if mapping.orientation == "reverse" else "Orientation: forward")
    return head + "  (| = match)\n\n" + "\n".join(out)


class AlignmentDialog(QDialog):
    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(960, 640)
        v = QVBoxLayout(self)
        view = QPlainTextEdit()
        view.setObjectName("MonoViewer")   # QSS 等宽字体规则的目标（setFont 会被全局 QSS 覆盖）
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        view.setPlainText(text)
        view.moveCursor(QTextCursor.MoveOperation.Start)
        v.addWidget(view)
        b = QPushButton("Close")
        b.clicked.connect(self.accept)
        v.addWidget(b)


class PageReview(QWidget):
    title = "3. Review Annotation"

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.current: str | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        # ---- 顶部计数条：总览 + 图例 + 全量重查 ----
        ribbon = QHBoxLayout()
        self.lbl_ribbon = QLabel("")
        self.lbl_ribbon.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_legend = QLabel('<a href="#legend">What do the colors mean?</a>')
        self.lbl_legend.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_legend.setToolTip("Explains Ready / Warnings / Needs review")
        self.lbl_legend.linkActivated.connect(lambda _: show_help("status_colors", self))
        self.b_recheck = QPushButton("Re-check all")
        self.b_recheck.setToolTip("Re-run validation on every annotated sequence with the "
                                  "current settings (e.g. after changing the identity "
                                  "threshold)")
        self.b_recheck.clicked.connect(self._recheck_all)
        self.b_next_issue = QPushButton("Next issue →")
        self.b_next_issue.setToolTip("Jump to the next sequence with warnings or errors")
        self.b_next_issue.clicked.connect(self._jump_next_issue)
        ribbon.addWidget(self.lbl_ribbon)
        ribbon.addStretch(1)
        ribbon.addWidget(self.lbl_legend)
        ribbon.addWidget(self.b_recheck)
        ribbon.addWidget(self.b_next_issue)
        outer.addLayout(ribbon)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Sequences"))
        self.seq_list = QListWidget()
        self.seq_list.setMaximumWidth(300)   # 名单列不挤占 feature 表格
        self.seq_list.currentRowChanged.connect(self._on_seq_selected)
        left.addWidget(self.seq_list, 1)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        self.feature_table = FeatureTable()
        self.feature_table.edited.connect(self._on_edited)
        right.addWidget(self.feature_table, 2)

        # ---- 单条工具栏：编辑类与查看类用分隔线分组 ----
        toolbar = QHBoxLayout()
        self.b_add_feat = QPushButton("Add feature")
        self.b_add_feat.setToolTip("Insert a new CDS row spanning the whole sequence, "
                                   "then edit the cells (type, coordinates, qualifiers)")
        self.b_add_feat.clicked.connect(self._add_feature)
        self.b_del_feat = QPushButton("Delete row")
        self.b_del_feat.setToolTip("Delete the selected feature row(s) "
                                   "(the source row cannot be deleted)")
        self.b_del_feat.clicked.connect(self._delete_feature)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        b_align = QPushButton("View alignment")
        b_align.setToolTip("Reference vs query alignment, with match marks and coordinates")
        b_align.clicked.connect(self._show_alignment)
        self.b_ref_feat = QPushButton("View reference features")
        self.b_ref_feat.setToolTip("Show the reference record's own five-column feature table")
        self.b_ref_feat.clicked.connect(self._show_reference_features)
        toolbar.addWidget(self.b_add_feat)
        toolbar.addWidget(self.b_del_feat)
        toolbar.addWidget(sep)
        toolbar.addWidget(b_align)
        toolbar.addWidget(self.b_ref_feat)
        toolbar.addStretch(1)
        right.addLayout(toolbar)

        self.lbl_issues = QLabel("Issues")
        right.addWidget(self.lbl_issues)
        self.issue_list = QListWidget()
        self.issue_list.itemClicked.connect(self._on_issue_clicked)
        right.addWidget(self.issue_list, 1)
        body.addLayout(right, 3)
        outer.addLayout(body, 1)

        # 项目加载态提示（无比对上下文 → 禁编辑，替代原 Re-validate 弹窗）
        self.lbl_project_hint = QLabel(
            "Loaded from a project file - editing is disabled because the alignment "
            "context is not stored in the project. Re-annotate in step 2 to restore it.")
        self.lbl_project_hint.setObjectName("Hint")
        self.lbl_project_hint.setWordWrap(True)
        self.lbl_project_hint.setVisible(False)
        outer.addWidget(self.lbl_project_hint)

        # ---- 底部状态条：状态文案 + 上下文动作（Confirm 随状态可用）----
        strip = QHBoxLayout()
        self.lbl_status = QLabel("-")
        self.lbl_status.setWordWrap(True)
        strip.addWidget(self.lbl_status, 1)
        self.b_confirm = QPushButton("Confirm for export")
        self.b_confirm.setToolTip("Record that you reviewed this sequence knowingly "
                                  "(optional note kept in the log). Required for red "
                                  "sequences before export.")
        self.b_confirm.clicked.connect(self._manual_confirm)
        self.b_confirm.setEnabled(False)
        strip.addWidget(self.b_confirm)
        outer.addLayout(strip)

        # ---- 编辑后防抖自动重验 ----
        self._reval_timer = QTimer(self)
        self._reval_timer.setSingleShot(True)
        self._reval_timer.timeout.connect(self._auto_revalidate)

    # ---- 计数条 ----
    def _update_ribbon(self):
        n = len(self.win.sequences)
        done = len(self.win.results)
        g = sum(1 for r in self.win.results.values() if r.status == "green")
        y = sum(1 for r in self.win.results.values() if r.status == "yellow")
        e = sum(1 for r in self.win.results.values() if r.status == "red")
        self.lbl_ribbon.setText(
            f'<span style="color:#24292f">{n} sequences</span> · '
            f'<span style="color:#57606a">{done} annotated</span> &nbsp;&nbsp; '
            f'<span style="color:#1a7f37">✓ {g} ready</span> &nbsp; '
            f'<span style="color:#9a6700">⚠ {y} warnings</span> &nbsp; '
            f'<span style="color:#cf222e">✗ {e} need review</span>')

    def _jump_next_issue(self):
        """循环跳到下一条有 warning/error 的序列。"""
        order = [self.win.sequences[i].seq_id for i in range(self.seq_list.count())]
        flagged = [sid for sid in order
                   if self.win.results.get(sid) and self.win.results[sid].status != "green"]
        if not flagged:
            return
        pos = order.index(self.current) if self.current in order else -1
        after = [sid for sid in flagged if order.index(sid) > pos]
        target = (after or flagged)[0]
        self.seq_list.setCurrentRow(order.index(target))

    # ---- 数据加载 ----
    def refresh(self):
        self._update_ribbon()
        self.seq_list.blockSignals(True)
        self.seq_list.clear()
        for s in self.win.sequences:
            res = self.win.results.get(s.seq_id)
            state = res.status if res else "pending"
            mark = _STATUS_MARK.get(state, "○ not annotated")
            item = QListWidgetItem(f"{mark}  {s.seq_id}")
            item.setData(Qt.ItemDataRole.UserRole, s.seq_id)
            item.setForeground(QColor(_STATUS_COLOR.get(state, "#8b949e")))
            self.seq_list.addItem(item)
        self.seq_list.blockSignals(False)
        if self.seq_list.count():
            row = max(0, self.seq_list.currentRow())
            self.seq_list.setCurrentRow(row)

    def _refresh_seq_row(self, seq_id: str):
        """只刷新清单中该序列的状态行（自动重验时避免整表重建打断编辑）。"""
        res = self.win.results.get(seq_id)
        state = res.status if res else "pending"
        mark = _STATUS_MARK.get(state, "○ not annotated")
        for row in range(self.seq_list.count()):
            item = self.seq_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == seq_id:
                item.setText(f"{mark}  {seq_id}")
                item.setForeground(QColor(_STATUS_COLOR.get(state, "#8b949e")))
                return

    def _on_seq_selected(self, row):
        if not (0 <= row < len(self.win.sequences)):
            return
        sid = self.win.sequences[row].seq_id
        self.current = sid
        self.load_result(sid)

    def load_result(self, seq_id: str):
        res = self.win.results.get(seq_id)
        if res is None:
            self.feature_table.setRowCount(0)
            self.feature_table.set_editable(False)
            self.b_add_feat.setEnabled(False)
            self.b_del_feat.setEnabled(False)
            self.lbl_project_hint.setVisible(False)
            self.lbl_issues.setVisible(False)
            self.issue_list.setVisible(False)
            self.issue_list.clear()
            self.lbl_status.setText("not annotated")
            self.b_confirm.setEnabled(False)
            self.b_confirm.setText("Confirm for export")
            return
        # 无比对上下文（项目加载态）→ 禁编辑并给出常驻提示
        editable = res.detail is not None
        self.feature_table.set_editable(editable)
        self.b_add_feat.setEnabled(editable)
        self.b_del_feat.setEnabled(editable)
        self.lbl_project_hint.setVisible(not editable)
        self.feature_table.build_from_features(res.features)
        self._load_issues(seq_id)

    def _load_issues(self, seq_id: str):
        """刷新 Issues 区与底部状态条（不触碰 feature 表格，保留编辑焦点）。"""
        res = self.win.results.get(seq_id)
        if res is None:
            return
        has_issues = bool(res.issues)
        self.lbl_issues.setVisible(has_issues)
        self.issue_list.setVisible(has_issues)
        self.issue_list.clear()
        for i in res.issues:
            mark, color = _SEVERITY.get(i.level, ("· ", QColor("#57606a")))
            text = f"{mark}{i.level.capitalize()}: {i.message}"
            hint = HINTS.get(i.code)
            if hint:
                text += f"\n      → {hint}"
            item = QListWidgetItem(text)
            item.setForeground(color)
            term = _ISSUE_HELP.get(i.code)
            if term:
                item.setData(Qt.ItemDataRole.UserRole, term)
            item.setData(Qt.ItemDataRole.UserRole + 1, i.code)
            if term or i.code in _ISSUE_ROW_TYPE:
                item.setToolTip("Click to jump to the related feature row"
                                + (" and open the glossary card" if term else ""))
            self.issue_list.addItem(item)
        # 底部状态条：状态文案 + Confirm 按钮随状态变化（红灯必选、黄灯可选、绿灯禁用）
        self.lbl_status.setText(
            f"{seq_id}: {_STATUS_LABEL.get(res.status, res.status)}"
            + ("  (manually confirmed)" if self.win.confirmed.get(seq_id) else ""))
        if res.status == "red":
            confirmed = self.win.confirmed.get(seq_id)
            self.b_confirm.setEnabled(not confirmed)
            self.b_confirm.setText("Confirmed ✓" if confirmed
                                   else "Confirm for export (required)")
        elif res.status == "yellow":
            confirmed = self.win.confirmed.get(seq_id)
            self.b_confirm.setEnabled(not confirmed)
            self.b_confirm.setText("Confirmed ✓" if confirmed
                                   else "Confirm for export (optional)")
        else:
            self.b_confirm.setEnabled(False)
            self.b_confirm.setText("Confirm for export")

    # ---- 编辑重验 ----
    def _on_edited(self):
        res = self.win.results.get(self.current) if self.current else None
        if res is None:
            return
        self._reval_timer.start(600)

    def _auto_revalidate(self):
        sid = self.current
        res = self.win.results.get(sid)
        if res is None or res.detail is None:
            return      # 项目加载态无比对上下文：静默跳过（行内提示已说明）
        s = next((x for x in self.win.sequences if x.seq_id == sid), None)
        if s is None:
            return
        try:
            features = self.feature_table.to_features()
        except ValueError as ex:
            # 解析失败不弹窗打断输入：行内提示，保留上次有效结果
            self.lbl_status.setText(f"⚠ Invalid edit - not re-validated: {ex}")
            return
        issues = validate(s, features, res.detail.mapping, res.detail.ref_features,
                          res.detail.ref_seq, res.detail.preset, self.win.make_config())
        res.features = features
        # 重验只替换 validate() 的输出；管线早期/迁移期的提示（base_issues）原样保留
        res.issues = list(res.detail.base_issues) + issues
        res.status = status_of(res.issues)
        res.tbl_text = write_tbl(features, sid)
        self._load_issues(sid)
        self._refresh_seq_row(sid)
        self._update_ribbon()
        self.lbl_status.setText(self.lbl_status.text() + "   ·   re-checked just now")
        self.win.log(f"[{sid}] Auto re-validated: status {res.status}, "
                     f"{len(issues)} issue(s)")

    def _recheck_all(self):
        """用当前设置重查全部已注释序列（如改了 identity threshold 之后）。"""
        n = 0
        for s in self.win.sequences:
            res = self.win.results.get(s.seq_id)
            if res is None or res.detail is None:
                continue
            issues = validate(s, res.features, res.detail.mapping, res.detail.ref_features,
                              res.detail.ref_seq, res.detail.preset, self.win.make_config())
            res.issues = list(res.detail.base_issues) + issues
            res.status = status_of(res.issues)
            res.tbl_text = write_tbl(res.features, s.seq_id)
            n += 1
        self.refresh()
        self.win.log(f"Re-checked {n} sequence(s) with current settings")

    # ---- feature 行增删 ----
    def _add_feature(self):
        s = next((x for x in self.win.sequences if x.seq_id == self.current), None)
        if s is None:
            QMessageBox.information(self, "No sequence",
                                    "Annotate a sequence first, then add features.")
            return
        self.feature_table.add_feature(ftype="CDS", coords=f"1..{len(s.seq)}")
        self.win.log(f"[{self.current}] feature row added - edit it, "
                     f"re-validation follows automatically")
        self._on_edited()

    def _delete_feature(self):
        rows = self.feature_table.selected_rows()
        if not rows:
            return
        err = self.feature_table.remove_rows(rows)
        if err:
            QMessageBox.information(self, "Not allowed", err)
            return
        self._on_edited()

    # ---- issue 点击 → 术语卡 + 行跳转 ----
    def _on_issue_clicked(self, item):
        term = item.data(Qt.ItemDataRole.UserRole)
        if term:
            show_help(term, self)
        ftype = _ISSUE_ROW_TYPE.get(item.data(Qt.ItemDataRole.UserRole + 1))
        if not ftype:
            return
        for row in range(self.feature_table.rowCount()):
            titem = self.feature_table.item(row, 0)
            if titem is not None and titem.text().strip() == ftype:
                self.feature_table.selectRow(row)
                self.feature_table.scrollToItem(titem)
                break

    # ---- 人工确认（红灯必须，黄灯可选）----
    def _manual_confirm(self):
        sid = self.current
        if not sid:
            return
        res = self.win.results.get(sid)
        if res is None:
            return
        if res.status == "green":
            QMessageBox.information(self, "No confirmation needed",
                                    "This sequence is Ready; no confirmation needed.")
            return
        note, ok = self._ask_note(sid)
        if not ok:
            return
        self.win.confirmed[sid] = True
        self.win.log(f"[{sid}] Manually confirmed" + (f": {note}" if note else ""))
        self.load_result(sid)
        self.refresh()

    def _ask_note(self, sid: str):
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Manual confirmation",
            f"Confirm [{sid}] is ready for submission (optional note, recorded in log):")
        return (text.strip(), ok)

    def _reference_features_text(self):
        """参考记录自身的五列 feature table（不含 source，只读对照用）。"""
        res = self.win.results.get(self.current) if self.current else None
        if res is None or res.detail is None:
            return None
        d = res.detail
        features = [f for f in d.ref_features if f.ftype != "source"]
        acc = res.provenance.reference or "reference"
        return write_tbl(features, acc)

    def _show_reference_features(self):
        text = self._reference_features_text()
        if text is None:
            QMessageBox.information(self, "No reference features",
                                    "The current result lacks alignment context (loaded from "
                                    "a project file). Re-annotate in step 2 first.")
            return
        acc = self.win.results[self.current].provenance.reference or "reference"
        dlg = AlignmentDialog(f"Reference features - {acc}", text, self)
        dlg.exec()

    def _show_alignment(self):
        res = self.win.results.get(self.current) if self.current else None
        if res is None or res.detail is None:
            QMessageBox.information(self, "No alignment",
                                    "Missing alignment context (annotate in this session first).")
            return
        dlg = AlignmentDialog("Reference vs Query - alignment view",
                              _alignment_text(res.detail.mapping, res.detail.ref_seq), self)
        dlg.exec()
