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
    (sequences, hits, selected_ref, results, settings,
     confirmed, exported) = load_project(str(p))
    assert sequences == [] and hits == {} and results == {}
    assert selected_ref == {} and confirmed == {}
    assert exported is False


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
