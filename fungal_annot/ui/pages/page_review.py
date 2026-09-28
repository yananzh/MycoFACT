"""P4 注释审核页（§7.2，核心交互页）：状态灯、计数条、可编辑 feature 表格、
结构化验证报告（带修复提示）、比对视图、红灯人工确认。
Phase 3 新手友好：issue 带图标与建议动作，术语就地解释（? 帮助卡）。"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QTextCursor
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QMessageBox, QPlainTextEdit,
                             QPushButton, QVBoxLayout, QWidget)

from ...core.tbl_writer import write_tbl
from ...core.validator import status_of, validate
from ..icons import icon
from ..widgets.feature_table import FeatureTable
from ..widgets.help import HelpButton

_STATUS_COLOR = {"green": "#1a7f37", "yellow": "#9a6700", "red": "#cf222e"}
_STATUS_LABEL = {"green": "Green - pass", "yellow": "Yellow - warnings (may submit)",
                 "red": "Red - manual confirmation required"}
_SEVERITY = {"error": ("⛔  ", QColor("#cf222e")),
             "warning": ("⚠  ", QColor("#9a6700")),
             "info": ("ℹ  ", QColor("#57606a"))}

# 已知问题 → 一句建议动作（§11：验证报告用自然语言解释）
HINTS = {
    "internal_stop": "Check the transl table (reference qualifier vs preset). A wrong "
                     "table can create false stop codons.",
    "exon_outside_aligned": "Normal for partial amplicons - your query simply does not "
                            "cover the whole gene. No action needed.",
    "exon_map_fail": "A reference exon has no counterpart in your sequence (indel/gap). "
                     "Review the affected segment manually.",
    "low_identity": "The reference may be too distant - pick a closer one in step 3, "
                    "or accept it knowingly.",
    "modifier_missing": "Fill the missing source qualifiers on the Import page "
                        "(batch apply) or edit the source row here.",
    "modifier_format": "Fix the format in the source row (see NCBI qualifier rules: "
                       "country, collection_date, lat_lon).",
    "country_unverified": "Check spelling against the official NCBI country list.",
    "seqid_invalid": "Rename the sequence here (first column) or on the Import page.",
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
    title = "4. Review"         # 步骤条标签：水平等宽排布下需要短标签

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.current: str | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        # ---- 顶部计数条 + 跳转（Phase 3）----
        ribbon = QHBoxLayout()
        self.lbl_ribbon = QLabel("")
        self.lbl_ribbon.setTextFormat(Qt.TextFormat.RichText)
        self.b_next_issue = QPushButton("Next issue →")
        self.b_next_issue.setToolTip("Jump to the next sequence with warnings or errors")
        self.b_next_issue.clicked.connect(self._jump_next_issue)
        ribbon.addWidget(self.lbl_ribbon)
        ribbon.addStretch(1)
        ribbon.addWidget(self.b_next_issue)
        outer.addLayout(ribbon)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Sequences (status)"))
        self.seq_list = QListWidget()
        self.seq_list.currentRowChanged.connect(self._on_seq_selected)
        left.addWidget(self.seq_list, 1)
        self.lbl_status = QLabel("-")
        self.lbl_status.setWordWrap(True)
        left.addWidget(self.lbl_status)
        b_confirm = QPushButton("Manual confirm (RED must be confirmed before export)")
        b_confirm.clicked.connect(self._manual_confirm)
        left.addWidget(b_confirm)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        self.feature_table = FeatureTable()
        right.addWidget(self.feature_table, 2)

        btns = QHBoxLayout()
        b_reval = QPushButton(icon("fa5s.sync-alt"), "Re-validate")
        b_reval.clicked.connect(self._revalidate)
        b_align = QPushButton("View alignment")
        b_align.clicked.connect(self._show_alignment)
        b_ref_feat = QPushButton(icon("fa5s.table"), "View reference features")
        b_ref_feat.setToolTip("Show the reference record's own five-column feature table")
        b_ref_feat.clicked.connect(self._show_reference_features)
        btns.addWidget(b_reval)
        btns.addWidget(b_align)
        btns.addWidget(b_ref_feat)
        btns.addWidget(HelpButton("partial"))
        btns.addWidget(HelpButton("codon_start"))
        btns.addStretch(1)
        right.addLayout(btns)

        right.addWidget(QLabel("Validation report"))
        self.issue_list = QListWidget()
        right.addWidget(self.issue_list, 1)
        body.addLayout(right, 3)
        outer.addLayout(body, 1)

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
            f'<span style="color:#1a7f37">● {g} pass</span> &nbsp; '
            f'<span style="color:#9a6700">● {y} warn</span> &nbsp; '
            f'<span style="color:#cf222e">● {e} error</span>')

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
            mark = {"green": "● pass", "yellow": "● warn",
                    "red": "● RED"}.get(state, "○ not annotated")
            item = QListWidgetItem(f"{mark}  {s.seq_id}")
            item.setForeground(QColor(_STATUS_COLOR.get(state, "#8b949e")))
            self.seq_list.addItem(item)
        self.seq_list.blockSignals(False)
        if self.seq_list.count():
            row = max(0, self.seq_list.currentRow())
            self.seq_list.setCurrentRow(row)

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
            self.issue_list.clear()
            self.issue_list.addItem(QListWidgetItem("Not annotated (go back and run annotation)"))
            self.lbl_status.setText("not annotated")
            return
        self.feature_table.build_from_features(res.features)
        self.issue_list.clear()
        if not res.issues:
            ok = QListWidgetItem("✓  All checks passed")
            ok.setForeground(QColor("#1a7f37"))
            self.issue_list.addItem(ok)
        for i in res.issues:
            mark, color = _SEVERITY.get(i.level, ("·  ", QColor("#57606a")))
            text = f"{mark}[{i.level}] {i.message}"
            hint = HINTS.get(i.code)
            if hint:
                text += f"\n      → {hint}"
            item = QListWidgetItem(text)
            item.setForeground(color)
            self.issue_list.addItem(item)
        self.lbl_status.setText(f"{seq_id}: {_STATUS_LABEL.get(res.status, res.status)}"
                                + (" (manually confirmed)" if self.win.confirmed.get(seq_id) else ""))

    # ---- 编辑重验 ----
    def _revalidate(self):
        sid = self.current
        res = self.win.results.get(sid)
        if res is None or res.detail is None:
            QMessageBox.warning(self, "Cannot re-validate",
                                "The current result lacks alignment context (loaded from a "
                                "project file). Re-annotate in step 3 first.")
            return
        s = next((x for x in self.win.sequences if x.seq_id == sid), None)
        if s is None:
            return
        try:
            features = self.feature_table.to_features()
        except ValueError as ex:
            QMessageBox.warning(self, "Invalid input", str(ex))
            return
        detail = res.detail
        issues = validate(s, features, detail.mapping, detail.ref_features,
                          detail.ref_seq, detail.preset, self.win.make_config())
        res.features = features
        res.issues = issues
        res.status = status_of(issues)
        res.tbl_text = write_tbl(features, sid)
        self.load_result(sid)
        self.refresh()
        self.win.log(f"[{sid}] Re-validated after edit: status {res.status}, "
                     f"{len(issues)} issue(s)")

    def _manual_confirm(self):
        sid = self.current
        if not sid:
            return
        res = self.win.results.get(sid)
        if res is None:
            return
        if res.status != "red" and not res.issues:
            QMessageBox.information(self, "No confirmation needed",
                                    "This sequence is green; no confirmation needed.")
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
        """参考记录自身的五列 feature table（含原 qualifier，只读对照用）。"""
        res = self.win.results.get(self.current) if self.current else None
        if res is None or res.detail is None:
            return None
        d = res.detail
        features = list(d.ref_features)
        if d.ref_len:
            from ...core.models import Feature as _F, FeaturePart as _P
            src_f = _F(ftype="source", strand=1,
                       parts=[_P(1, d.ref_len)], qualifiers=d.ref_source_quals)
            features = [src_f] + features
        acc = res.provenance.reference or "reference"
        return write_tbl(features, acc)

    def _show_reference_features(self):
        text = self._reference_features_text()
        if text is None:
            QMessageBox.information(self, "No reference features",
                                    "The current result lacks alignment context (loaded from "
                                    "a project file). Re-annotate in step 3 first.")
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
