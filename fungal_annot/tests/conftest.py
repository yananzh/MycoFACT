"""端到端测试夹具：构造带完整注释的参考 GenBank 记录与同源查询序列。

参考结构（开发计划 §9.1 A/B/C/D 用例的合成基础）：
- 2000bp 记录 REF00001.1
- CDS join(201..600, 701..1149)（849bp = 283 密码子，含内含子 601..700），
  带 protein_id/locus_tag/db_xref/note="complete cds" —— 用于回归 §6.5 qualifier 三分表
- gene 201..1149；source 带参考菌株修饰符（不得迁移，§2.4）
"""
import io
import os
import random

import pytest
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import (BeforePosition, CompoundLocation, SeqFeature,
                            SimpleLocation)
from Bio.SeqRecord import SeqRecord

# 离屏渲染：CI 的 headless Linux 与本地无显示环境都需要显式指定平台插件。
# 在 conftest 里统一 setdefault，任何引入 Qt 的测试模块（新加的也一样）都不必重复。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


@pytest.fixture
def window(qtbot):
    """四页向导主窗口（离屏渲染）。UI 测试共用，避免每个文件各写一份夹具。"""
    from fungal_annot.ui.main_window import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    yield win


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


@pytest.fixture(scope="session")
def partial_ref_gb():
    """5' partial 单 exon CDS 的参考记录：CDS <301..1150 且 /codon_start=2，
    product/note 都写成 "complete cds"（用于回归完整性断言改写）。

    用途：不变式回归——查询与参考 CDS 完全一致时，输出 codon_start 必须等于参考值。
    """
    rng = random.Random(11)
    inner = "A" + _make_cds(849)          # 前置 1 个碱基 → 首个完整密码子在第 2 位
    bg = "".join(rng.choice("ACGT") for _ in range(1500))
    seq = list(bg)
    seq[300:300 + len(inner)] = list(inner)
    seq = "".join(seq)
    rec = SeqRecord(Seq(seq), id="REF00002.1", name="REF00002",
                    description="Fusarium partialus tef1 gene, partial cds")
    rec.annotations["molecule_type"] = "DNA"
    rec.annotations["data_file_division"] = "PLN"
    rec.annotations["organism"] = "Fusarium partialus"
    rec.annotations["source"] = "Fusarium partialus"
    src = SeqFeature(SimpleLocation(0, 1500, strand=1), type="source")
    src.qualifiers = {"organism": ["Fusarium partialus"], "mol_type": ["genomic DNA"],
                      "strain": ["P001"], "country": ["China"]}
    gene = SeqFeature(SimpleLocation(300, 1150, strand=1), type="gene")
    gene.qualifiers = {"gene": ["tef1"]}
    cds = SeqFeature(SimpleLocation(BeforePosition(300), 1150, strand=1), type="CDS")
    cds.qualifiers = {"gene": ["tef1"],
                      "product": ["translation elongation factor 1-alpha, complete cds"],
                      "note": ["complete cds"],
                      "transl_table": ["1"], "codon_start": ["2"]}
    rec.features = [src, gene, cds]
    buf = io.StringIO()
    SeqIO.write(rec, buf, "genbank")
    return buf.getvalue()


@pytest.fixture(scope="session")
def two_cds_gb():
    """含两个 CDS 的参考记录（201..800 表 1；1201..1800 表 12）。

    用途：回归 CDS 配对必须按参考坐标——查询只覆盖第二个 CDS 时，蛋白回检与密码表
    必须取自该 CDS 自身，而非按下标取到被跳过的第一个 CDS。
    """
    rng = random.Random(23)
    bg = "".join(rng.choice("ACGT") for _ in range(2400))
    seq = list(bg)
    seq[200:800] = list(_make_cds(600))       # CDS-A 201..800
    seq[1200:1800] = list(_make_cds(600))     # CDS-B 1201..1800
    seq = "".join(seq)
    rec = SeqRecord(Seq(seq), id="REF00003.1", name="REF00003",
                    description="two-CDS reference record")
    rec.annotations["molecule_type"] = "DNA"
    rec.annotations["data_file_division"] = "PLN"
    rec.annotations["organism"] = "Fusarium duo"
    rec.annotations["source"] = "Fusarium duo"
    src = SeqFeature(SimpleLocation(0, 2400, strand=1), type="source")
    src.qualifiers = {"organism": ["Fusarium duo"], "mol_type": ["genomic DNA"],
                      "country": ["China"]}
    cds_a = SeqFeature(SimpleLocation(200, 800, strand=1), type="CDS")
    cds_a.qualifiers = {"gene": ["geneA"], "product": ["protein A"],
                        "transl_table": ["1"]}
    cds_b = SeqFeature(SimpleLocation(1200, 1800, strand=1), type="CDS")
    cds_b.qualifiers = {"gene": ["geneB"], "product": ["protein B"],
                        "transl_table": ["12"]}
    rec.features = [src, cds_a, cds_b]
    buf = io.StringIO()
    SeqIO.write(rec, buf, "genbank")
    return buf.getvalue()


def query_plus_insertion(seq: str) -> str:
    """查询 = ref[301..1600] + 框内 3bp 插入（query 0-based 402 处，位于 exon2 读码框内）。"""
    q = seq[300:1600]
    return q[:402] + "GCA" + q[402:]
