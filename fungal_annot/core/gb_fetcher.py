"""Entrez 下载 GenBank（支持窗口截取）+ 磁盘缓存（§6.2）。

长记录（基因组/超长 contig）按 BLAST HSP 窗口 ±flank 截取，避免整条下载与
O(n·m) 全序列比对；efetch 的 seq_start/seq_stop 返回的子记录坐标帧已重建。
"""
import os
import re
import time
from urllib.error import URLError

from Bio import Entrez, SeqIO

_REGION_RE = re.compile(r"REGION:\s*(\d+)\.\.(\d+)")


class GbFetchError(Exception):
    pass


class Throttle:
    """相邻两次 NCBI 请求的最小间隔（秒）。"""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self):
        dt = time.monotonic() - self._last
        if dt < self.min_interval:
            time.sleep(self.min_interval - dt)
        self._last = time.monotonic()


def default_cache_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".fungal_annot", "cache")


def fetch_gb_text(accession: str, email: str = "", api_key: str = "",
                  window=None, flank: int = 500, max_window: int = 500_000,
                  cache_dir: str | None = None,
                  throttle: Throttle | None = None,
                  seq_len: int | None = None) -> tuple[str, str]:
    """下载 GenBank 文本。window=(subj_start, subj_end)（参考 1-based）时取 ±flank；
    seq_len（参考全长，来自 BLAST 命中）用于把窗口末端夹取到记录范围内，避免
    超出末端的请求被 NCBI 返回不同长度的子记录而触发帧校验失败。

    返回 (gb_text, region)；region 为 "full" 或 "a..b"。带 API key 时限速 10 req/s，
    否则按 NCBI 限制保守取 1.2s 间隔。
    """
    if window:
        s = max(1, window[0] - flank)
        e = window[1] + flank
        if seq_len:
            s = min(s, seq_len)
            e = min(e, seq_len)
        if e - s + 1 > max_window:
            raise GbFetchError(
                f"Window of {e - s + 1} bp exceeds the {max_window} bp limit: {accession} looks like a genome-scale record;"
                "pick a single-marker record as reference")
        region = f"{s}..{e}"
    else:
        region = "full"

    cache_dir = cache_dir or default_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    tag = region.replace("..", "-") if window else "full"
    cache_file = os.path.join(cache_dir, f"{accession.replace('.', '_')}_{tag}.gb")
    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 0:
        with open(cache_file, encoding="utf-8") as fh:
            return fh.read(), region

    Entrez.email = email or "fungal-annot@example.org"
    Entrez.api_key = api_key or None
    if throttle is None:
        throttle = Throttle(0.35 if api_key else 1.2)

    params = dict(db="nuccore", id=accession, rettype="gb", retmode="text")
    if window:
        params["seq_start"] = s
        params["seq_stop"] = e
    text = None
    for attempt in range(3):
        try:
            throttle.wait()
            handle = Entrez.efetch(**params)
            text = handle.read()
            handle.close()
            break
        except (URLError, OSError) as ex:
            if attempt == 2:
                raise GbFetchError(f"Failed to download {accession} after 3 attempts: {ex}") from ex
            time.sleep(5 * (2 ** attempt))
    if not text or "LOCUS" not in text[:200]:
        raise GbFetchError(f"{accession}: response is not GenBank text")
    with open(cache_file, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text, region


def parse_gb(text: str, region: str = "full"):
    """解析 GenBank 记录；窗口请求时断言返回记录长度与请求区间一致（§6.2 窗口帧守卫），
    防止坐标偏移静默污染全部迁移坐标。"""
    rec = SeqIO.read(_as_handle(text), "genbank")
    if rec is None or len(rec.seq) == 0:
        raise GbFetchError("Parsed GenBank record is empty")
    if region != "full":
        m = _REGION_RE.search(text)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if len(rec.seq) != b - a + 1:
                raise GbFetchError(
                    f"Window frame mismatch: requested {a}..{b} ({b - a + 1} bp) but got {len(rec.seq)}bp")
        else:
            raise GbFetchError("Windowed response lacks a REGION declaration; coordinate frame cannot be verified")
    return rec


def extract_region(text: str) -> str:
    m = _REGION_RE.search(text)
    return f"{m.group(1)}..{m.group(2)}" if m else "full"


def _as_handle(text):
    import io
    return io.StringIO(text)
