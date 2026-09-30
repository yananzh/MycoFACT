"""P4 注释审核页（§7.2，核心交互页）：两个列表——左侧基因名单，右侧注释结果列表
（该序列每个参考一行：Reference / Status / Identity / Issues / Use，点行查看该
variant，Use 列单选采纳，Issues 列悬停可见完整问题与建议）；feature 表格支持增删行、
编辑后 600ms 防抖自动重验（无比对上下文的项目加载态禁编辑并给行内提示）；
红灯序列在导出页导出时确认后才能导出（确认弹窗见 page_export）。"""
import html

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QTextCursor
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QFrame, QHBoxLayout,
                             QHeaderView, QLabel, QListWidget, QListWidgetItem,
                             QMessageBox, QPlainTextEdit, QPushButton, QRadioButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ...core.tbl_writer import write_tbl
from ...core.validator import status_of, validate
from ..widgets.feature_table import FeatureTable
from ..widgets.help import (STATUS_COLOR as _STATUS_COLOR,
                            STATUS_MARK as _STATUS_MARK,
                            show_page_help)
_SEVERITY = {"error": ("⛔ ", QColor("#cf222e")),
             "warning": ("⚠ ", QColor("#9a6700")),
             "info": ("ℹ ", QColor("#57606a"))}

# 已知问题 → 一句建议动作（§11：验证报告用自然语言解释）
HINTS = {
    "internal_stop": "Most often a frameshift: the query is missing or has an extra "
                     "base (check for sequencing errors). A wrong transl table can "
                     "also create false stop codons.",
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
    "cds_phase": "A length that is not a multiple of three usually means a frameshift "
                 "(missing/extra base) - verify the sequence; only mark the end "
                 "partial if it genuinely is.",
    "protein_identity": "Protein differs a lot from the reference - it may be misannotated "
                        "or from a distant species.",
}


