"""命令行入口（M1–M2 交付物）。UI（M3–M5）复用 services/pipeline 同一编排。"""
import argparse
import os
import sys

from Bio import SeqIO

from .core.models import SeqInput
from .core.presets import load_presets
from .services.pipeline import PipelineConfig, annotate_sequence, write_outputs


def load_fasta(path: str) -> list[SeqInput]:
    seqs = []
    for rec in SeqIO.parse(path, "fasta"):
        seqs.append(SeqInput(seq_id=str(rec.id), seq=str(rec.seq).upper()))
    if not seqs:
        raise SystemExit(f"No sequences in FASTA: {path}")
    return seqs


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="fungal-annot",
        description="Fungal multi-locus feature table generator (reference annotation transfer)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="FASTA -> annotation transfer -> .tbl/.fsa + validation report")
    r.add_argument("--input", required=True, help="input FASTA (one or more sequences)")
    r.add_argument("--out", required=True, help="output directory")
    r.add_argument("--gene-type", required=True,
                   help="gene preset name (tef1/rpb2/LSU/cox1/..., see presets)")
    r.add_argument("--email", default="", help="NCBI contact email (required for online mode)")
    r.add_argument("--api-key", default="", help="Entrez API key (optional, higher rate limit)")
    r.add_argument("--organism", default="", help="BLAST Entrez query filter (e.g. 'Fusarium')")
    r.add_argument("--db", default="core_nt",
                   help="BLAST database (default core_nt; NCBI has merged nt into core_nt)")
    r.add_argument("--identity", type=float, default=97.0, help="nucleotide identity threshold (default 97)")
    r.add_argument("--ref-gb", default="", help="offline mode: local reference GenBank file")
    r.add_argument("--accession", default="", help="reference accession directly (skip BLAST)")
    r.add_argument("--source", default="",
                   help="source qualifiers applied to all sequences, semicolon-separated key=value,"
                        "e.g. 'organism=Fusarium sp.;strain=A1;country=China;"
                        "collection_date=2021-Mar'")
    r.add_argument("--no-auto-partial", action="store_true",
                   help="disable auto-partial for features touching sequence ends")

    sub.add_parser("presets", help="list gene presets")

    args = p.parse_args(argv)
    if args.cmd == "presets":
        for name, pr in load_presets().items():
            kind = pr.kind + ("/mito" if pr.mito else "")
            extra = " (manual confirm)" if pr.manual_confirm else ""
            print(f"{name:8s} {kind:12s} transl_table={pr.transl_table}{extra}")
        return 0

    seqs = load_fasta(args.input)
    src_quals = {}
    for kv in args.source.split(";"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            src_quals[k.strip()] = v.strip()
    for s in seqs:
        s.source_qualifiers.update(src_quals)
    cfg = PipelineConfig(
        email=args.email, api_key=args.api_key, organism_filter=args.organism,
        blast_db=args.db, identity_threshold=args.identity,
        auto_partial=not args.no_auto_partial,
        online=bool(args.ref_gb or args.accession or args.email),
    )
    ref_text = None
    if args.ref_gb:
        with open(args.ref_gb, encoding="utf-8") as fh:
            ref_text = fh.read()

    results = []
    for s in seqs:
        s.gene_type = args.gene_type
        print(f"[{s.seq_id}] Processing ({s.gene_type}, {len(s.seq)} bp)...")
        res = annotate_sequence(s, cfg, reference_gb_text=ref_text,
                                reference_accession=args.accession or None)
        results.append(res)
        for i in res.issues:
            print(f"  [{i.level}] {i.message}")
        print(f"  Status: {res.status}"
              + (" (RED - manual confirmation required)" if res.status == "red" else ""))

    written = write_outputs(results, args.out, seqs)
    print(f"\nOutput directory: {args.out}")
    for w in written:
        print(f"  {w}")
    n_red = sum(1 for r in results if r.status == "red")
    if n_red:
        print(f"WARNING: {n_red} sequence(s) are RED - files are for manual review; do not submit to GenBank without confirmation.")
    return 1 if n_red else 0


if __name__ == "__main__":
    sys.exit(main())
