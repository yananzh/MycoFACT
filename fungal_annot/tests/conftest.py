"""端到端测试夹具：构造带完整注释的参考 GenBank 记录与同源查询序列。

参考结构（开发计划 §9.1 A/B/C/D 用例的合成基础）：
- 2000bp 记录 REF00001.1
- CDS join(201..600, 701..1149)（849bp = 283 密码子，含内含子 601..700），
  带 protein_id/locus_tag/db_xref/note="complete cds" —— 用于回归 §6.5 qualifier 三分表
- gene 201..1149；source 带参考菌株修饰符（不得迁移，§2.4）
"""
import io
import random

import pytest
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import CompoundLocation, SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord

# 密码子池：全部以 G/C 结尾、不以 T 开头且不含 "TA"/"TG" 子串——任何拼接顺序、
# 任何读码框都不可能产生终止密码子（框内插入 TAA 的测试除外）
CODON_POOL = ["CCG", "GCG", "GCC", "GGC", "GGG", "ACG", "AGG", "CGC", "CTC", "ACC", "AGC", "GAG"]


def _make_cds(length: int) -> str:
    crng = random.Random(7)   # 与背景序列的 rng 独立，保证夹具确定性
    # ATG 之后必须接 C/G 开头的密码子，否则移框读出 TGA（ATG|ACG → TG-A）
    first_pool = [c for c in CODON_POOL if not c.startswith("A")]
    codons = ["ATG", crng.choice(first_pool)]
    codons += [crng.choice(CODON_POOL) for _ in range((length - 6) // 3 - 1)]
    codons += ["TAA"]
    s = "".join(codons)
    assert len(s) == length
    for f in range(3):  # 任何读码框都不得出现*内部*终止子（末尾终止子属设计）
        seg = s[f:]
        seg = seg[:len(seg) // 3 * 3]
        prot = str(Seq(seg).translate())
        if prot.endswith("*"):
            prot = prot[:-1]
        assert "*" not in prot, f"frame {f} 出现内部终止子"
    return s


@pytest.fixture(scope="session")
def ref_record_seq():
    """(2000bp 参考序列, 849bp CDS 序列)。

    CDS 用伪随机密码子（而非循环），否则 CDS 成为周期序列，局部比对的放置
    在重复区内不唯一，会破坏所有坐标断言。
    """
    rng = random.Random(42)
    bg = "".join(rng.choice("ACGT") for _ in range(2000))
    cds = _make_cds(849)
    seq = list(bg)
    seq[200:600] = list(cds[:400])       # exon1 = 201..600
    seq[700:1149] = list(cds[400:])      # exon2 = 701..1149
    return "".join(seq), cds


@pytest.fixture(scope="session")
def ref_gb_text(ref_record_seq):
    seq, cds = ref_record_seq
    rec = SeqRecord(Seq(seq), id="REF00001.1", name="REF00001",
                    description="Fusarium referenceus isolate REF001 tef1 gene, complete cds")
    rec.annotations["molecule_type"] = "DNA"
    rec.annotations["data_file_division"] = "PLN"
    rec.annotations["organism"] = "Fusarium referenceus"
    rec.annotations["source"] = "Fusarium referenceus"

    src = SeqFeature(SimpleLocation(0, 2000, strand=1), type="source")
    src.qualifiers = {"organism": ["Fusarium referenceus"], "mol_type": ["genomic DNA"],
                      "strain": ["REF001"], "country": ["China"],
                      "db_xref": ["taxon:999999"]}

    gene = SeqFeature(SimpleLocation(200, 1149, strand=1), type="gene")
    gene.qualifiers = {"gene": ["tef1"]}

    cds_f = SeqFeature(CompoundLocation([SimpleLocation(200, 600, strand=1),
                                         SimpleLocation(700, 1149, strand=1)]), type="CDS")
    cds_f.qualifiers = {"gene": ["tef1"],
                        "product": ["translation elongation factor 1-alpha"],
                        "note": ["complete cds"],
                        "protein_id": ["NP_999.1"],
                        "locus_tag": ["REF_0001"],
                        "db_xref": ["GeneID:999"],
                        "transl_table": ["1"],
                        "translation": [str(Seq(cds[:-3]).translate())]}
    rec.features = [src, gene, cds_f]
    buf = io.StringIO()
    SeqIO.write(rec, buf, "genbank")
    return buf.getvalue()


def query_plus_insertion(seq: str) -> str:
    """查询 = ref[301..1600] + 框内 3bp 插入（query 0-based 402 处，位于 exon2 读码框内）。"""
    q = seq[300:1600]
    return q[:402] + "GCA" + q[402:]
