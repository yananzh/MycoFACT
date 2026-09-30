<div align="right">

English | [简体中文](./README.zh-CN.md)

</div>

<div align="center">

<img src="assets/logos/logo_a_helix_mushroom_preview.png" alt="MycoFACT logo" width="128"/>

# MycoFACT

[![CI](https://github.com/yananzh/MycoFACT/actions/workflows/ci.yml/badge.svg)](https://github.com/yananzh/MycoFACT/actions/workflows/ci.yml)
[![Build](https://github.com/yananzh/MycoFACT/actions/workflows/build.yml/badge.svg)](https://github.com/yananzh/MycoFACT/actions/workflows/build.yml)

**Automatic feature table generation for fungal multi-locus identification sequences**

</div>

**MycoFACT** (**F**ungal **F**eature **A**nnotation & **C**omparison **T**ool, package
`fungal_annot`) prepares fungal marker gene sequences for NCBI BankIt submission. Pick a
reference record, and its GenBank annotations are transferred onto your query sequences
along the alignment coordinates — producing the five-column feature tables (.tbl) ready
for submission. The CLI additionally emits paired .fsa files and a validation report;
the GUI exports .tbl only.

Tailored presets cover the common markers: ITS (incl. 5.8S), LSU, SSU, tef1, rpb1, rpb2,
tub2, tub1, act, cal, chs, gapdh, his3, tsr1, mcm7, plus the standard mitochondrial set
(mtLSU, mtSSU, cox1/cox2/cox3, cob, nad1/nad2/nad3/nad4/nad4L/nad5/nad6, atp6/atp8/atp9,
rps3 — all flagged for manual confirmation). Genes outside this list are supported too:
they fall back to the Generic preset (broad feature whitelist, codon table taken from
the reference record).

## How it works

1. **Import & BLAST** — paste, drag & drop, or browse your FASTA; hits come back ranked.
2. **Reference selection** — pick the reference record in the hit table (a recommended
   row is pre-selected).
3. **Annotation review** — the transferred feature table is editable; every edit is
   revalidated instantly, an alignment view assists checking, and red-flagged items must
   be manually acknowledged.
4. **Validation & export** — a five-column feature table per sequence plus a combined
   multi-record feature table (GUI writes `.tbl` only; the CLI additionally emits paired
   `.fsa` files and a validation report CSV).

A horizontal step bar at the top of the window lets you jump to any unlocked step, and
projects can be saved (JSON) and resumed at any time. BLAST and parsing run in background
threads, so the UI stays responsive.

## Features

- **Reference annotation transfer** — reference GenBank annotations are mapped onto query
  sequences along alignment coordinates, producing BankIt-portal-format five-column
  feature tables (features such as gene/CDS only; organism info is entered in the BankIt
  portal form).
- **Multi-gene presets** — the gene type is auto-detected from BLAST hit titles or the
  reference annotation, with a generic preset as fallback.
- **Three ways to specify the reference** — online BLAST, direct accession input (skips
  BLAST), or a local reference GenBank file for fully offline runs (CLI only).
- **Instant revalidation of edits** — red-flagged items require manual confirmation
  before export.

## Installation

Requires Python ≥ 3.10 (CI runs on 3.12, covering Windows / macOS / Linux).

```bash
git clone https://github.com/yananzh/MycoFACT.git
cd MycoFACT
pip install -r requirements.txt
```

Ready-to-run builds: the `Build` workflow packages the app with PyInstaller (--onedir) on
every push to `main` and on `v*` tags, producing Windows zip / macOS .app zip /
Linux tar.gz; pushing a tag (e.g. `v0.1.0`) attaches them to a GitHub Release.

> [!WARNING]
> Binaries are currently unsigned. Windows SmartScreen shows a warning on first launch
> ("More info" → "Run anyway"); on macOS, right-click → Open on first start.

The app icon (mushroom + DNA helix, [assets/logos](assets/logos)) ships on all three
platforms: embedded `.ico` in the Windows executable, `.icns` in the macOS bundle, and
multi-size PNGs as the window/taskbar icon everywhere. Regenerate the icon files from the
SVG with `python scripts/build_icons.py` (needs PyQt6 + Pillow).

## Usage

### Graphical interface

```bash
python main.py
```

This opens the four-step wizard described above. Click **Example** on the first page to
load the built-in demo (`demo/example.fasta`) and explore the wizard; annotation itself
requires online BLAST or a reference accession (fully offline runs are CLI only, via
`--ref-gb`).

### Command line

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

# Online mode: pick the reference via BLAST
python main.py run --input seqs.fasta --out outdir --gene-type tef1 --email you@example.org

# Specify the reference accession directly (skips BLAST)
python main.py run --input seqs.fasta --out outdir --gene-type tef1 --accession LCxxxxxx.1

# List all gene presets
python main.py presets
```

> [!NOTE]
> Online BLAST requires network access, and NCBI requires a contact email
> (`--email`). Optional flags: `--api-key` (higher Entrez rate limit), `--organism`
> (Entrez filter, e.g. `Fusarium`), `--db` (BLAST database, default `core_nt`),
> `--identity` (hit identity threshold, default 97), and `--no-auto-partial`
> (disable auto-partial for features touching sequence ends).

### Output

| File | Description |
| ---- | ----------- |
| `<SeqID>.tbl` + `<SeqID>.fsa` | Feature table and paired FASTA per sequence |
| `all_features.tbl` | All annotated records' `>Feature` blocks combined into a single multi-record file, uploadable as a whole to BankIt (omitted when no sequence produced features) |
| `validation_report.csv` | Overall validation report |

## Project structure

```text
MycoFACT/
├── main.py                # Entry point: python main.py → GUI; run / presets → CLI
├── fungal_annot/
│   ├── core/              # Core layer: BLAST, reference fetching, annotation
│   │                      #   transfer, validation, .tbl writing
│   ├── services/          # Pipeline, background threads, project JSON persistence
│   ├── ui/                # PyQt6 four-page wizard UI
│   ├── resources/         # Stylesheets, icons, gene presets
│   └── tests/             # pytest tests
├── scripts/
│   ├── make_demo.py       # One-shot demo data generator
│   └── build_icons.py     # Icon regeneration from the SVG logo
└── demo/                  # Built-in examples (query FASTA / reference GenBank)
```

## Status

- **Core + CLI + tests** (M0–M2) and the **PyQt6 wizard UI** (M3–M5: background thread
  queue, project JSON persistence, instant revalidation of review edits) are complete.
  (The previously announced in-app table2asn preflight entry was dropped: organism info
  is entered in the BankIt portal form, so a preflight pass does not apply.)
- **To do**: online BLAST validation against the live NCBI service (a gold-standard set
  of real lab sequences is recommended), a table2asn CI gate (requires a BankIt template
  .sbt), and Windows code signing / macOS notarization.

Run the test suite with:

```bash
pytest
```
