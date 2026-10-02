"""简明帮助：四页操作步骤、全流程概览和就地术语解释，共用 HTML 弹窗。"""
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
                             QTextBrowser, QVBoxLayout)

# ---- 调色板（与主窗口步骤条/红绿灯状态色一致）----
ACCENT = "#2D7DD2"          # 当前步骤/主按钮的品牌蓝
ACCENT_DARK = "#1B5A9C"     # 标题深蓝
MUTED = "#57606a"
GREEN = "#1a7f37"
YELLOW = "#9a6700"
RED = "#cf222e"

# 红绿灯状态的配色与动作化文案（第 3/4 页共用；页面代码 import 这两个）
STATUS_COLOR = {"green": GREEN, "yellow": YELLOW, "red": RED, "pending": MUTED}
STATUS_MARK = {"green": "✓ Ready", "yellow": "⚠ Warnings", "red": "✗ Needs review",
               "pending": "○ Awaiting validation"}

# "Marker" 列的就地解释（第 1/2/4 页共用）：说明自动判定机制与其影响
MARKER_HINT = ("Marker inferred from BLAST titles or reference annotation; controls "
               "transferred features and genetic code. 'auto-detect' means not yet identified.")

# 提交免责声明（APP_GUIDE / 旧 About / 新 About 弹窗共用一句，避免多处漂移）
DISCLAIMER = ("Results are drafting aids - verify against current NCBI rules "
              "before submitting.")


# ---- 渲染基建：小块拼装 ----------------------------------------------------
_SUBMISSION_LINKS = (
    '<a href="https://submit.ncbi.nlm.nih.gov/subs/genbank/">'
    'NCBI BankIt submission portal</a>',
    '<a href="https://www.ncbi.nlm.nih.gov/genbank/feature_table/">'
    'NCBI feature-table guide</a>',
)


# ---- 渲染基建：弹窗外壳 ----------------------------------------------------
_DOC_CSS = (
    "h3 { color: " + ACCENT_DARK + "; font-size: 12pt; margin-top: 16px; margin-bottom: 5px; }"
    "p { margin-top: 4px; margin-bottom: 6px; }"
    "li { margin-top: 2px; margin-bottom: 3px; }"
    "code { background-color: #f0f3f6; color: #953800; }"
    "td { vertical-align: top; }"
)


def _wrap(title: str, subtitle: str, body: str, footer: str = "") -> str:
    """统一外壳：品牌横幅（单格表，背景最可靠）+ 样式表 + 正文容器 + 页脚。"""
    banner = (
        '<table width="100%" cellspacing="0" cellpadding="0"><tr>'
        '<td style="background-color:' + ACCENT + '; padding-top:12px; '
        'padding-bottom:12px; padding-left:16px; padding-right:16px;">'
        '<span style="color:#ffffff; font-size:16pt; font-weight:bold;">' + title
        + '</span><br>'
        '<span style="color:#d8e7f8; font-size:10pt;">' + subtitle + '</span>'
        '</td></tr></table>')
    foot = f'<p style="color:{MUTED}; font-size:8.5pt;">{footer}</p>' if footer else ""
    return (f"<style>{_DOC_CSS}</style>" + banner
            + f'<div style="margin-left:14px; margin-right:14px;">{body}{foot}</div>')


def _help_dialog(title: str, html: str, size: tuple, parent=None) -> QDialog:
    """统一样式帮助弹窗：横幅贴边（零边距）+ 可滚动正文 + Close。"""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(*size)
    v = QVBoxLayout(dlg)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)  # 官方文档在默认浏览器打开，页内目录仍就地跳转
    browser.setFrameShape(QFrame.Shape.NoFrame)
    browser.setHtml(html)
    v.addWidget(browser, 1)
    row = QHBoxLayout()
    row.setContentsMargins(12, 6, 12, 8)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    bb.rejected.connect(dlg.reject)
    row.addWidget(bb)
    v.addLayout(row)
    return dlg


