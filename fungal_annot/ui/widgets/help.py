"""帮助卡片（Phase 3 新手友好）：术语就地解释（§7.2/§11）。"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QToolButton

# "Marker" 列的就地解释（第 1/2/4 页共用）：说明自动判定机制与其影响
MARKER_HINT = ("Marker gene preset (tef1, act, LSU...) chosen automatically from BLAST "
               "hit titles during annotation - it controls which features are "
               "transferred (CDS vs rRNA) and the genetic code. Shows 'auto-detect' "
               "until then.")

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
