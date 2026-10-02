"""五列 feature table 与配对 .fsa 输出（§6.7）。

格式要点：互补链 feature 的区段按坐标降序书写；'<'（5' partial）恒在
第 1 列、'>'（3' partial）恒在第 2 列，与链方向无关（NCBI feature_table
规范，解析器只按列识别标记，标反则整条 feature 被判无效坐标丢弃）；
join 多段只在**首行**写 feature key，后续区段行仅含起止坐标，qualifier
跟在最后一段后。
"""
import csv
import io


def _fmt_part(p, strand: int):
    """返回 (左坐标, 右坐标) 字符串。NCBI 规范：'<' 恒在第 1 列（5' partial）、
    '>' 恒在第 2 列（3' partial），与链方向无关。partial_low/high 绑定低/高
    坐标端，故负链（5' 端 = 高坐标端）在降序书写时 5' partial 标在
    第 1 列的高坐标、3' partial 标在第 2 列的低坐标。"""
    if strand > 0:
        return (f"<{p.start}" if p.partial_low else str(p.start),
                f">{p.end}" if p.partial_high else str(p.end))
    return (f"<{p.end}" if p.partial_high else str(p.end),
            f">{p.start}" if p.partial_low else str(p.start))


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
    for i, (left, right) in enumerate(coords):
        # feature key 只在首行；join 的后续区段行仅两列坐标（NCBI 规范）
        lines.append(f"{left}\t{right}\t{feat.ftype}" if i == 0
                     else f"{left}\t{right}")
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


def tbl_text_from(features, seq_id: str, fallback: str = "") -> str:
    """.tbl 文本的唯一来源：有 feature 时按 feature **现算**。

    调用方（导出、项目保存）必须走这里，不得直接读结果对象上缓存的文本——
    features 与缓存文本是两份数据源，编辑后两者会不一致。无 feature 时始终
    返回空文本；fallback 参数仅为兼容旧调用保留，不得恢复已经失效的缓存表。
    """
    if features:
        return write_tbl(features, seq_id)
    return ""


def has_feature_lines(text: str) -> bool:
    """五列表文本是否含真正的 feature 行（除 >Feature 记录头与空行外还有内容）。

    只有一条 >Feature 头的 .tbl 对提交毫无意义（BankIt 视为零产出），
    因此不得当成功产物写出。
    """
    for line in (text or "").splitlines():
        stripped = line.rstrip()
        if stripped and not stripped.startswith(">Feature"):
            return True
    return False


def write_combined_tbl(tbl_texts: list[str]) -> str:
    """多记录 feature table：各序列的 >Feature 块顺序拼接成一个汇总文件，
    BankIt 多记录提交可整文件上传。空文本（红灯失败序列）直接跳过。"""
    return "".join(t if t.endswith("\n") else t + "\n" for t in tbl_texts)


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
