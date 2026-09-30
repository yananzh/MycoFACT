"""帮助系统（统一样式的 HTML 弹窗）：三块内容 + 一套渲染基建。

内容：HELP 术语词条（就地解释）、PAGE_HELP 四页指南（每页 Help 按钮）、
APP_GUIDE 全软件使用指南（菜单 Guide——菜单级帮助是整个软件的使用说明，
而非当前页）；另有 show_help 词条弹窗。About 弹窗在 widgets/about.py（原生
控件 + 更新检查），不复用本模块的 HTML 外壳，但共用 DISCLAIMER 文案。

渲染基建：Qt 富文本只支持 CSS 子集——<style> 块的元素选择器可用（Qt 6 实测），
但横幅、提示框、数据表一律用表格单元格实现（background-color 与 padding 在
单元格上支持最完整、最可预期）；弹窗外壳统一走 _wrap + _help_dialog。
"""
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
                             QTextBrowser, QVBoxLayout)

# ---- 调色板（与主窗口步骤条/红绿灯状态色一致）----
ACCENT = "#2D7DD2"          # 当前步骤/主按钮的品牌蓝
ACCENT_DARK = "#1B5A9C"     # 标题深蓝
MUTED = "#57606a"
HEAD_BG = "#e7f0fb"         # 表头浅蓝
ZEBRA_BG = "#f6f8fa"        # 斑马纹
GREEN = "#1a7f37"
YELLOW = "#9a6700"
RED = "#cf222e"

# 红绿灯状态的配色与动作化文案（第 3/4 页共用；页面代码 import 这两个）
STATUS_COLOR = {"green": GREEN, "yellow": YELLOW, "red": RED}
STATUS_MARK = {"green": "✓ Ready", "yellow": "⚠ Warnings", "red": "✗ Needs review"}
STATUS_BG = {"green": "#eaf4ec", "yellow": "#fff3cd", "red": "#ffebe9"}

# "Marker" 列的就地解释（第 1/2/4 页共用）：说明自动判定机制与其影响
MARKER_HINT = ("Marker gene preset (tef1, act, LSU...) chosen automatically from BLAST "
               "hit titles during annotation - it controls which features are "
               "transferred (CDS vs rRNA) and the genetic code. Shows 'auto-detect' "
               "until then.")

# 提交免责声明（APP_GUIDE / 旧 About / 新 About 弹窗共用一句，避免多处漂移）
DISCLAIMER = ("Results are drafting aids - verify against current NCBI rules "
              "before submitting.")


# ---- 渲染基建：小块拼装 ----------------------------------------------------
def _chip(text: str, fg: str, bg: str) -> str:
    """彩色徽章（Qt 富文本无 border-radius，用色块 + 空格内边距替代圆角药丸）。"""
    return (f'<span style="background-color:{bg}; color:{fg}; font-weight:bold;">'
            f'&nbsp;{text}&nbsp;</span>')


def _status_chip(status: str) -> str:
    return _chip(STATUS_MARK[status], STATUS_COLOR[status], STATUS_BG[status])


def _note(text: str, kind: str = "tip") -> str:
    """单格表格提示框：tip（蓝）/ warn（黄）/ danger（红）。"""
    bg, fg, label = {"tip": ("#eef4fb", ACCENT_DARK, "TIP"),
                     "warn": ("#fff3cd", "#7a5600", "HEADS-UP"),
                     "danger": ("#ffebe9", RED, "IMPORTANT")}[kind]
    return ('<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            '<td style="background-color:' + bg + '; padding-top:8px; '
            'padding-bottom:8px; padding-left:10px; padding-right:10px;">'
            f'<span style="color:{fg}; font-weight:bold;">{label}&nbsp;&nbsp;</span>{text}'
            '</td></tr></table>')


