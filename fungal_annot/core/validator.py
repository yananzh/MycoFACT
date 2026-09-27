"""自动验证（§6.6）：翻译 / 边界 / 密码表一致性 / identity 门禁 / 修饰符格式 /
Seq ID / N 区段边界。所有问题输出为结构化 Issue，驱动状态灯。

状态判定：status_of(issues) → red（任一 error）/ yellow（有 warning）/ green。
"""
import re

from Bio.Seq import Seq

from .feature_transfer import _spliced_cds, resolve_transl_table
from .models import Feature, Issue

SEQID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-|+]*$")
LATLON_RE = re.compile(r"^-?\d{1,3}(\.\d+)?\s*[NS]\s+-?\d{1,3}(\.\d+)?\s*[EW]$")
# NCBI 认可的 collection_date 常见形态：2021 / 2021-03 / 2021-03-15 / 2021-Mar / 2021-Mar-15
# 及区间 "a/b"、"before YYYY"、"after YYYY"、"not collected"
_DATE_RE = re.compile(
    r"^\d{4}(-\d{2}(-\d{2})?|-[A-Z][a-z]{2}(-\d{2})?)?"
    r"(/\d{4}(-\d{2}(-\d{2})?|-[A-Z][a-z]{2}(-\d{2})?)?)?$")
_DATE_SPECIAL = re.compile(r"^(before|after)\s+\d{4}$|^not collected$", re.I)
_STOPS = ("TAA", "TAG", "TGA")

# NCBI 受控国家/地区列表的常用子集；未收录者降级为 warning（请核对官方列表），
# 避免因本地清单不全而误拦截合法提交。
COUNTRY_LIST = {
    "Argentina", "Australia", "Austria", "Bangladesh", "Belarus", "Belgium",
    "Bolivia", "Bosnia and Herzegovina", "Brazil", "Bulgaria", "Cambodia",
    "Cameroon", "Canada", "Chile", "China", "Colombia", "Costa Rica",
    "Croatia", "Cuba", "Cyprus", "Czechia", "Czech Republic", "Denmark",
    "Dominican Republic", "Ecuador", "Egypt", "Estonia", "Ethiopia",
    "Finland", "France", "French Polynesia", "Georgia", "Germany", "Ghana",
    "Greece", "Greenland", "Guatemala", "Hungary", "Iceland", "India",
    "Indonesia", "Iran", "Iraq", "Ireland", "Israel", "Italy", "Jamaica",
    "Japan", "Jordan", "Kazakhstan", "Kenya", "Korea", "South Korea",
    "Kyrgyzstan", "Laos", "Latvia", "Lebanon", "Lithuania", "Madagascar",
    "Malaysia", "Mexico", "Mongolia", "Montenegro", "Morocco", "Myanmar",
    "Nepal", "Netherlands", "New Zealand", "Nicaragua", "Nigeria", "Norway",
    "Oman", "Pakistan", "Panama", "Papua New Guinea", "Paraguay", "Peru",
    "Philippines", "Poland", "Portugal", "Puerto Rico", "Qatar", "Romania",
    "Russia", "Russian Federation", "Saudi Arabia", "Serbia", "Singapore",
    "Slovakia", "Slovenia", "South Africa", "Spain", "Sri Lanka", "Sweden",
    "Switzerland", "Taiwan", "Tanzania", "Thailand", "Tunisia", "Turkey",
    "Turkmenistan", "Uganda", "Ukraine", "United Arab Emirates",
    "United Kingdom", "UK", "USA", "United States", "Uruguay", "Uzbekistan",
    "Venezuela", "Vietnam", "Viet Nam", "Zambia", "Zimbabwe",
}


def status_of(issues) -> str:
    levels = {i.level for i in issues}
    if "error" in levels:
        return "red"
    if "warning" in levels:
        return "yellow"
    return "green"


