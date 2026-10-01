"""gb_fetcher 邮箱门禁（不预设邮箱）：缺失即报错、用户邮箱原样生效、缓存命中不受影响。"""
import pytest


def test_missing_email_raises(tmp_path):
    """邮箱缺失/全空白：直接报错并指引用户填写（不得回退到任何预设地址）。"""
    from fungal_annot.core.gb_fetcher import GbFetchError, fetch_gb_text

    with pytest.raises(GbFetchError, match="contact email"):
        fetch_gb_text("XX000001.1", email="", cache_dir=str(tmp_path))
    with pytest.raises(GbFetchError, match="contact email"):
        fetch_gb_text("XX000001.1", email="   ", cache_dir=str(tmp_path))


def test_cached_record_needs_no_email(tmp_path):
    """缓存命中不触网：无需邮箱也返回缓存内容（离线复用不受影响）。"""
    from fungal_annot.core.gb_fetcher import fetch_gb_text

    (tmp_path / "XX000001_1_full.gb").write_text("LOCUS fake", encoding="utf-8")
    text, region = fetch_gb_text("XX000001.1", email="", cache_dir=str(tmp_path))
    assert text == "LOCUS fake" and region == "full"


def test_user_email_is_used(tmp_path, monkeypatch):
    """用户填写的邮箱 trim 后原样传给 Entrez（不存在预设兜底）。"""
    from Bio import Entrez

    from fungal_annot.core.gb_fetcher import fetch_gb_text

    captured = {}

    class _Handle:
        def read(self):
            return "LOCUS fake"

        def close(self):
            pass

    def fake_efetch(**params):
        captured["email"] = Entrez.email
        return _Handle()

    monkeypatch.setattr(Entrez, "efetch", fake_efetch)
    text, _ = fetch_gb_text("XX000001.1", email="  me@host.org  ",
                            cache_dir=str(tmp_path))
    assert captured["email"] == "me@host.org"
    assert "LOCUS fake" in text