def _issues_tooltip(issues) -> str:
    """结果列表 Issues 列的悬停文本：完整问题清单（级别 + 说明 + 建议动作）。"""
    if not issues:
        return ""
    lines = []
    for i in issues:
        mark, _ = _SEVERITY.get(i.level, ("· ", None))
        line = f"{mark}{i.level.capitalize()}: {i.message}"
        hint = HINTS.get(i.code)
        if hint:
            line += f"\n   → {hint}"
        lines.append(line)
    text = "\n".join(lines)
    return text if len(text) <= 900 else text[:900].rstrip() + "…"


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
    help_key = "page_review"

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.current: str | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        # ---- 顶部计数条：总览 ----
        ribbon = QHBoxLayout()
        self.lbl_ribbon = QLabel("")
        self.lbl_ribbon.setTextFormat(Qt.TextFormat.RichText)
        ribbon.addWidget(self.lbl_ribbon)
        ribbon.addStretch(1)
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
        # ---- Annotation results：右侧列表——左侧选中基因的全部注释结果，
        #      点行查看该 variant，Use 列单选采纳（导出与步骤状态取采纳者）----
        self.viewed_ref: str | None = None      # 当前查看的 variant（切换序列时回落采纳者）
        self._use_radios: list[QRadioButton] = []
        right.addWidget(QLabel("Annotation results"))
        self.variant_table = QTableWidget(0, 5)
        self.variant_table.setHorizontalHeaderLabels(
            ["Reference", "Status", "Identity", "Issues", "Use"])
        self.variant_table.verticalHeader().setVisible(False)
        self.variant_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.variant_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.variant_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.variant_table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.variant_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.variant_table.setMaximumHeight(132)
        self.variant_table.clicked.connect(self._on_variant_clicked)
        self.variant_table.itemDoubleClicked.connect(self._on_variant_double_clicked)
        right.addWidget(self.variant_table)

        # ---- 行内问题提示：当前查看 variant 的 error/warning 与建议动作，
        #      直接可见，不只藏在 Issues 列的悬停 tooltip 里 ----
        self.lbl_issues = QLabel("")
        self.lbl_issues.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_issues.setWordWrap(True)
        self.lbl_issues.setVisible(False)
        right.addWidget(self.lbl_issues)

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
        b_help = QPushButton("Help")
        b_help.setToolTip("How to use this page: steps, terms, tips")
        b_help.clicked.connect(lambda: show_page_help("page_review", self))
        toolbar.addWidget(b_help)
        toolbar.addStretch(1)
        right.addLayout(toolbar)
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

        # ---- 编辑后防抖自动重验 ----
        self._reval_timer = QTimer(self)
        self._reval_timer.setSingleShot(True)
        self._reval_timer.timeout.connect(self._auto_revalidate)

    # ---- variant 辅助（同序列多参考结果）----
    def _variants(self, sid: str) -> dict:
        return self.win.results.get(sid) or {}

    def _viewed_acc(self, sid: str) -> str | None:
        """当前查看的 variant accession；未显式切换时跟随采纳者。"""
        variants = self._variants(sid)
        if not variants:
            return None
        if self.viewed_ref in variants:
            return self.viewed_ref
        return self.win.chosen_accession(sid)

    def _viewed_result(self, sid: str):
        acc = self._viewed_acc(sid)
        return self._variants(sid).get(acc) if acc else None

    # ---- 计数条 ----
    def _update_ribbon(self):
        n = len(self.win.sequences)
        done = sum(1 for s in self.win.sequences if self.win.results.get(s.seq_id))
        g = y = e = 0
        for s in self.win.sequences:
            res = self.win.chosen_result(s.seq_id)
            if res is None:
                continue
            if res.status == "green":
                g += 1
            elif res.status == "yellow":
                y += 1
            else:
                e += 1
        self.lbl_ribbon.setText(
            f'<span style="color:#24292f">{n} sequences</span> · '
            f'<span style="color:#57606a">{done} annotated</span> &nbsp;&nbsp; '
            f'<span style="color:#1a7f37">✓ {g} ready</span> &nbsp; '
            f'<span style="color:#9a6700">⚠ {y} warnings</span> &nbsp; '
            f'<span style="color:#cf222e">✗ {e} need review</span>')

    # ---- 数据加载 ----
    def refresh(self):
        self._update_ribbon()
        keep = self.current          # clear() 会把 currentRow 重置为 -1，先记下原序列
        self.seq_list.blockSignals(True)
        self.seq_list.clear()
        for s in self.win.sequences:
            res = self.win.chosen_result(s.seq_id)
            state = res.status if res else "pending"
            mark = _STATUS_MARK.get(state, "○ not annotated")
            item = QListWidgetItem(f"{mark}  {s.seq_id}")
            item.setData(Qt.ItemDataRole.UserRole, s.seq_id)
            item.setForeground(QColor(_STATUS_COLOR.get(state, "#8b949e")))
            self.seq_list.addItem(item)
        self.seq_list.blockSignals(False)
        if self.seq_list.count():
            # 回到原序列（Re-check all / 确认导出 / 切页后浏览位置不丢）；不在了则回第一行
            row = next((i for i in range(self.seq_list.count())
                        if self.seq_list.item(i).data(Qt.ItemDataRole.UserRole) == keep), 0)
            self.seq_list.setCurrentRow(row)

    def _refresh_seq_row(self, seq_id: str):
        """只刷新清单中该序列的状态行（自动重验时避免整表重建打断编辑）。"""
        res = self.win.chosen_result(seq_id)
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
        self.viewed_ref = None       # 切换序列 → 回到查看其采纳的 variant
        self.load_result(sid)

    def load_result(self, seq_id: str):
        variants = self._variants(seq_id)
        if not variants:
            self.viewed_ref = None
            self._use_radios = []
            self.variant_table.setRowCount(0)
            self.variant_table.setVisible(False)
            self.feature_table.setRowCount(0)
            self.feature_table.set_editable(False)
            self.b_add_feat.setEnabled(False)
            self.b_del_feat.setEnabled(False)
            self.lbl_project_hint.setVisible(False)
            self.lbl_issues.setVisible(False)
            return
        if self.viewed_ref not in variants:
            self.viewed_ref = self.win.chosen_accession(seq_id)
        self._populate_variant_table(seq_id)
        self._update_issues_hint(seq_id)
        res = variants[self.viewed_ref]
        # 无比对上下文（项目加载态）→ 禁编辑并给出常驻提示
        editable = res.detail is not None
        self.feature_table.set_editable(editable)
        self.b_add_feat.setEnabled(editable)
        self.b_del_feat.setEnabled(editable)
        self.lbl_project_hint.setVisible(not editable)
        self.feature_table.build_from_features(res.features)

    # ---- Annotation results ----
    def _populate_variant_table(self, seq_id: str):
        """结果列表：该序列的每个参考一行（按选择排名序）；点行查看该 variant，
        Use 列单选采纳，Issues 列悬停查看完整问题清单。"""
        variants = self._variants(seq_id)
        order = list(self.win.selected_refs.get(seq_id) or [])
        accs = ([a for a in order if a in variants]
                + [a for a in variants if a not in order])
        chosen_acc = self.win.chosen_accession(seq_id)
        self.variant_table.setRowCount(0)
        self.variant_table.setVisible(True)
        self._use_radios = []
        for acc in accs:
            res = variants[acc]
            row = self.variant_table.rowCount()
            self.variant_table.insertRow(row)
            self.variant_table.setItem(row, 0, QTableWidgetItem(acc))
            st = QTableWidgetItem(_STATUS_MARK.get(res.status, res.status))
            st.setForeground(QColor(_STATUS_COLOR.get(res.status, "#24292f")))
            self.variant_table.setItem(row, 1, st)
            prov = getattr(res, "provenance", None)
            ident = getattr(prov, "nt_identity", None) if prov else None
            self.variant_table.setItem(
                row, 2, QTableWidgetItem(f"{ident:.1%}" if ident is not None else "-"))
            n_err = sum(1 for i in res.issues if i.level == "error")
            n_warn = sum(1 for i in res.issues if i.level == "warning")
            issues_item = QTableWidgetItem(
                f"{len(res.issues)}"
                + (f" ({n_err}E/{n_warn}W)" if res.issues else ""))
            issues_item.setToolTip(_issues_tooltip(res.issues))
            if n_err:
                issues_item.setForeground(QColor("#cf222e"))
            elif n_warn:
                issues_item.setForeground(QColor("#9a6700"))
            self.variant_table.setItem(row, 3, issues_item)
            use = QRadioButton()
            use.setChecked(acc == chosen_acc)   # 先设状态再连信号，避免误触发采纳
            use.setToolTip("Use this result for export")
            use.toggled.connect(lambda on, a=acc: self._on_use_toggled(on, a))
            self.variant_table.setCellWidget(row, 4, use)
            self._use_radios.append(use)
        if self.viewed_ref in accs:      # 当前查看行保持选中
            self.variant_table.selectRow(accs.index(self.viewed_ref))

    def _update_issues_hint(self, seq_id: str):
        """行内提示当前查看 variant 的 error/warning（error 优先，附建议动作）。"""
        res = self._viewed_result(seq_id)
        issues = [i for i in (res.issues if res else [])
                  if i.level in ("error", "warning")]
        if not issues:
            self.lbl_issues.setText("")
            self.lbl_issues.setVisible(False)
            return
        shown, rest = issues[:3], issues[3:]
        lines = []
        for i in shown:
            mark, color = (("⛔", "#cf222e") if i.level == "error" else ("⚠", "#9a6700"))
            line = f"<span style='color:{color}'><b>{mark} {html.escape(i.message)}</b>"
            hint = HINTS.get(i.code)
            if hint:
                line += f"<br>&nbsp;&nbsp;→ {html.escape(hint)}"
            lines.append(line + "</span>")
        if rest:
            lines.append(f"<span style='color:#57606a'>+{len(rest)} more - hover the "
                         "Issues column for the full list</span>")
        self.lbl_issues.setText("<br>".join(lines))
        self.lbl_issues.setVisible(True)

    def _on_use_toggled(self, on: bool, acc: str):
        """Use 列单选：勾选即采纳该 variant（导出与步骤状态随之切换）。"""
        if not on:
            return
        sid = self.current
        if not sid or acc not in self._variants(sid):
            return
        if acc != self.win.chosen_accession(sid):
            self._adopt(acc)

    def _on_variant_clicked(self, index):
        """点结果列表行 → 切换查看该 variant（feature 表 / Confirm 随之刷新）。"""
        sid = self.current
        if not sid or not index.isValid():
            return
        acc_item = self.variant_table.item(index.row(), 0)
        acc = acc_item.text() if acc_item else None
        if acc and acc != self.viewed_ref and acc in self._variants(sid):
            self.viewed_ref = acc
            self.load_result(sid)

    def _on_variant_double_clicked(self, item):
        acc_item = self.variant_table.item(item.row(), 0)
        if acc_item:
            self._adopt(acc_item.text())

    def _adopt(self, acc: str):
        sid = self.current
        if not sid or acc not in self._variants(sid):
            return
        self.viewed_ref = acc
        self.win.chosen_ref[sid] = acc
        self.win.log(f"[{sid}] Adopted annotation from {acc}")
        self.load_result(sid)            # 重建结果列表 / 清单标记 / 计数条
        self.win._refresh_nav()
        self.win.page_export.refresh()

    # ---- 编辑重验 ----
    def _on_edited(self):
        res = self._viewed_result(self.current) if self.current else None
        if res is None:
            return
        self._reval_timer.start(600)

    def _auto_revalidate(self):
        sid = self.current
        res = self._viewed_result(sid) if sid else None
        if res is None or res.detail is None:
            return      # 项目加载态无比对上下文：静默跳过（行内提示已说明）
        s = next((x for x in self.win.sequences if x.seq_id == sid), None)
        if s is None:
            return
        try:
            features = self.feature_table.to_features()
        except ValueError as ex:
            # 解析失败不弹窗打断输入：状态栏提示，保留上次有效结果
            self.win.log(f"⚠ Invalid edit - not re-validated: {ex}")
            return
        issues = validate(s, features, res.detail.mapping, res.detail.ref_features,
                          res.detail.ref_seq, res.detail.preset, self.win.make_config())
        res.features = features
        # 重验只替换 validate() 的输出；管线早期/迁移期的提示（base_issues）原样保留
        res.issues = list(res.detail.base_issues) + issues
        res.status = status_of(res.issues)
        res.tbl_text = write_tbl(features, sid)
        self._populate_variant_table(sid)
        self._update_issues_hint(sid)
        self._refresh_seq_row(sid)
        self._update_ribbon()
        self.win.log(f"[{sid}] Auto re-validated vs {self.viewed_ref}: "
                     f"status {res.status}, {len(issues)} issue(s)")

    def _recheck_all(self):
        """用当前设置重查全部已注释序列的全部 variant（如改了 identity threshold 后）。"""
        n = 0
        for s in self.win.sequences:
            for res in (self.win.results.get(s.seq_id) or {}).values():
                if res.detail is None:
                    continue
                issues = validate(s, res.features, res.detail.mapping,
                                  res.detail.ref_features, res.detail.ref_seq,
                                  res.detail.preset, self.win.make_config())
                res.issues = list(res.detail.base_issues) + issues
                res.status = status_of(res.issues)
                res.tbl_text = write_tbl(res.features, s.seq_id)
                n += 1
        self.refresh()
        if self.current:
            self._update_issues_hint(self.current)
        self.win.log(f"Re-checked {n} result variant(s) with current settings")

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

    def _reference_features_text(self):
        """参考记录自身的五列 feature table（不含 source，只读对照用）。"""
        res = self._viewed_result(self.current) if self.current else None
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
        acc = self._viewed_result(self.current).provenance.reference or "reference"
        dlg = AlignmentDialog(f"Reference features - {acc}", text, self)
        dlg.exec()

    def _show_alignment(self):
        res = self._viewed_result(self.current) if self.current else None
        if res is None or res.detail is None:
            QMessageBox.information(self, "No alignment",
                                    "Missing alignment context (annotate in this session first).")
            return
        dlg = AlignmentDialog("Reference vs Query - alignment view",
                              _alignment_text(res.detail.mapping, res.detail.ref_seq), self)
        dlg.exec()