def _in_n_run(seq: str, pos: int, min_run: int = 5) -> bool:
    """1-based 边界坐标是否落在长度 ≥ min_run 的连续 N 区段（或紧邻其边缘）。"""
    n = len(seq)

    def run_len(idx):
        l = r = idx
        while l > 0 and seq[l - 1] == "N":
            l -= 1
        while r < n - 1 and seq[r + 1] == "N":
            r += 1
        return r - l + 1

    if seq[pos - 1] == "N":
        return run_len(pos - 1) >= min_run
    if pos > 1 and seq[pos - 2] == "N" and run_len(pos - 2) >= min_run:
        return True
    if pos < n and seq[pos] == "N" and run_len(pos) >= min_run:
        return True
    return False


def _aa_identity(a: str, b: str):
    if not a or not b:
        return None
    from Bio.Align import PairwiseAligner
    al = PairwiseAligner()
    al.mode = "global"
    al.match_score = 2
    al.mismatch_score = -1
    al.open_gap_score = -5
    al.extend_gap_score = -1
    res = al.align(a, b)
    best = res[0]   # 不调用 len()：最优解数量可能极大（惰性求值）
    t_arr, q_arr = best.aligned
    eq = tot = 0
    for (ts, te), (qs, qe) in zip(t_arr, q_arr):
        for i in range(te - ts):
            tot += 1
            if a[ts + i] == b[qs + i]:
                eq += 1
    return (eq / tot) if tot else None