def _table(headers, rows, widths=()) -> str:
    """斑马纹数据表：headers 为纯文本，rows 的单元格是 HTML 片段。"""
    head = []
    for i, h in enumerate(headers):
        w = f' width="{widths[i]}"' if i < len(widths) else ""
        head.append(f'<td{w} style="background-color:{HEAD_BG}; padding-top:5px; '
                    f'padding-bottom:5px; padding-left:8px; padding-right:8px;">'
                    f'<b>{h}</b></td>')
    body = []
    for i, row in enumerate(rows):
        bg = "#ffffff" if i % 2 == 0 else ZEBRA_BG
        tds = "".join(f'<td style="background-color:{bg}; padding-top:5px; '
                      f'padding-bottom:5px; padding-left:8px; padding-right:8px;">'
                      f'{c}</td>' for c in row)
        body.append(f"<tr>{tds}</tr>")
    return ('<table width="100%" cellspacing="0" cellpadding="0">'
            f'<tr>{"".join(head)}</tr>{"".join(body)}</table>')


def _terms_table(pairs) -> str:
    return _table(("Term", "What it means"),
                  [(f"<b>{t}</b>", m) for t, m in pairs], widths=(170,))


def _fix_table(rows) -> str:
    return _table(("What you see", "What to do"),
                  [(f"<b>{a}</b>", b) for a, b in rows], widths=(240,))


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
    browser.setOpenExternalLinks(False)
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


# ---- 页面指南（每页按钮区的 Help 按钮）：What / How to use / Terms / Tips / 问题速查 ----
_PAGE_META = {
    "page_import": ("Import &amp; BLAST",
                    "Step 1 of 4 · bring sequences in and find close references"),
    "page_reference": ("Select Reference",
                       "Step 2 of 4 · pick references and transfer their annotation"),
    "page_review": ("Review Annotation",
                    "Step 3 of 4 · compare results, fix issues, confirm for export"),
    "page_export": ("Export Results",
                    "Step 4 of 4 · write .tbl files and submit via BankIt"),
}

