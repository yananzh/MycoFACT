"""软件更新检查（手动触发）：查询 GitHub Releases 最新版并与当前版本比较。

联网惯例沿用 gb_fetcher：领域异常 + 少量重试退避 + 校验响应形状，全部异常
统一转 UpdateCheckError，不向 UI 泄露原始网络异常。release 的 tag 是 v 前缀
（如 v0.2.0）而包内 __version__ 裸写（0.2.0），比较前先剥掉前缀。
"""
import json
import time
import urllib.error
import urllib.request

RELEASE_API = "https://api.github.com/repos/yananzh/MycoFACT/releases/latest"


class UpdateCheckError(Exception):
    """更新检查失败（网络 / 限流 / 响应形状不符合预期）。"""


def parse_version(text: str):
    """"v0.2.1" → (0, 2, 1)；非纯数字版本号（预发布段等）返回 None。"""
    if not text:
        return None
    parts = text.strip().lstrip("vV").split(".")
    if not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def is_newer(latest: str, current: str) -> bool:
    """latest 是否严格新于 current（逐段数字比较，段数不足补零）。"""
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def fetch_latest_release(timeout: float = 8.0, retries: int = 2) -> dict:
    """查询最新 release 的原始 JSON 字段；网络类失败按 2/4 秒退避重试。

    GitHub API 强制要求 User-Agent；响应缺少 tag_name / html_url 视为
    形状异常，重试无意义，立即抛出。
    """
    from .. import __version__

    last_ex = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                RELEASE_API,
                headers={"User-Agent": f"MycoFACT/{__version__}",
                         "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, dict) or not data.get("tag_name") \
                    or not data.get("html_url"):
                raise UpdateCheckError(
                    "Unexpected response from the GitHub Releases API")
            return data
        except UpdateCheckError:
            raise
        except (urllib.error.URLError, OSError, ValueError) as ex:
            last_ex = ex
            if attempt < retries:
                time.sleep(2 * (2 ** attempt))
    raise UpdateCheckError(
        f"Could not reach GitHub Releases: {last_ex}") from last_ex


def check_for_update(current: str, timeout: float = 8.0, retries: int = 2) -> dict | None:
    """有新版本返回摘要 dict，已是最新（或无法解析版本号）返回 None。

    dict 字段：version（剥 v 前缀）、url（release 页）、name、published_at、
    notes（release notes 原文，供 UI 摘录）。
    """
    data = fetch_latest_release(timeout=timeout, retries=retries)
    tag = str(data["tag_name"]).strip()
    if not is_newer(tag, current):
        return None
    return {
        "version": tag.lstrip("vV"),
        "url": str(data["html_url"]),
        "name": str(data.get("name") or ""),
        "published_at": str(data.get("published_at") or ""),
        "notes": str(data.get("body") or ""),
    }
