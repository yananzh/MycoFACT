"""core.blast_runner 单元测试：并发池的共享提交节流 + run_blast 参数接线。

全部离线：节流器用假时钟，qblast/解析直接 stub，不访问 NCBI。
"""
import io
import threading

from fungal_annot.core import blast_runner as br


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
    assert br._submit_throttle.min_interval == br.SUBMIT_SPACING  # 回到默认间隔