PAGE_HELP = {
    "page_import": ("How to use: Import & BLAST", f"""
<h3>What this page does</h3>
<p>Import your marker sequences and find close references for each with an
<b>online BLAST</b> search at NCBI.</p>

<h3>How to use</h3>
<ol>
<li><b>Get sequences in</b> - paste FASTA (or a bare DNA sequence) into the box,
<b>drag &amp; drop</b> files onto it, or use <b>Browse</b>. No sequences at hand?
<b>Example</b> loads four demo sequences.</li>
<li><b>Press BLAST.</b> The box content is imported (duplicate IDs rejected) and
searched in a small parallel pool (submission rate-limited), ~1-5 min per
sequence. When the queue drains, the app moves to step 2 on its own.</li>
<li><b>Manage the list:</b> <b>double-click a Seq ID to rename</b> (hits, results
and confirmations follow); <b>✕</b> removes a sequence; <b>STOP</b> cancels the
remaining queue.</li>
</ol>

<h3>Terms</h3>
{_terms_table((
    ("FASTA", 'Plain-text sequence format; entries start with a "&gt;" header line.'),
    ("Seq ID", "Unique name (letters, digits and . _ : - | +) - it becomes the "
               "exported file name <code>&lt;SeqID&gt;.tbl</code>."),
    ("Marker", "Which locus the sequence is (tef1, act, LSU, ...) - auto-detected "
               "from BLAST titles; decides which features are transferred and the "
               "genetic code."),
    ("Ident %", "Identity of the <b>best BLAST local match (HSP)</b>: same bases "
                "/ that stretch's length, gaps included. The stretch may be "
                "shorter than your sequence (coverage is the separate Cover %) - "
                "it ranks candidate references. Step 3 recomputes a full-length "
                "value, so the two numbers can differ."),
    ("NCBI email", "Required for online BLAST - set it in menu ▸ Settings."),
    ("BLAST state", f"<code>-</code> queued · <span style='color:{YELLOW}'>running…"
                    f"</span> searching · <span style='color:{GREEN}'>done</span> "
                    "hits stored."),
))}

<h3>Tips</h3>
<ul>
<li><b>BLAST again</b> searches only sequences without hits - add latecomers any
time.</li>
<li>Seq IDs must be unique - they become the exported file names.</li>
</ul>

<h3>Common problems</h3>
{_fix_table((
    ("BLAST is disabled", "Box empty, queue running, or email missing - set it in "
                          "menu ▸ Settings."),
    ("Non-nucleotide characters ...", "Input has letters outside the DNA alphabet - "
                                      "fix it and press BLAST again."),
    ("Duplicate Seq ID", "Rename one (double-click the Seq ID in the list)."),
    ("BLAST failed", "Network hiccup or NCBI throttling - press BLAST again; "
                     "finished ones are skipped."),
))}
"""),
    "page_reference": ("How to use: Select Reference", f"""
<h3>What this page does</h3>
<p>Pick the reference record(s) whose annotation will be transferred onto each
sequence - up to 5 per sequence, compared side by side in step 3.</p>

<h3>How to use</h3>
<ol>
<li><b>Select a sequence</b> on the left; its ranked BLAST hits fill the table.
The <b>light-blue top row is the recommended</b> hit.</li>
<li><b>Check hits in the Use column</b> - 1 to 5 per sequence; top-ranked ones
are pre-checked (Settings ▸ default_refs). Each checked hit gets its own result
in step 3.</li>
<li><b>View match</b> edits the accession lists - you may type accessions not in
the hit list; clear a row to fall back to the recommended hits.</li>
<li><b>Start Annotation</b> downloads each reference, transfers gene/CDS (or
rRNA) features and validates - step 3 opens when the queue drains.</li>
</ol>

<h3>Terms</h3>
{_terms_table((
    ("Ident %", "Nucleotide identity between hit and your sequence."),
    ("Cover %", "How much of your sequence the hit aligns - near 100% is needed "
                "for reliable ends."),
    ("Ratio", "Reference length / yours. 1.0-1.5 ideal; &gt;2 = genome-scale "
              "record (only the matching window is fetched)."),
    ("Accession", "Stable record ID (e.g. MZ123456.1) - you may type your own in "
                  "View match."),
    ("Use", "Checkbox column - checked = annotated against this reference."),
))}

<h3>Tips</h3>
<ul>
<li>Identity below the threshold (default 97%) turns the sequence
<span style="color:{RED}">red</span> in step 3 - pick a closer hit here.</li>
<li>Genome-scale records (Ratio &gt; 2) are fine.</li>
</ul>

<h3>Common problems</h3>
{_fix_table((
    ("Start Annotation is disabled", "Every sequence needs at least one reference - "
                                     "check hits or use View match."),
    ("[seq] no reference chosen - skipped", "No BLAST hits - back to step 1."),
    ("Failed vs ACCESSION", "Reference download failed - press Start Annotation "
                            "again once the network is back."),
))}
"""),
    "page_review": ("How to use: Review Annotation", f"""
<h3>What this page does</h3>
<p>Compare the transferred annotation, fix what is wrong, and adopt one result
per sequence for export. Every edit is re-validated automatically.</p>

<h3>Status colors</h3>
{_table(("Status", "Meaning"),
        ((_status_chip("green"), "No problems - nothing to do."),
         (_status_chip("yellow"), "Exportable, but read the issues first."),
         (_status_chip("red"), "Fix it or confirm knowingly - export blocked "
                               "until then.")),
        widths=(175,))}

<h3>How to use</h3>
<ol>
<li><b>Pick a sequence</b> on the left; <b>Annotation results</b> lists one row
per reference. Click a row to inspect it; tick the <b>Use</b> radio to adopt it
for export.</li>
<li><b>Edit cells directly</b> - Type, Strand, Coordinates, Qualifiers.
Re-validation runs ~0.6 s after you stop typing.</li>
<li><b>Add feature</b> / <b>Delete row</b> manage rows (the source row is
protected); <b>View alignment</b> checks exon boundaries against the reference.</li>
<li><b>Confirm for export</b> - required for red, optional for yellow, disabled
for green.</li>
</ol>

<h3>Terms</h3>
{_terms_table((
    ("Identity", "Whole-query identity vs the chosen reference, <b>recomputed by "
                 "the app</b> (Smith-Waterman, strand auto-detected) right before "
                 "annotation transfer: same bases / aligned positions, gaps "
                 "excluded. Compared with the identity threshold - and not "
                 "identical with step 1's Ident % (local HSP, gaps included), so "
                 "the two numbers need not match."),
    ("Partial (&lt;1 / &gt;520)", "Ends cut by the primers - normal for amplicons."),
    ("codon_start", "First complete codon in a 5'-partial CDS (1/2/3) - derived "
                    "automatically."),
    ("transl_table", "Genetic code used to translate a CDS - taken from the "
                     "reference."),
    ("Variants", "Per-reference results; exactly one is adopted (Use) per "
                 "sequence."),
    ("Re-check all", "Re-validates every annotated sequence with the current "
                     "settings."),
))}

<h3>Tips</h3>
<ul>
<li>Coordinates syntax: <code>&lt;1..300, 401..520</code> - commas split exons,
"&lt;" / "&gt;" mark partial ends.</li>
<li>Hover the <b>Issues</b> column for the full findings with suggested fixes.</li>
</ul>

<h3>Common problems</h3>
{_fix_table((
    ("Cells are read-only", "Loaded from a .fap.json without alignment context - "
                            "re-annotate on step 2."),
    ("Still red after an edit", "Wait ~0.6 s; hover Issues for the exact problem."),
    ("Export blocked on step 4", "A red sequence is unconfirmed - press Confirm "
                                 "for export here."),
))}
"""),
    "page_export": ("How to use: Export Results", f"""
<h3>What this page does</h3>
<p>Write one <b>five-column .tbl</b> (BankIt format) per sequence, from the
variant adopted in step 3, plus a summary <code>all_features.tbl</code>
concatenating every record.</p>

<h3>How to use</h3>
<ol>
<li><b>Set the output directory</b> and press <b>Export Feature Table</b> - one
<code>&lt;SeqID&gt;.tbl</code> per annotated sequence plus the combined
<code>all_features.tbl</code> (overwrites existing files).</li>
<li><b>Open output folder</b> shows the results in Explorer.</li>
<li>Unconfirmed red sequences block the export - confirm them on step 3.</li>
</ol>

<h3>What's next (BankIt)</h3>
<ul>
<li>Start a nucleotide submission in the NCBI <b>BankIt</b> portal; upload the
.tbl files <b>and your original FASTA</b> - for a multi-sequence submission the
combined <code>all_features.tbl</code> can replace the per-sequence files.</li>
<li>Organism and source modifiers (isolate, country, collection date, ...) are
collected by the portal - deliberately not part of the .tbl.</li>
</ul>

<h3>Terms</h3>
{_terms_table((
    (".tbl", "Five-column feature table (start, stop, feature key, qualifiers) - "
             "features only, no sequence."),
    ("all_features.tbl", "Summary feature table: every sequence's &gt;Feature "
                         "record in one file, ready for a multi-record BankIt "
                         "submission."),
    ("BankIt portal", "NCBI's web submission wizard; pairs the .tbl with your "
                      "FASTA and adds the source information."),
    ("Adopted variant", "The result ticked in Use on step 3 - the one exported."),
    ("Confirmed", "Yes = red status knowingly accepted on step 3."),
))}

<h3>Tips</h3>
<ul>
<li><b>Re-export after any edit</b> in step 3 - files always reflect the current
tables.</li>
</ul>

<h3>Common problems</h3>
{_fix_table((
    ("Export blocked", "Red sequences lack confirmation - confirm them on step 3."),
    ("Could not write to '&lt;dir&gt;'", "Invalid or read-only directory - pick "
                                         "another one."),
    ("Nothing to export yet", "Annotate sequences in steps 1-3 first."),
))}
"""),
}


