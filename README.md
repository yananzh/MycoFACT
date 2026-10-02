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

Tailored presets cover the common markers: 5.8S, LSU, SSU, tef1, rpb1, rpb2, tub2,
tub1, act, cal, chs, gapdh, his3, tsr1, mcm7, plus mitochondrial markers (mtLSU, mtSSU,
cox1, cob, nad1/nad2/nad4/nad5, atp6, rps3 — all flagged for manual confirmation). Genes
outside this list are supported too: they fall back to the Generic preset (broad feature
whitelist, codon table taken from the reference record).

## How it works

> [!IMPORTANT]
> **Check Sanger trace quality before annotating.** Open each chromatogram (.ab1) in
> a trace viewer such as [SnapGene](https://www.snapgene.com/), Chromas or 4Peaks,
> inspect the peak quality, and trim the low-quality ends — the noisy stretch right
> after the primer and the deteriorating tail. Import only the clean, high-confidence
> region as FASTA: the annotation is transferred onto exactly the bases you supply,
> so inaccurate input produces inaccurate feature tables.

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
  BLAST), or a local reference GenBank file for fully offline runs (GUI and CLI).
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
load the built-in demo (`demo/example.fasta`). To skip BLAST, click **Use reference**,
then either enter accessions through **View match**, or click **Local GenBank** on
step 2 for fully offline annotation. A local reference is applied to all imported
sequences; per-sequence reference selection can be adjusted before annotation.

Use **Save / Save As** to save a JSON project and **Open** to resume it. The project
includes imported sequences, unimported text, references, results, confirmations,
settings, and the task log. Restored annotations are read-only until re-annotated
because alignment context is not serialized. **Log** retains task messages and
failure details. Closing or replacing a modified project offers Save / Discard / Cancel.

Edits show **Awaiting validation** until rechecked. Export completes validation first;
invalid cell syntax must be corrected. Confirmation applies to the adopted result and
is invalidated by edits, reference changes, re-annotation, or validation changes.

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
| `.mycofact-outputs.json` | Internal output manifest; keep it in the output directory, do not upload it to BankIt |

Exports are staged before replacing the previous batch. Re-exporting into the same
directory updates unchanged files listed in the manifest and removes obsolete outputs,
including tables for sequences that now fail. Manually modified files and existing
files without a manifest are preserved: choose a new output directory in that case.
For output folders created by an earlier version, use a new empty directory.

Sequences for which nothing could be transferred (no feature matched the transfer
whitelist, or every candidate segment was dropped) are reported as errors and produce
**no `.tbl`/`.fsa`** — an empty `>Feature` stub is rejected by BankIt, so a missing file
means "this one needs attention", not "this one is fine".

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
