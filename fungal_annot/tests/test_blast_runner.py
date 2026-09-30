"""core.blast_runner 单元测试：并发池的共享提交节流 + run_blast 参数接线。

全部离线：节流器用假时钟，qblast/解析直接 stub，不访问 NCBI。
"""
import io
import threading

from fungal_annot.core import blast_runner as br
from fungal_annot.core.models import BlastHit


# ---- 共享提交节流器 ---------------------------------------------------------
def test_submit_throttle_spaces_concurrent_submits(monkeypatch):
    """并发池下共享节流：3 个线程同时 wait()，提交时刻互相错开 ≥ min_interval。"""
    now = {"t": 100.0}
    monkeypatch.setattr(br.time, "monotonic", lambda: now["t"])
    monkeypatch.setattr(br.time, "sleep", lambda s: now.__setitem__("t", now["t"] + s))

    th = br._SubmitThrottle(10.0)
    barrier = threading.Barrier(3)
    ts = []

    def worker():
        barrier.wait()
        th.wait()
        ts.append(now["t"])

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert ts == sorted(ts)
    for a, b in zip(ts, ts[1:]):
        assert b - a >= 10.0 - 1e-9      # 相邻提交间隔不小于节流窗口


def test_submit_throttle_no_wait_when_spaced(monkeypatch):
    """距上次提交已超过间隔时不 sleep。"""
    now = {"t": 100.0}
    monkeypatch.setattr(br.time, "monotonic", lambda: now["t"])
    slept = []
    monkeypatch.setattr(br.time, "sleep", lambda s: slept.append(s))

    th = br._SubmitThrottle(10.0)
    th.wait()                            # _last=0 → dt=100 ≥ 10，不等待
    now["t"] = 200.0
    th.wait(5.0)                         # 显式改窗口，仍远超间隔
    assert slept == []


# ---- run_blast 接线 ---------------------------------------------------------
def test_run_blast_passes_params_and_throttles(monkeypatch):
    """run_blast 经共享节流器提交，参数透传 qblast；organism 为空时不加 Entrez 过滤。"""
    seen = {}

    def fake_qblast(program, db, seq, **kw):
        seen.update(program=program, db=db, hitlist=kw.get("hitlist_size"),
                    entrez=kw.get("entrez_query"))
        return io.StringIO("<xml/>")

    monkeypatch.setattr(br.NCBIWWW, "qblast", fake_qblast)
    monkeypatch.setattr(br, "parse_qblast_xml",
                        lambda xml, query_len: [{"ok": query_len}])
    waits = []
    monkeypatch.setattr(br._submit_throttle, "wait",
                        lambda iv=None: waits.append(iv))

    hits = br.run_blast("ACGT", blast_db="core_nt", organism="Fusarium",
                        hitlist_size=20, submit_interval=7)
    assert seen == {"program": "blastn", "db": "core_nt",
                    "hitlist": 20, "entrez": "Fusarium"}
    assert waits == [7]                  # 提交前经过共享节流器（间隔透传）
    assert hits == [{"ok": 4}]

    seen.clear()
    br.run_blast("ACGT")
    assert seen["entrez"] is None        # 空 organism → 无 Entrez 过滤
    # 断言逐次透传本身（旧断言 min_interval 未变是永真的：stub 从不写该属性）
    assert waits == [7.0, br.SUBMIT_SPACING]


# ---- rank_hits：参考排序 -----------------------------------------------------
def _hit(acc, qcovs, pident=99.0, flags=None):
    return BlastHit(accession=acc, title=acc, pident=pident, qcovs=qcovs,
                    flags=flags or {})


def test_rank_hits_prefers_full_coverage_then_completeness():
    """qcovs 满覆盖优先 → 注释完整度（complete_cds > 培养物线索 > partial）→ pident。"""
    full_partial = _hit("A", 100.0, flags={"partial_cds": True})
    full_culture = _hit("B", 100.0, flags={"culture": True})
    full_complete = _hit("C", 100.0, flags={"complete_cds": True})
    partial_cov = _hit("D", 90.0, flags={"complete_cds": True})
    ranked = br.rank_hits([partial_cov, full_culture, full_complete, full_partial], None)
    assert [h.accession for h in ranked] == ["C", "B", "A", "D"]


def test_rank_hits_refseq_bonus_only_for_rrna():
    """RefSeq 加分仅对 rRNA 类预设生效（蛋白编码 marker 无 RefSeq 覆盖）：
    其余线索相同时，rRNA 参考中 RefSeq 记录优先；CDS 参考中不起作用。"""
    refseq = _hit("R", 100.0, pident=98.0, flags={"refseq": True, "culture": True})
    plain = _hit("P", 100.0, pident=99.5, flags={"culture": True})
    cds = br.GenePreset(name="tef1", kind="CDS", transl_table=1,
                        feature_types=["gene", "CDS"])
    assert [h.accession for h in br.rank_hits([refseq, plain], cds)] == ["P", "R"]
    rrna = br.GenePreset(name="LSU", kind="rRNA", transl_table=None,
                         feature_types=["gene", "rRNA"])
    assert [h.accession for h in br.rank_hits([refseq, plain], rrna)] == ["R", "P"]


