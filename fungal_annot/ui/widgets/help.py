"""帮助卡片（Phase 3 新手友好）：术语就地解释（§7.2/§11）。"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QMessageBox,
                             QTextBrowser, QToolButton, QVBoxLayout)

# "Marker" 列的就地解释（第 1/2/4 页共用）：说明自动判定机制与其影响
MARKER_HINT = ("Marker gene preset (tef1, act, LSU...) chosen automatically from BLAST "
               "hit titles during annotation - it controls which features are "
               "transferred (CDS vs rRNA) and the genetic code. Shows 'auto-detect' "
               "until then.")

# 红绿灯状态的配色与动作化文案（第 3/4 页共用，与 status_colors 帮助卡一致）
STATUS_COLOR = {"green": "#1a7f37", "yellow": "#9a6700", "red": "#cf222e"}
STATUS_MARK = {"green": "✓ Ready", "yellow": "⚠ Warnings", "red": "✗ Needs review"}
STATUS_HINT = {"green": "Ready", "yellow": "Ready - review the warnings below",
               "red": "Needs review - fix it or confirm before export"}

HELP = {
    "status_colors": (
        "Traffic-light status",
        "<p>Every sequence gets one of three statuses after annotation - and again "
        "after every edit:</p>"
        "<ul>"
        "<li><b style='color:#1a7f37'>✓ Ready</b> — no problems found. Nothing to do.</li>"
        "<li><b style='color:#9a6700'>⚠ Warnings</b> — the table can be exported, but "
        "read the warnings first (they are often expected for partial amplicons). "
        "Confirming is optional.</li>"
        "<li><b style='color:#cf222e'>✗ Needs review</b> — an error was detected. Fix it "
        "in the feature table, or press <b>Confirm for export</b> to accept it "
        "knowingly; export stays blocked until then.</li>"
        "</ul>"),
    "partial": (
        "Partial feature",
        "<p>A <b>partial feature</b> is one whose ends do not reach a natural gene boundary. "
        "PCR amplicons almost never contain a complete gene, so features touching the "
        "first/last base of your sequence are marked partial by writing "
        "<code>&lt;1</code> or <code>&gt;520</code> in the five-column table.</p>"
        "<p>This is expected and correct for amplicon submissions — GenBank reviewers "
        "know the ends are cut by the primers.</p>"),
    "codon_start": (
        "codon_start",
        "<p><b>codon_start</b> tells GenBank where the first <i>complete</i> codon begins inside a "
        "5'-partial CDS: <code>1</code> = first base, <code>2</code> = skip 1 base, <code>3</code> = skip 2 bases.</p>"
        "<p>Example: if your fragment starts 2 bases into a codon, the first complete codon "
        "begins at base 2, so <code>codon_start=2</code>. This tool derives it automatically from "
        "the reference CDS frame (plan §2.1).</p>"),
    "transl_table": (
        "transl_table (genetic code)",
        "<p><b>transl_table</b> selects the genetic code used to translate a CDS:</p>"
        "<ul>"
        "<li><code>1</code> — standard code (nuclear fungal genes: tef1, rpb2, tub2 ...)</li>"
        "<li><code>12</code> — alternative yeast code, CTG = Ser (Candida and relatives!)</li>"
        "<li><code>4</code> — mold mitochondria; <code>3</code> — yeast mitochondria</li>"
        "</ul>"
        "<p>Using the wrong table silently mistranslates the protein — this tool takes the "
        "table from the reference record and warns when it conflicts with the preset.</p>"),
    "identity": (
        "identity threshold",
        "<p>The <b>nucleotide identity</b> between your sequence and the chosen reference must be "
        "above this threshold (default 97%) before annotation is transferred automatically.</p>"
        "<p>Below the threshold the sequence is flagged RED: a distant reference may have "
        "misplaced exon boundaries, so a human should confirm the choice.</p>"),
    "hit_columns": (
        "Hit table columns",
        "<p><b>Cover %</b> — percentage of your query covered by the hit (BLAST qcovs); "
        "100% is required for reliable end annotation.</p>"
        "<p><b>Ratio</b> — reference length / query length (Len ratio). About 1.0–1.5 is "
        "ideal: your amplicon sits <i>inside</i> the reference with flanking context on "
        "both sides. Values far above 2 indicate a genome-scale record (windowed fetch "
        "will be used).</p>"
        "<p><b>Ident %</b> — nucleotide identity of the hit (BLAST pident).</p>"),
}


def show_help(term: str, parent=None):
    """按词条名弹出富文本术语解释（供 HelpButton 与 issue 行点击共用）。"""
    title, body = HELP[term]
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setTextFormat(Qt.TextFormat.RichText)
    box.setText(body)
    box.setIcon(QMessageBox.Icon.Information)
    box.exec()


class HelpButton(QToolButton):
    """'? 按钮：点击弹出富文本术语解释。"""

    def __init__(self, term: str, parent=None):
        super().__init__(parent)
        self.term = term
        self.setText("?")
        self.setFixedSize(22, 22)
        self.setToolTip("What is this?")
        self.clicked.connect(self._show)

    def _show(self):
        show_help(self.term, self)