# ---- 页面指南：操作步骤与关键提示 ----
_PAGE_META = {
    "page_import": ("Import &amp; BLAST", "Step 1 of 4"),
    "page_reference": ("Select Reference", "Step 2 of 4"),
    "page_review": ("Review Annotation", "Step 3 of 4"),
    "page_export": ("Export Results", "Step 4 of 4"),
}

PAGE_HELP = {
    "page_import": ("How to use: Import & BLAST", """
<h3>How to use</h3>
<ol>
<li>Enter your NCBI contact email in <b>Settings</b>; internet access is required.</li>
<li>Paste DNA or FASTA, use <b>Browse</b>, or drag FASTA files into the input box.
<b>Example</b> loads sample sequences.</li>
<li>Click <b>BLAST</b> to import and search. Continue to step 2 when searches finish.</li>
</ol>
<p><b>Before import:</b> inspect Sanger traces (.ab1) and trim low-quality ends.</p>
<p><b>STOP</b> skips queued searches; active searches finish.
<b>Clear</b> removes the input and imported sequences.</p>
"""),
    "page_reference": ("How to use: Select Reference", """
<h3>How to use</h3>
<ol>
<li>Select a sequence to see its BLAST hits. Top-ranked references are preselected.</li>
<li>Check <b>1-5 references</b> per sequence. <b>View match</b> lets you edit
accessions; clearing a row restores the recommended hits.</li>
<li>Click <b>Start Annotation</b>. Review the results in step 3 when it finishes.</li>
</ol>
<p>Choose close references with the correct marker. Downloads require internet
access and your NCBI contact email.</p>
"""),
    "page_review": ("How to use: Review Annotation", """
<h3>How to use</h3>
<ol>
<li>Select a sequence and compare its reference results. Select <b>Use</b>
for the result to export.</li>
<li>Read <b>Issues</b>; inspect <b>View alignment</b> or
<b>View reference features</b> when needed.</li>
<li>Edit features, wait for validation, then continue to step 4.
Invalid cells block saving and export.</li>
</ol>
<p><b>Ready:</b> checks passed. <b>Warnings:</b> read the findings.
<b>Needs review:</b> fix errors where possible; remaining errors need confirmation
at export.</p>
<p>Coordinates are 1-based, e.g. <code>&lt;1..300, 401..520</code>.
Qualifiers use <code>key: value</code>, one per line.</p>
<p>Opened project results are read-only until re-annotated in step 2.</p>
"""),
    "page_export": ("How to use: Export Results", f"""
<h3>How to use</h3>
<ol>
<li>Check the summary and output directory. Only the result selected with
<b>Use</b> in step 3 is exported.</li>
<li>Click <b>Export Feature Table</b>. Review any red results before confirming.</li>
<li><b>Open output folder</b> to find per-sequence <code>.tbl</code> files
and the combined <code>all_features.tbl</code>.</li>
</ol>
<p>The project file and results share one folder. For imported FASTA files,
the default is <code>MycoFACT_out</code> beside the first loaded file.</p>
<p>Upload the table(s) with the matching FASTA in {_SUBMISSION_LINKS[0]}.
Enter organism and source details in the portal.</p>
<p>Keep <code>.mycofact-outputs.json</code>. If an existing file conflicts,
choose another folder. Sequences with no transferable features produce no table.</p>
"""),
}


def build_page_help_dialog(term: str, parent=None) -> QDialog:
    """构建页面指南弹窗（统一样式、可滚动）；供 show_page_help 与测试使用。"""
    title, body = PAGE_HELP[term]
    page, subtitle = _PAGE_META[term]
    html = _wrap(page, subtitle, body,
                 footer="Open <b>Guide</b> for the workflow overview.")
    return _help_dialog(title, html, (640, 400), parent)


def show_page_help(term: str, parent=None):
    """弹出当前页的简明操作指南。"""
    build_page_help_dialog(term, parent).exec()