def build_page_help_dialog(term: str, parent=None) -> QDialog:
    """构建页面指南弹窗（统一样式、可滚动）；供 show_page_help 与测试使用。"""
    title, body = PAGE_HELP[term]
    page, subtitle = _PAGE_META[term]
    html = _wrap(page, subtitle, body,
                 footer="The full user guide is in menu ▸ Guide.")
    return _help_dialog(title, html, (720, 600), parent)


def show_page_help(term: str, parent=None):
    """弹出某页的使用指南（How to use / Terms / Tips / Common problems）。"""
    build_page_help_dialog(term, parent).exec()


# ---- 术语词条（就地解释）：统一弹窗样式 ----
_EX_PARTIAL = ('Example: <code>&lt;1..520</code> reads "starts upstream of base 1, '
               "ends at base 520\" - the 5' end was cut by the primer.")

_CODON_ROWS = _table(("codon_start", "Meaning"),
                     (("<b>1</b>", "The first base of the sequence is the first base "
                                   "of a codon."),
                      ("<b>2</b>", "Skip 1 base - the sequence starts 1 base into a "
                                   "codon."),
                      ("<b>3</b>", "Skip 2 bases - the sequence starts 2 bases into a "
                                   "codon.")),
                     widths=(130,))

_CODE_ROWS = _table(("Code", "Genetic code", "Typical use"),
                    (("<b>1</b>", "standard", "nuclear fungal genes: tef1, rpb2, "
                                              "tub2, act, ..."),
                     ("<b>12</b>", "alternative yeast (CTG = Ser)",
                      "Candida and relatives - the classic trap!"),
                     ("<b>4</b>", "mold mitochondria", "mitochondrial markers of molds"),
                     ("<b>3</b>", "yeast mitochondria", "mitochondrial markers of yeasts")),
                    widths=(60, 200, 220))

