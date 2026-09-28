"""五列 feature table 与配对 .fsa 输出（§6.7）。

格式要点：互补链 feature 的区段按坐标降序书写；'<'/'> ' 标在对应的
partial 坐标端；join 多段为同 feature key 的连续行，qualifier 跟在最后一段后。
"""
import csv
import io


def _fmt_part(p, strand: int):
    """返回 (左坐标, 右坐标) 字符串。partial 标记绑定坐标端：
    plus 左=低('<')/右=高('>')；minus 左=高('>')/右=低('<')。"""
    if strand > 0:
        return (f"<{p.start}" if p.partial_low else str(p.start),
                f">{p.end}" if p.partial_high else str(p.end))
    return (f">{p.end}" if p.partial_high else str(p.end),
            f"<{p.start}" if p.partial_low else str(p.start))


def _order(features):
    src = [f for f in features if f.ftype == "source"]
    rest = sorted((f for f in features if f.ftype != "source"),
                  key=lambda f: (f.start, f.ftype != "gene", f.ftype))
    return src + rest


def feature_lines(feat) -> list[str]:
    lines = []
    coords = [_fmt_part(p, feat.strand) for p in feat.parts]
    if feat.strand < 0:
        coords = list(reversed(coords))
    for left, right in coords:
        lines.append(f"{left}\t{right}\t{feat.ftype}")
    for k, vals in feat.qualifiers.items():
        for v in vals:
            # 五列格式：列 1-3 留空，qualifier 在列 4、值在列 5（三个前导制表符）
            lines.append(f"\t\t\t{k}\t{v}")
    return lines


def write_tbl(features, seq_id: str) -> str:
    out = [f">Feature {seq_id}"]
    for f in _order(features):
        out.extend(feature_lines(f))
    return "\n".join(out) + "\n"


def write_fsa(seq_id: str, seq: str, wrap: int = 70) -> str:
    lines = [f">{seq_id}"]
    for i in range(0, len(seq), wrap):
        lines.append(seq[i:i + wrap])
    return "\n".join(lines) + "\n"


REPORT_COLUMNS = ["seq_id", "length", "gene_type", "status", "n_features",
                  "source", "reference", "region", "orientation",
                  "pident", "qcovs", "nt_identity", "issues"]


def write_report_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=REPORT_COLUMNS, extrasaction="ignore",
                       lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in REPORT_COLUMNS})
    return buf.getvalue()