# ---- 页面指南（每页按钮区的 Help 按钮）：How to use / Terms / Tips 三段式 ----
PAGE_HELP = {
    "page_import": (
        "How to use: Import & BLAST",
        "<h3>What this page does</h3>"
        "<p>Bring your sequences into the project and find close references with an "
        "online BLAST search.</p>"
        "<h3>How to use</h3>"
        "<ul>"
        "<li><b>Paste</b> FASTA text (one or more entries) or a bare DNA sequence into "
        "the box; <b>drag &amp; drop</b> FASTA files onto it; or use <b>Browse</b>.</li>"
        "<li><b>Example</b> loads four demo sequences so you can try the whole workflow.</li>"
        "<li>Click <b>BLAST</b>: the box content is imported automatically and the "
        "search queue starts. It runs serially (~1-5 min per sequence, NCBI rate "
        "limits); when the queue drains the app moves to step 2 on its own.</li>"
        "<li>The table lists every imported sequence: ID, length, marker and BLAST "
        "state. <b>Double-click a Seq ID to rename</b> it (hits, results and "
        "confirmations follow the new name); <b>✕</b> removes a sequence.</li>"
        "</ul>"
        "<h3>Terms</h3>"
        "<ul>"
        "<li><b>FASTA</b> - plain-text sequence format; every entry starts with a "
        "\"&gt;\" header line.</li>"
        "<li><b>Marker</b> - which locus a sequence is (tef1, act, LSU ...). Detected "
        "automatically from BLAST titles during annotation; it decides which features "
        "are transferred (CDS vs rRNA) and the genetic code.</li>"
        "<li><b>NCBI email</b> - required by NCBI for online BLAST; set it in "
        "Tools ▸ Settings before your first search.</li>"
        "</ul>"
        "<h3>Tips</h3>"
        "<ul>"
        "<li>Seq IDs must be unique (letters, digits and . _ : - | +) - they become "
        "the file names of the exported .tbl.</li>"
        "<li>Clicking BLAST again skips sequences that already have hits, so you can "
        "add latecomers and search only those.</li>"
        "<li>Long runs of N near feature ends are flagged later in step 3.</li>"
        "</ul>"),
    "page_reference": (
        "How to use: Select Reference",
        "<h3>What this page does</h3>"
        "<p>For each sequence, pick the reference record whose annotation will be "
        "transferred to it.</p>"
        "<h3>How to use</h3>"
        "<ul>"
        "<li>Select a sequence on the left; the hit table shows its BLAST hits.</li>"
        "<li>Click the radio button in the <b>Use</b> column. The first row is "
        "pre-selected - the <b>recommended</b> hit (blue row): best identity, full "
        "coverage, culture/type strains preferred, length ratio in the 1.0-1.5 sweet "
        "spot.</li>"
        "<li><b>Use recommended for all</b> accepts the top hit for every sequence.</li>"
        "<li><b>View match</b> lists each sequence's current reference accession - edit "
        "any of them, or clear a row to fall back to the recommended hit.</li>"
        "<li><b>Start Annotation</b> downloads each reference, transfers gene/CDS (or "
        "rRNA) features onto your sequence and validates them - then step 3 opens. "
        "Re-running it overwrites previous results with fresh ones.</li>"
        "</ul>"
        "<h3>Terms</h3>"
        "<ul>"
        "<li><b>Ident %</b> - nucleotide identity between the hit and your sequence.</li>"
        "<li><b>Cover %</b> - how much of your sequence the hit covers; 100% is needed "
        "for reliable end annotation.</li>"
        "<li><b>Ratio</b> - reference length / your length. 1.0-1.5 is ideal (your "
        "amplicon sits inside the reference); far above 2 marks a genome-scale record "
        "(a matching window is fetched automatically).</li>"
        "<li><b>Accession</b> - the stable record ID (e.g. MZ123456.1). You may also "
        "type one yourself in View match - it does not have to be in the hit list.</li>"
        "</ul>"
        "<h3>Tips</h3>"
        "<ul>"
        "<li>Prefer hits marked with a star (culture / type strains) - names follow "
        "the strain.</li>"
        "<li>Identity below the threshold (default 97%) turns the sequence red in "
        "step 3 - pick a closer hit here.</li>"
        "<li>Large genome records (Ratio &gt; 2) are fine: only the matching region "
        "is fetched and the rest is discarded.</li>"
        "</ul>"),
    "page_review": (
        "How to use: Review Annotation",
        "<h3>What this page does</h3>"
        "<p>Check the transferred annotation, fix what is wrong, and confirm what you "
        "accept. Every edit is re-validated automatically.</p>"
        "<h3>Status colors</h3>"
        "<ul>"
        "<li><b style='color:#1a7f37'>✓ Ready</b> - no problems found; nothing to "
        "do.</li>"
        "<li><b style='color:#9a6700'>⚠ Warnings</b> - exportable, but read the issues "
        "first; confirming is optional.</li>"
        "<li><b style='color:#cf222e'>✗ Needs review</b> - an error was detected; fix "
        "it or press Confirm. Export stays blocked until then.</li>"
        "</ul>"
        "<h3>How to use</h3>"
        "<ul>"
        "<li>Edit cells directly: <b>Type</b> (CDS, gene, rRNA ...), <b>Strand</b> "
        "(+/-), <b>Coordinates</b>, <b>Qualifiers</b>. Re-validation runs about 0.6 s "
        "after you stop typing and the status updates everywhere.</li>"
        "<li><b>Add feature</b> inserts a CDS row spanning the whole sequence; "
        "<b>Delete row</b> removes the selected rows. The source row is managed for "
        "you.</li>"
        "<li><b>View alignment</b> lays the reference against your sequence (\"|\" = "
        "match) - use it to check exon boundaries and indels. <b>View reference "
        "features</b> shows the reference's own table for comparison.</li>"
        "<li>The <b>Issues</b> list explains every finding with a suggested action. "
        "Click an issue to jump to the related feature row and/or open a glossary "
        "card.</li>"
        "<li><b>Confirm for export</b>: required for red sequences (accept knowingly - "
        "an optional note goes to the log), optional for yellow, disabled when "
        "green.</li>"
        "</ul>"
        "<h3>Terms</h3>"
        "<ul>"
        "<li><b>Partial (&lt;1 / &gt;520)</b> - feature ends cut by the primers; "
        "normal for amplicons and expected by GenBank.</li>"
        "<li><b>codon_start</b> - where the first complete codon starts inside a "
        "5'-partial CDS (1, 2 or 3).</li>"
        "<li><b>Re-check all</b> - re-runs validation on every annotated sequence with "
        "the current settings (e.g. after changing the identity threshold).</li>"
        "</ul>"
        "<h3>Tips</h3>"
        "<ul>"
        "<li>Coordinates syntax: <code>&lt;1..300, 401..520</code> - commas separate "
        "exons, \"&lt;\" / \"&gt;\" mark partial ends.</li>"
        "<li>Project files (.fap.json) do not store the alignment context, so editing "
        "is disabled there - re-annotate in step 2 to restore it.</li>"
        "<li>Red sequences stay blocked on step 4 until confirmed - by design, since "
        "NCBI reviewers reject silent errors.</li>"
        "</ul>"),
    "page_export": (
        "How to use: Export Results",
        "<h3>What this page does</h3>"
        "<p>Write one five-column .tbl file per sequence (BankIt format).</p>"
        "<h3>How to use</h3>"
        "<ul>"
        "<li>Set the <b>output directory</b>, then <b>Export all</b>. Files are named "
        "&lt;SeqID&gt;.tbl and are overwritten on re-export.</li>"
        "<li><b>Open output folder</b> opens the directory in Windows Explorer.</li>"
        "<li>Sequences marked <b>Needs review</b> must be confirmed on the Review page "
        "first - export is blocked otherwise.</li>"
        "</ul>"
        "<h3>What's next (BankIt)</h3>"
        "<ul>"
        "<li>Go to the NCBI <b>BankIt</b> portal and start a nucleotide submission "
        "(GB2sequin-style workflow).</li>"
        "<li>Upload the .tbl files and your original FASTA sequences when the portal "
        "asks for them.</li>"
        "<li>The portal form collects <b>organism and source modifiers</b> (isolate, "
        "country, collection date ...) - they are intentionally not part of the "
        ".tbl. Let the portal validate, then submit.</li>"
        "</ul>"
        "<h3>Terms</h3>"
        "<ul>"
        "<li><b>.tbl</b> - five-column feature table: start, stop, feature key and "
        "qualifiers (BankIt format).</li>"
        "<li><b>BankIt portal</b> - NCBI's web submission wizard; it pairs your .tbl "
        "with the FASTA sequence and adds the source information.</li>"
        "</ul>"
        "<h3>Tips</h3>"
        "<ul>"
        "<li>Export again after any edit in step 3 - the files always reflect the "
        "current tables.</li>"
        "<li>Statuses shown here were last re-checked on the Review page; re-export "
        "after any change.</li>"
        "</ul>"),
}


def build_page_help_dialog(term: str, parent=None) -> QDialog:
    """构建页面指南弹窗（富文本、可滚动）；供 show_page_help 与测试使用。"""
    title, html = PAGE_HELP[term]
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(680, 560)
    v = QVBoxLayout(dlg)
    browser = QTextBrowser()
    browser.setOpenExternalLinks(False)
    browser.setHtml(html)
    v.addWidget(browser, 1)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    bb.rejected.connect(dlg.reject)
    v.addWidget(bb)
    return dlg


def show_page_help(term: str, parent=None):
    """弹出某页的使用指南（How to use / Terms / Tips）。"""
    build_page_help_dialog(term, parent).exec()