# ---- parse_qblast_xml：负链 HSP 的 subject 区间归一化 ------------------------
_BLAST_XML = """<?xml version="1.0"?>
<BlastOutput>
  <BlastOutput_program>blastn</BlastOutput_program>
  <BlastOutput_version>BLASTN 2.16.0+</BlastOutput_version>
  <BlastOutput_db>core_nt</BlastOutput_db>
  <BlastOutput_query-ID>Query_1</BlastOutput_query-ID>
  <BlastOutput_query-def>tef1</BlastOutput_query-def>
  <BlastOutput_query-len>400</BlastOutput_query-len>
  <BlastOutput_param><Parameters><Parameters_expect>0.05</Parameters_expect></Parameters></BlastOutput_param>
  <BlastOutput_iterations>
    <Iteration>
      <Iteration_num>1</Iteration_num>
      <Iteration_hits>
        <Hit>
          <Hit_num>1</Hit_num>
          <Hit_id>gnl|BL_ORD_ID|0</Hit_id>
          <Hit_def>ref|NC_000001.1| marker complete cds</Hit_def>
          <Hit_accession>NC_000001.1</Hit_accession>
          <Hit_len>5000</Hit_len>
          <Hit_hsps>
            <Hsp>
              <Hsp_num>1</Hsp_num>
              <Hsp_bit-score>250.0</Hsp_bit-score>
              <Hsp_score>500</Hsp_score>
              <Hsp_evalue>1e-60</Hsp_evalue>
              <Hsp_query-from>1</Hsp_query-from>
              <Hsp_query-to>200</Hsp_query-to>
              <Hsp_hit-from>800</Hsp_hit-from>
              <Hsp_hit-to>600</Hsp_hit-to>
              <Hsp_query-frame>1</Hsp_query-frame>
              <Hsp_hit-frame>-1</Hsp_hit-frame>
              <Hsp_identity>198</Hsp_identity>
              <Hsp_positive>198</Hsp_positive>
              <Hsp_gaps>0</Hsp_gaps>
              <Hsp_align-len>200</Hsp_align-len>
              <Hsp_qseq>ACGT</Hsp_qseq>
              <Hsp_hseq>ACGT</Hsp_hseq>
            </Hsp>
            <Hsp>
              <Hsp_num>2</Hsp_num>
              <Hsp_bit-score>80.0</Hsp_bit-score>
              <Hsp_score>160</Hsp_score>
              <Hsp_evalue>1e-15</Hsp_evalue>
              <Hsp_query-from>301</Hsp_query-from>
              <Hsp_query-to>400</Hsp_query-to>
              <Hsp_hit-from>500</Hsp_hit-from>
              <Hsp_hit-to>400</Hsp_hit-to>
              <Hsp_query-frame>1</Hsp_query-frame>
              <Hsp_hit-frame>-1</Hsp_hit-frame>
              <Hsp_identity>90</Hsp_identity>
              <Hsp_positive>90</Hsp_positive>
              <Hsp_gaps>0</Hsp_gaps>
              <Hsp_align-len>100</Hsp_align-len>
              <Hsp_qseq>ACGT</Hsp_qseq>
              <Hsp_hseq>ACGT</Hsp_hseq>
            </Hsp>
          </Hit_hsps>
        </Hit>
        <Hit>
          <Hit_num>2</Hit_num>
          <Hit_id>gnl|BL_ORD_ID|1</Hit_id>
          <Hit_def>some strain</Hit_def>
          <Hit_accession>AB000002.1</Hit_accession>
          <Hit_len>3000</Hit_len>
          <Hit_hsps>
            <Hsp>
              <Hsp_num>1</Hsp_num>
              <Hsp_bit-score>200.0</Hsp_bit-score>
              <Hsp_score>400</Hsp_score>
              <Hsp_evalue>1e-50</Hsp_evalue>
              <Hsp_query-from>1</Hsp_query-from>
              <Hsp_query-to>200</Hsp_query-to>
              <Hsp_hit-from>100</Hsp_hit-from>
              <Hsp_hit-to>299</Hsp_hit-to>
              <Hsp_query-frame>1</Hsp_query-frame>
              <Hsp_hit-frame>1</Hsp_hit-frame>
              <Hsp_identity>196</Hsp_identity>
              <Hsp_positive>196</Hsp_positive>
              <Hsp_gaps>0</Hsp_gaps>
              <Hsp_align-len>200</Hsp_align-len>
              <Hsp_qseq>ACGT</Hsp_qseq>
              <Hsp_hseq>ACGT</Hsp_hseq>
            </Hsp>
          </Hit_hsps>
        </Hit>
      </Iteration_hits>
    </Iteration>
  </BlastOutput_iterations>
</BlastOutput>"""


def test_parse_qblast_xml_normalizes_minus_strand_subject_span():
    """legacy BLAST XML 的负链 HSP 以 hit-from > hit-to 报告；subject 区间须
    先按 HSP 归一化为 lo..hi 再跨 HSP 取包络，否则窗口截取失真/误报错误。"""
    hits = br.parse_qblast_xml(_BLAST_XML, query_len=400)
    minus, plus = hits
    # 负链两段 HSP：800..600 与 500..400 → 包络 400..800（旧实现给出 500..600）
    assert (minus.subject_start, minus.subject_end) == (400, 800)
    assert minus.subject_len == 5000
    assert minus.pident == 99.0          # 最佳 HSP：198/200
    assert minus.qcovs == 75.0           # (1..200)+(301..400) 合并 300bp / 400
    # 正链 HSP 不受影响
    assert (plus.subject_start, plus.subject_end) == (100, 299)
    assert plus.pident == 98.0
    assert plus.flags["complete_cds"] is False
    assert minus.flags["complete_cds"] is True   # title 线索解析仍工作
