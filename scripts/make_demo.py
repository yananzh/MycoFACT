"""生成演示数据：demo/reference.gb（带完整注释的参考记录）+ demo/tef1_queries.fasta。

用法：python scripts/make_demo.py
之后可运行：python main.py run --input demo/tef1_queries.fasta --out demo_out \
    --gene-type tef1 --ref-gb demo/reference.gb
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import CompoundLocation, SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord

# 与测试夹具同一套构造逻辑（无终止子密码子池 + 伪随机）
CODON_POOL = ["CCG", "GCG", "GCC", "GGC", "GGG", "ACG", "AGG", "CGC", "CTC", "ACC", "AGC", "GAG"]


def make_cds(length):
    crng = random.Random(7)
    first_pool = [c for c in CODON_POOL if not c.startswith("A")]
    codons = ["ATG", crng.choice(first_pool)]
    codons += [crng.choice(CODON_POOL) for _ in range((length - 6) // 3 - 1)]
    codons += ["TAA"]
    s = "".join(codons)
    return s


def main():
    rng = random.Random(42)
    bg = "".join(rng.choice("ACGT") for _ in range(2000))
    cds = make_cds(849)
    seq_list = list(bg)
    seq_list[200:600] = list(cds[:400])      # exon1 = 201..600
    seq_list[700:1149] = list(cds[400:])     # exon2 = 701..1149
    seq = "".join(seq_list)

    rec = SeqRecord(Seq(seq), id="MZ123456.1", name="MZ123456",
                    description="Fusarium solani isolate CBS 123456 tef1 gene, partial cds")
    rec.annotations["molecule_type"] = "DNA"
    rec.annotations["data_file_division"] = "PLN"
    rec.annotations["organism"] = "Fusarium solani"
    rec.annotations["source"] = "Fusarium solani"
    src = SeqFeature(SimpleLocation(0, 2000, strand=1), type="source")
    src.qualifiers = {"organism": ["Fusarium solani"], "mol_type": ["genomic DNA"],
                      "strain": ["CBS 123456"], "country": ["China: Beijing"],
                      "collection_date": ["2020-May"]}
    gene = SeqFeature(SimpleLocation(200, 1149, strand=1), type="gene")
    gene.qualifiers = {"gene": ["tef1"]}
    cds_f = SeqFeature(CompoundLocation([SimpleLocation(200, 600, strand=1),
                                         SimpleLocation(700, 1149, strand=1)]), type="CDS")
    cds_f.qualifiers = {"gene": ["tef1"],
                        "product": ["translation elongation factor 1-alpha"],
                        "note": ["partial cds"],
                        "protein_id": ["QWX12345.1"],
                        "locus_tag": ["FSOL_0001"],
                        "db_xref": ["GeneID:888888"],
                        "transl_table": ["1"],
                        "translation": [str(Seq(cds[:-3]).translate())]}
    rec.features = [src, gene, cds_f]

    here = os.path.dirname(os.path.abspath(__file__))
    demo = os.path.join(here, "..", "demo")
    os.makedirs(demo, exist_ok=True)
    with open(os.path.join(demo, "reference.gb"), "w", encoding="utf-8", newline="\n") as fh:
        SeqIO.write(rec, fh, "genbank")

    # 两条查询：正链（带 3bp 框内插入）与反向互补
    q1 = seq[300:1600]
    q1 = q1[:402] + "GCA" + q1[402:]
    q2 = str(Seq(seq[300:1600]).reverse_complement())
    with open(os.path.join(demo, "tef1_queries.fasta"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(">Fsol_A1_tef1\n")
        for i in range(0, len(q1), 70):
            fh.write(q1[i:i + 70] + "\n")
        fh.write(">Fsol_A2_tef1_RC\n")
        for i in range(0, len(q2), 70):
            fh.write(q2[i:i + 70] + "\n")
    print("demo 数据已生成：demo/reference.gb, demo/tef1_queries.fasta")


if __name__ == "__main__":
    main()