def _translate(aa_seq: str, table: int) -> str:
    trimmed = aa_seq[:len(aa_seq) // 3 * 3]
    return str(Seq(trimmed).translate(table=table))


def validate(seq_input, features, mapping, ref_features, ref_seq, preset, cfg):
    """返回 issues 列表；状态由 status_of() 汇总。"""
    issues = []
    seq = seq_input.seq
    L = len(seq)

    # ---- Seq ID 合法性 ----
    if not SEQID_RE.match(seq_input.seq_id or ""):
        issues.append(Issue("error", "seqid_invalid",
                            f"Seq ID '{seq_input.seq_id}' contains spaces or invalid characters"
                            "(allowed: alphanumerics and . _ : - | +); must match the FASTA header"))

    # ---- 坐标范围 + N 区段边界 ----
    for f in features:
        for p in f.parts:
            if not (1 <= p.start <= p.end <= L):
                issues.append(Issue("error", "coord_out_of_range",
                                    f"{f.ftype} segment {p.start}..{p.end} is outside the sequence range 1..{L}"))
        for p in f.parts:
            if not (1 <= p.start <= p.end <= L):
                continue        # 越界区段已记 error，跳过 N 检查避免索引越界
            if any(_in_n_run(seq, pos) for pos in (p.start, p.end)):
                issues.append(Issue("warning", "n_boundary",
                                    f"{f.ftype} boundary falls in a run of N bases; coordinates may be unreliable"))
                break

    # ---- source 修饰符（§2.4）----
    src = next((f for f in features if f.ftype == "source"), None)
    if src is None:
        issues.append(Issue("error", "source_missing", "Missing source feature"))
    else:
        q = {k: v[0] for k, v in src.qualifiers.items() if v}
        if not q.get("organism"):
            issues.append(Issue("warning", "modifier_missing", "source lacks organism"))
        if not q.get("mol_type"):
            issues.append(Issue("warning", "modifier_missing", "source lacks mol_type"))
        country = (q.get("country") or "").strip()
        if not country:
            issues.append(Issue("warning", "modifier_missing",
                                "source lacks country (mandatory for naturally collected specimens)"))
        else:
            head = country.split(":")[0].strip()
            if not head:
                issues.append(Issue("error", "modifier_format", f"country has invalid format: '{country}'"))
            elif head not in COUNTRY_LIST:
                issues.append(Issue("warning", "country_unverified",
                                    f"country '{head}' is not in the local controlled list; check the official NCBI country list"))
        date = (q.get("collection_date") or "").strip()
        if date and not (_DATE_RE.match(date) or _DATE_SPECIAL.match(date)):
            issues.append(Issue("error", "modifier_format",
                                f"collection_date does not follow NCBI format: '{date}'"
                                "(e.g. 2021 / 2021-03 / 2021-03-15 / 2021-Mar / 2021-Mar-15)"))
        latlon = (q.get("lat_lon") or "").strip()
        if latlon and not LATLON_RE.match(latlon):
            issues.append(Issue("error", "modifier_format",
                                f"lat_lon should look like '12.3 N 45.6 E': '{latlon}'"))

    # ---- CDS 逐条检查 ----
    ref_cds = [f for f in ref_features if f.ftype == "CDS"]
    new_cds = [f for f in features if f.ftype == "CDS"]
    if len(ref_cds) != len(new_cds):
        issues.append(Issue("info", "cds_pairing",
                            "Transferred CDS count differs from the reference (some skipped/dropped); protein check paired where possible"))
    for i, f in enumerate(new_cds):
        ref_f = ref_cds[i] if i < len(ref_cds) else None
        table, conflict, certain = resolve_transl_table(ref_f, preset, cfg.user_transl_table)
        if conflict:
            issues.append(Issue(
                "warning", "transl_table_conflict",
                f"Reference /transl_table={ref_val_of(ref_f)} differs from the selected "
                f"table={table}; not silently resolved - manual confirmation required (§2.3)"))
        if table is None:
            issues.append(Issue("info", "table_uncertain",
                                "Transl table undetermined (no reference qualifier, no preset default); translation check skipped"))
        else:
            cds_seq = _spliced_cds(f.parts, f.strand, seq)
            cs = int(f.qualifiers.get("codon_start", ["1"])[0])
            frame = cds_seq[cs - 1:]
            aa = _translate(frame, table)
            core = aa[:-1] if aa.endswith("*") else aa
            if "*" in core:
                level = "error" if certain else "warning"
                issues.append(Issue(
                    level, "internal_stop",
                    "CDS translation contains an internal stop codon"
                    + ("" if certain else " (transl table uncertain - possibly a wrong table)")))
            p5 = (f.strand < 0 and f.parts[-1].partial_high) or \
                 (f.strand > 0 and f.parts[0].partial_low)
            p3 = (f.strand < 0 and f.parts[0].partial_low) or \
                 (f.strand > 0 and f.parts[-1].partial_high)
            if not p3:
                if len(frame) % 3 != 0:
                    issues.append(Issue("error", "cds_phase",
                                        "3' end is not partial but CDS length is not a multiple of three"))
                elif aa and aa[-1] != "*" and frame[-3:] not in _STOPS:
                    issues.append(Issue("warning", "no_stop_codon", "3' end complete but no stop codon"))
            if not p5 and frame[:3] != "ATG":
                issues.append(Issue("warning", "no_start_codon", "5' end complete but no ATG start codon"))
            # 蛋白回检：与参考蛋白 pairwise identity（§6.6）
            if ref_f is not None and aa:
                ref_cs = int((ref_f.qualifiers.get("codon_start") or ["1"])[0])
                ref_aa = _translate(_spliced_cds(ref_f.parts, ref_f.strand, ref_seq)[ref_cs - 1:], table)
                ident = _aa_identity(core, ref_aa[:-1] if ref_aa.endswith("*") else ref_aa)
                if ident is not None and ident < 0.95:
                    issues.append(Issue(
                        "warning", "protein_identity",
                        f"Protein identity vs reference {ident:.1%} < 95%"))

    # ---- Nucleotide identity 门禁：非编码用全局，CDS 按 exon 加权（§6.6）----
    if new_cds:
        tot = eq = 0
        for f in new_cds:
            for p in f.parts:
                if p.ref_start and p.ref_end:
                    for (rs, re_, _qs, _qe) in mapping.blocks:
                        s, e = max(rs, p.ref_start), min(re_, p.ref_end)
                        for pos in range(s, e + 1):
                            tot += 1
                            if mapping.ref_seq[pos - 1] == mapping.query_seq[mapping.ref_to_query[pos] - 1]:
                                eq += 1
        nt = (eq / tot) if tot else None
    else:
        nt = mapping.identity()
    if nt is not None and nt * 100 < cfg.identity_threshold:
        issues.append(Issue(
            "error", "low_identity",
            f"Nucleotide identity {nt:.1%} is below threshold {cfg.identity_threshold}%%; confirm the reference choice manually"))

    return issues


def ref_val_of(ref_feature):
    v = (ref_feature.qualifiers.get("transl_table") or [None])[0] if ref_feature else None
    return v