HELP = {
    "partial": ("Partial feature",
                "<p>A <b>partial feature</b> is one whose ends do not reach a natural "
                "gene boundary. PCR amplicons almost never contain a complete gene, so "
                "features touching the first/last base of your sequence are marked "
                "partial by writing <code>&lt;1</code> or <code>&gt;520</code> in the "
                "five-column table.</p>"
                + _note(_EX_PARTIAL)
                + "<p>This is expected and correct for amplicon submissions - GenBank "
                  "reviewers know the ends are cut by the primers.</p>"),
    "codon_start": ("codon_start",
                    "<p><b>codon_start</b> tells GenBank where the first <i>complete</i> "
                    "codon begins inside a 5'-partial CDS. This tool derives it "
                    "automatically from the reference CDS frame - you normally never "
                    "edit it, and it only matters for 5'-partial CDS.</p>"
                    + _CODON_ROWS),
    "transl_table": ("transl_table (genetic code)",
                     "<p><b>transl_table</b> selects the genetic code used to translate "
                     "a CDS:</p>" + _CODE_ROWS
                     + _note("Using the wrong table silently mistranslates the protein - "
                             "the tool takes the table from the reference record and "
                             "warns when it conflicts with the marker preset.", "warn")),
    "identity": ("identity threshold",
                 "<p>The <b>nucleotide identity</b> between your sequence and the chosen "
                 "reference must be above this threshold (default 97%) before annotation "
                 "is transferred without a red flag - this is the whole-query value "
                 "recomputed on step 3 (the Identity column there), not the step-1 "
                 "BLAST Ident %.</p>"
                 "<p>Below the threshold the sequence is flagged " + _status_chip("red")
                 + " on step 3: a distant reference may have misplaced exon boundaries, "
                   "so a human should confirm the choice.</p>"
                 + _note("Change the threshold in menu ▸ Settings; press "
                         "<b>Re-check all</b> on step 3 to re-evaluate existing results.")),
}


def build_term_help_dialog(term: str, parent=None) -> QDialog:
    """构建术语词条弹窗（统一样式）；供 show_help 与测试使用。"""
    title, body = HELP[term]
    html = _wrap(title, "Glossary · what the term means in this tool", body)
    return _help_dialog(title, html, (620, 440), parent)


