<div align="right">

English | [简体中文](./README.zh-CN.md)

</div>

# MycoFACT — Automatic Feature Table Generation for Fungal Multi-locus Identification Sequences

[![CI](https://github.com/yananzh/MycoFACT/actions/workflows/ci.yml/badge.svg)](https://github.com/yananzh/MycoFACT/actions/workflows/ci.yml)
[![Build](https://github.com/yananzh/MycoFACT/actions/workflows/build.yml/badge.svg)](https://github.com/yananzh/MycoFACT/actions/workflows/build.yml)

**MycoFACT** (**F**ungal **F**eature **A**nnotation & **C**omparison **T**ool, package
`fungal_annot`) uses "reference annotation transfer" to automatically generate NCBI
five-column feature tables (.tbl) for fungal marker gene sequences (LSU/SSU/tef1/rpb1/rpb2/
tub2/act/cal/chs and mitochondrial markers), together with the paired .fsa files and a
validation report required for BankIt submission.

## ✨ Features

- **Reference annotation transfer**: after a reference sequence is selected via BLAST, the
  annotations of the reference GenBank record are transferred to the query sequences along
  the alignment coordinates, producing a five-column feature table (.tbl) in BankIt portal
  format (features such as gene/CDS only; organism info is entered in the BankIt portal form).
- **Multi-gene presets**: built-in presets for LSU, SSU, tef1, rpb1, rpb2, tub2, act, cal, chs
  and mitochondrial markers; the gene type is auto-detected from BLAST hit titles or the
  reference annotation, falling back to a generic preset when unrecognized.
- **Three ways to specify the reference**: online BLAST (requires network; NCBI requires an
  email address), offline mode with a local reference GenBank file, or direct accession
  input to skip BLAST.
- **Four-step wizard GUI**: Import & BLAST → Reference Selection → Annotation Review →
  Validation & Export; a horizontal step bar at the top of the window lets you jump to any
  unlocked step.
- **Instant revalidation of edits**: the feature table is editable, and every edit is
  revalidated immediately; a comparison view assists manual review, and red-flagged items
  must be manually acknowledged before export.
- **Project save / resume**: save/open projects (JSON) from the File menu, and close and
  resume work at any time.
- **Background thread queue**: BLAST and parsing run in background threads, keeping the UI
  responsive.

## 📌 Status

- **M0–M2 completed**: all core/ layer modules + CLI + tests (milestones M0–M2, §8 of the
  design plan).
- **M3–M5 completed**: PyQt6 four-page wizard UI, background thread queue, project JSON
  persistence, instant revalidation of review edits, in-app table2asn preflight entry.
- **To do**: online BLAST validation against the live NCBI service (a gold-standard set of
  real lab sequences is recommended per plan M2), a table2asn CI gate (requires a BankIt
  template .sbt), and Windows code signing / macOS notarization.

## 📦 Installation

Requires Python ≥ 3.10 (CI runs on 3.12, covering Windows / macOS / Linux).

```bash
git clone https://github.com/yananzh/MycoFACT.git
cd MycoFACT
pip install -r requirements.txt
```

Ready-to-run builds: the `Build` workflow packages the app with PyInstaller
(--onedir) on every push and on `v*` tags, producing Windows zip / macOS .app zip
/ Linux tar.gz. Pushing a tag (e.g. `v0.1.0`) attaches them to a GitHub Release.
Binaries are currently unsigned: Windows SmartScreen shows a warning on first
launch ("More info" → "Run anyway"); on macOS, right-click → Open on first start.

## 🖥 Graphical Interface

```bash
python main.py        # launch the GUI
```

Four steps: import sequences and run BLAST (drag & drop / browse / paste FASTA or bare
sequences, or click **Example** to load the built-in demo demo/example.fasta; the wizard
advances automatically once the queue is drained) → reference selection (in-row single
choice in the hit table, recommended row pre-selected) → annotation review (editable
feature table, instant revalidation, alignment view, manual acknowledgment of red-flagged
items) → validation summary and export (.tbl + .fsa + combined table + report).

References are always resolved online (hit accession / direct download); the offline local
GenBank mode remains available only via the CLI `--ref-gb` option.

## ⌨️ Quick Start (CLI)

```bash
# One-shot demo: generates a reference GenBank file + two queries (forward strand with an
# insertion / reverse complement) and runs the pipeline end-to-end offline
python scripts/make_demo.py
python main.py run --input demo/tef1_queries.fasta --out demo_out --gene-type tef1 \
    --ref-gb demo/reference.gb

# Offline mode: use a local reference GenBank file (testing / no-network environments)
python main.py run --input seqs.fasta --out outdir --gene-type tef1 --ref-gb reference.gb
# When --gene-type is omitted it is auto-detected from hit titles / the reference
# annotation; falls back to the generic preset if unrecognized

# Online mode: pick the reference via BLAST (requires network; email is required by NCBI)
python main.py run --input seqs.fasta --out outdir --gene-type tef1 --email you@example.org

# Specify the reference accession directly (skips BLAST)
python main.py run --input seqs.fasta --out outdir --gene-type tef1 --accession LCxxxxxx.1

# List all gene presets
python main.py presets
```

## 📤 Output

- One `<SeqID>.tbl` (feature table) + one paired `<SeqID>.fsa` per sequence
- `all_features.tbl` — summary feature table: every annotated record's
  `>Feature` block in a single multi-record file, uploadable as a whole to
  BankIt (omitted when no sequence produced features)
- Overall validation report `validation_report.csv`

## ✅ Running Tests

```bash
pytest
```

## 📁 Project Structure

```text
MycoFACT/
├── main.py                # Entry point: python main.py → GUI; run / presets → CLI
├── fungal_annot/
│   ├── core/              # Core layer: BLAST, reference fetching, annotation
│   │                      #   transfer, validation, .tbl writing
│   ├── services/          # Pipeline, background threads, project JSON persistence
│   ├── ui/                # PyQt6 four-page wizard UI
│   ├── resources/         # Stylesheets, icons
│   └── tests/             # pytest tests
├── scripts/make_demo.py   # One-shot demo data generator
└── demo/                  # Built-in examples (query FASTA / reference GenBank)
```

## 📄 Design Document

The detailed design is described in the Chinese-language internal document
《真菌多基因序列FeatureTable工具-开发计划.md》(not included in this repository).
