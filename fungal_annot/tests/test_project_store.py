"""项目存取错误路径（§7.3）：版本拒绝 / 损坏 JSON / 缺键容错 / 临时文件清理。

此前只有一条 happy-path 往返测试（经 UI 间接覆盖），错误路径零覆盖。
"""
import json

import pytest

from fungal_annot.services import project_store
from fungal_annot.services.project_store import load_project, save_project


def test_load_project_rejects_newer_version(tmp_path):
    """version 大于支持版本 → ValueError（UI 侧弹窗拒载，不静默降级）。"""
    p = tmp_path / "newer.json"
    p.write_text(json.dumps({"version": project_store.PROJECT_VERSION + 1}),
                 encoding="utf-8")
    with pytest.raises(ValueError):
        load_project(str(p))


def test_load_project_corrupt_json_is_valueerror(tmp_path):
    """损坏的 JSON → JSONDecodeError（ValueError 子类，与 UI 的拦截元组一致）。"""
    p = tmp_path / "corrupt.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_project(str(p))


def test_load_project_missing_file(tmp_path):
    """文件不存在 → OSError（UI 侧同样拦截）。"""
    with pytest.raises(OSError):
        load_project(str(tmp_path / "nope.json"))


def test_load_project_minimal_data(tmp_path):
    """缺键容错：只有 version 也能加载出空项目。"""
    p = tmp_path / "min.json"
    p.write_text(json.dumps({"version": project_store.PROJECT_VERSION}),
                 encoding="utf-8")
    (sequences, hits, selected_refs, results, settings,
     confirmed, exported, chosen_ref) = load_project(str(p))
    assert sequences == [] and hits == {} and results == {}
    assert selected_refs == {} and chosen_ref == {}
    assert confirmed == {} and exported is False


def test_project_v2_roundtrip_multi_variant(tmp_path):
    """v2 往返：多 variant + 采纳者 + 多参考选择完整保留。"""
    from fungal_annot.core.models import Provenance, Issue, SeqInput
    from fungal_annot.services.pipeline import SeqResult
    from fungal_annot.services.project_store import save_project

    r1 = SeqResult(seq_id="s1", status="green",
                   provenance=Provenance(reference="REF00001.1"))
    r2 = SeqResult(seq_id="s1", status="yellow",
                   issues=[Issue("warning", "n_boundary", "x")],
                   provenance=Provenance(reference="REF00002.1"))
    p = str(tmp_path / "proj.json")
    save_project(p, [SeqInput("s1", "ACGTACGT")], {},
                 {"s1": ["REF00001.1", "REF00002.1"]},
                 {"s1": {"REF00001.1": r1, "REF00002.1": r2}}, {},
                 confirmed={"s1": True}, exported=False,
                 chosen_ref={"s1": "REF00002.1"})
    (sequences, hits, selected_refs, results, settings,
     confirmed, exported, chosen) = load_project(p)
    assert set(results["s1"]) == {"REF00001.1", "REF00002.1"}
    assert chosen == {"s1": "REF00002.1"}
    assert results["s1"]["REF00002.1"].status == "yellow"
    assert [i.code for i in results["s1"]["REF00002.1"].issues] == ["n_boundary"]
    assert selected_refs == {"s1": ["REF00001.1", "REF00002.1"]}
    assert confirmed == {"s1": True} and exported is False


def test_load_project_v1_migrates_to_variants(tmp_path):
    """v1（单参考）项目 → v2 结构：单结果成为唯一 variant（accession 取
    provenance.reference）且即为采纳者；selected_ref 单值 → 单元素列表。"""
    data = {
        "version": 1,
        "sequences": [{"seq_id": "s1", "seq": "ACGTACGT", "gene_type": "tef1",
                       "source_qualifiers": {}}],
        "hits": {},
        "selected_ref": {"s1": "REF00001.1"},
        "results": {"s1": {
            "seq_id": "s1", "status": "yellow", "issues": [],
            "provenance": {"source": "accession", "reference": "REF00001.1",
                           "region": "full", "orientation": "forward",
                           "pident": None, "qcovs": None, "nt_identity": None},
            "tbl_text": ">Feature s1\n", "fsa_text": "", "features": [],
        }},
        "confirmed": {}, "exported": False, "settings": {},
    }
    p = tmp_path / "v1.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    (sequences, hits, selected_refs, results, settings,
     confirmed, exported, chosen_ref) = load_project(str(p))
    assert set(results["s1"]) == {"REF00001.1"}
    assert chosen_ref == {"s1": "REF00001.1"}
    assert results["s1"]["REF00001.1"].status == "yellow"
    assert selected_refs == {"s1": ["REF00001.1"]}


def test_save_project_leaves_no_tmp_file(tmp_path):
    """回归：save 成功后不得遗留 path + ".tmp"（json.dump 中途异常时也需清理）。"""
    p = str(tmp_path / "proj.json")
    save_project(p, [], {}, {}, {}, {})
    import os
    assert os.path.exists(p)
    assert not os.path.exists(p + ".tmp")


def test_save_project_failure_cleans_tmp_file(tmp_path, monkeypatch):
    """json.dump 中途失败 → .tmp 清理掉，不留垃圾文件。"""
    p = str(tmp_path / "proj.json")

    def boom(*a, **k):
        raise TypeError("not serializable")
    monkeypatch.setattr(project_store.json, "dump", boom)
    with pytest.raises(TypeError):
        save_project(p, [], {}, {}, {}, {})
    import os
    assert not os.path.exists(p + ".tmp")