# ---- 术语词条（就地解释）：统一弹窗样式 ----
HELP = {
    "partial": ("Partial feature",
                "<p>A partial feature extends beyond an end of your sequence. "
                "<code>&lt;1</code> or <code>&gt;520</code> marks the incomplete "
                "end; this is common for PCR amplicons.</p>"),
    "codon_start": ("codon_start",
                    "<p>Start of the first complete codon in a 5'-partial CDS: "
                    "<b>1</b> skips no bases, <b>2</b> skips one, "
                    "<b>3</b> skips two. Derived from the reference frame.</p>"),
    "transl_table": ("transl_table (genetic code)",
                     "<p>The genetic code used to translate a CDS, taken from "
                     "the reference. Common codes: <b>1</b> standard, "
                     "<b>12</b> alternative yeast, <b>4</b> mold mitochondria, "
                     "<b>3</b> yeast mitochondria. Review any code-conflict warning.</p>"),
    "identity": ("identity threshold",
                 "<p>Whole-query identity to the reference. Below the threshold "
                 "(default <b>97%</b>), the result is red and needs review. "
                 "This can differ from BLAST's local identity. Change the "
                 "threshold in <b>Settings</b>.</p>"),
}


def build_term_help_dialog(term: str, parent=None) -> QDialog:
    """构建术语词条弹窗（统一样式）；供 show_help 与测试使用。"""
    title, body = HELP[term]
    html = _wrap(title, "Glossary · what the term means in this tool", body)
    return _help_dialog(title, html, (540, 300), parent)


def show_help(term: str, parent=None):
    """按词条名弹出富文本术语解释（issue 行点击等入口共用）。"""
    build_term_help_dialog(term, parent).exec()


# ---- 全软件使用指南（菜单 Guide）----
APP_GUIDE = ("User Guide", f"""
<h3>Before you start</h3>
<p>Inspect Sanger traces (.ab1), trim low-quality ends, and prepare FASTA.
Enter your NCBI contact email in <b>Settings</b>. Searches and reference downloads
require internet access.</p>
<h3>Four steps</h3>
<ol>
<li><b>Import &amp; BLAST:</b> paste DNA or load FASTA, then click <b>BLAST</b>.</li>
<li><b>Select Reference:</b> check 1-5 close references per sequence;
click <b>Start Annotation</b>.</li>
<li><b>Review Annotation:</b> inspect issues and features; select <b>Use</b>
for one result per sequence. Wait for edits to finish validation.</li>
<li><b>Export Results:</b> click <b>Export Feature Table</b>. Upload the
<code>.tbl</code> files or combined <code>all_features.tbl</code> with the matching
FASTA in {_SUBMISSION_LINKS[0]}. Add organism and source details in the portal.</li>
</ol>
<h3>Status</h3>
<p><b>Ready:</b> checks passed. <b>Warnings:</b> read the findings.
<b>Needs review:</b> fix errors where possible; export asks you to accept remaining
errors. <b>Awaiting validation:</b> wait; correct invalid cells before saving
or exporting.</p>
<h3>Save and resume</h3>
<p><b>File &gt; Save / Save As</b> saves a JSON project; <b>Open</b> resumes it.
The project and exported tables share one directory, initially
<code>MycoFACT_out</code> beside the first loaded FASTA. Changing the output folder
or using Save As updates the shared location.</p>
<p>Opened results can be viewed and exported; re-annotate in step 2 to edit them.
Keep <code>.mycofact-outputs.json</code> for repeat exports. If files conflict,
choose another folder. Check <b>Log</b> for task failures.</p>
""")

_APP_SUBTITLE = ("MycoFACT · from raw amplicon "
                 "sequences to a BankIt-ready submission")


def build_app_guide_dialog(parent=None) -> QDialog:
    """构建全软件使用指南弹窗（菜单 Guide 的内容）。"""
    title, body = APP_GUIDE
    html = _wrap(title, _APP_SUBTITLE, body)
    return _help_dialog(title, html, (700, 560), parent)


def show_app_guide(parent=None):
    """弹出全软件使用指南（菜单 Guide）。"""
    build_app_guide_dialog(parent).exec()