def show_help(term: str, parent=None):
    """按词条名弹出富文本术语解释（issue 行点击等入口共用）。"""
    build_term_help_dialog(term, parent).exec()


# ---- 全软件使用指南（菜单 Guide）----
_APP_STEPS = _table(
    ("Step", "Page", "What you do", "What you get"),
    ((_chip("1", "#ffffff", ACCENT), "<b>Import &amp; BLAST</b>",
      "Paste or drop FASTA, press <b>BLAST</b>",
      "A ranked hit list per sequence"),
     (_chip("2", "#ffffff", ACCENT), "<b>Select Reference</b>",
      "Check 1-5 references, press <b>Start Annotation</b>",
      "Validated gene models per reference"),
     (_chip("3", "#ffffff", ACCENT), "<b>Review Annotation</b>",
      "Fix issues, adopt one result per sequence",
      "An adopted annotation per sequence"),
     (_chip("4", "#ffffff", ACCENT), "<b>Export Results</b>",
      "Pick a folder, press <b>Export Feature Table</b>",
      "&lt;SeqID&gt;.tbl files for BankIt")),
    widths=(70, 150, 220, 200))

_APP_STATUS = _table(
    ("Status", "Meaning"),
    ((_status_chip("green"), "No problems - nothing to do."),
     (_status_chip("yellow"), "Exportable, but read the issues first."),
     (_status_chip("red"), "Fix or confirm knowingly - export blocked until "
                           "then.")),
    widths=(175,))

APP_GUIDE = ("User Guide", f"""
<h3>What this tool does</h3>
<p>For each fungal marker amplicon, find a close reference on NCBI, transfer its
annotation, review and fix it, and export the <b>five-column .tbl</b> that NCBI
BankIt expects - one file per sequence.</p>

<h3>The four-step workflow</h3>
{_APP_STEPS}
<p style="margin-top:8px;">{_note("Steps unlock in order - hover a locked step for the reason; click any unlocked step to jump.")}</p>

<h3>Settings</h3>
<p>Four settings - everything else runs on sensible defaults:</p>
<ul>
<li><b>NCBI contact email</b> - required for the online BLAST.</li>
<li><b>identity threshold (97%)</b> - below it a sequence is flagged red.</li>
<li><b>References compared per sequence (1-5)</b> - pre-checked on step 2.</li>
<li><b>Concurrent BLAST submissions (1-4)</b> - parallel jobs speed up batches;
submissions stay rate-limited.</li>
</ul>

<h3>Review status at a glance</h3>
{_APP_STATUS}
<p style="margin-top:6px;">The same colors run through step 3 (list and ribbon),
step 4 (summary) and the status bar.</p>

<h3>Getting the submission out</h3>
<p>One <code>&lt;SeqID&gt;.tbl</code> per sequence from the adopted variant. In
the <b>BankIt</b> portal upload them with your original FASTA; organism and
source modifiers are entered there.</p>

<h3>Good to know</h3>
<ul>
<li><b>BLAST again</b> skips sequences with hits; <b>STOP</b> cancels the rest.</li>
<li><b>Re-export</b> after edits on step 3 - files are overwritten.</li>
<li>Nothing leaves your machine except the sequences sent to NCBI for BLAST.</li>
</ul>
{_note("Verify before submitting - annotation transfer is a drafting aid.", "danger")}
""")

_APP_SUBTITLE = ("MycoFACT · from raw amplicon "
                 "sequences to a BankIt-ready submission")


def build_app_guide_dialog(parent=None) -> QDialog:
    """构建全软件使用指南弹窗（菜单 Guide 的内容）。"""
    title, body = APP_GUIDE
    html = _wrap(title, _APP_SUBTITLE, body,
                 footer="Every page also has its own <b>Help</b> button with "
                        "step-specific guidance.")
    return _help_dialog(title, html, (800, 640), parent)


def show_app_guide(parent=None):
    """弹出全软件使用指南（菜单 Guide）。"""
    build_app_guide_dialog(parent).exec()
