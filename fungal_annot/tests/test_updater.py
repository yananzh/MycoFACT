"""core.updater 单元测试：版本解析/比较 + GitHub Releases 查询（离线，stub urlopen）。"""
import json
import urllib.error

import pytest

from fungal_annot.core import updater


# ---- 版本解析与比较 ---------------------------------------------------------
def test_parse_version():
    assert updater.parse_version("v0.2.1") == (0, 2, 1)
    assert updater.parse_version("0.1.0") == (0, 1, 0)
    assert updater.parse_version("V1.2") == (1, 2)
    assert updater.parse_version("") is None
    assert updater.parse_version("abc") is None
    assert updater.parse_version("v1.0.0-beta.1") is None    # 预发布段不支持


def test_is_newer():
    assert updater.is_newer("v0.2.0", "0.1.9")
    assert updater.is_newer("0.1.10", "v0.1.9")     # 数字比较而非字典序
    assert updater.is_newer("0.2", "0.1.9")         # 段数不足补零
    assert not updater.is_newer("0.1.0", "0.1.0")
    assert not updater.is_newer("0.1.0", "0.2.0")
    assert not updater.is_newer("garbage", "0.1.0") # 解析失败不算新版本


# ---- GitHub Releases 查询 ---------------------------------------------------
class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _release(tag="v0.2.0", body="- fix a\n- add b"):
    return {"tag_name": tag, "html_url": f"https://example.com/rel/{tag}",
            "name": tag, "published_at": "2026-09-29T00:00:00Z", "body": body}


def test_fetch_latest_release_ok(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["ua"] = req.headers.get("User-agent")
        return _FakeResponse(_release())

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    data = updater.fetch_latest_release()
    assert data["tag_name"] == "v0.2.0"
    assert seen["url"] == updater.RELEASE_API
    assert seen["ua"].startswith("MycoFACT/")   # GitHub API 强制要求 User-Agent


def test_fetch_latest_release_bad_shape(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResponse({"foo": 1}))
    with pytest.raises(updater.UpdateCheckError):
        updater.fetch_latest_release()


def test_fetch_latest_release_network_error(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    monkeypatch.setattr(updater.time, "sleep", lambda s: None)  # 跳过退避等待
    with pytest.raises(updater.UpdateCheckError):
        updater.fetch_latest_release(retries=2)


# ---- 组合：check_for_update -------------------------------------------------
def test_check_for_update_paths(monkeypatch):
    monkeypatch.setattr(updater, "fetch_latest_release",
                        lambda **kw: _release("v0.2.0"))
    info = updater.check_for_update("0.1.0")
    assert info == {"version": "0.2.0", "url": "https://example.com/rel/v0.2.0",
                    "name": "v0.2.0", "published_at": "2026-09-29T00:00:00Z",
                    "notes": "- fix a\n- add b"}

    monkeypatch.setattr(updater, "fetch_latest_release",
                        lambda **kw: _release("v0.1.0"))
    assert updater.check_for_update("0.1.0") is None

    monkeypatch.setattr(updater, "fetch_latest_release",
                        lambda **kw: _release("not-a-version"))
    assert updater.check_for_update("0.1.0") is None
