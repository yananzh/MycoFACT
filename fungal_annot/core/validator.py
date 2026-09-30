"""自动验证（§6.6）：翻译 / 边界 / 密码表一致性 / identity 门禁 / Seq ID / N 区段边界。
所有问题输出为结构化 Issue，驱动状态灯。source 修饰符由 BankIt 门户采集，不在
.tbl 中，也不在本工具校验范围。

状态判定：status_of(issues) → red（任一 error）/ yellow（有 warning）/ green。
"""
import re

from Bio.Data.CodonTable import TranslationError
from Bio.Seq import Seq

from .feature_transfer import _spliced_cds, resolve_transl_table
from .models import Issue

SEQID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-|+]*$")
_STOPS = ("TAA", "TAG", "TGA")


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

    # ---- 零产出：没有任何可提交 feature 时必须报错，不得绿灯放行 ----
    # 只有 >Feature 记录头的 .tbl 会被 BankIt 拒收，导出侧也会跳过它；
    # 若不在这里报 error，用户看到的是"绿灯 + 空表"这一最坏组合。
    if not features:
        if not ref_features:
            issues.append(Issue(
                "error", "no_reference_features",
                f"The reference record has no feature matching the "
                f"'{preset.name if preset else 'selected'}' preset whitelist - "
                "choose another reference or gene preset"))
        else:
            issues.append(Issue(
                "error", "no_features_transferred",
                "No feature could be transferred from the reference (every candidate "
                "segment was dropped) - manual review required"))

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

    # source 修饰符不校验：BankIt 门户模式下 source 不在 .tbl 中，
    # organism/来源信息由门户表单采集并校验（§7.2 P1/P5）。

    # ---- CDS 逐条检查 ----
    ref_cds = [f for f in ref_features if f.ftype == "CDS"]
    new_cds = [f for f in features if f.ftype == "CDS"]
    if len(ref_cds) != len(new_cds):
        issues.append(Issue("info", "cds_pairing",
                            "Transferred CDS count differs from the reference (some skipped/dropped); pairing by reference coordinates"))
    for f in new_cds:
        ref_f = _match_ref_cds(f, ref_cds)
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
            try:
                aa = _translate(frame, table)
            except TranslationError:
                # 含不可翻译字符（如比对导出的 gap '-'）：结构化报错，跳过该 CDS
                # 的后续检查，而不是让 TranslationError 穿出管线使整批崩溃
                issues.append(Issue(
                    "error", "invalid_residue",
                    "CDS contains characters that cannot be translated "
                    "(e.g. alignment gaps '-') - clean up the sequence first"))
                continue
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
                                        "3' end is not partial but CDS length is not a multiple of "
                                        "three - possible frameshift (missing/extra base)"))
                elif aa and aa[-1] != "*" and frame[-3:] not in _STOPS:
                    issues.append(Issue("warning", "no_stop_codon", "3' end complete but no stop codon"))
            if not p5 and frame[:3] != "ATG":
                issues.append(Issue("warning", "no_start_codon", "5' end complete but no ATG start codon"))
            # 蛋白回检：与参考蛋白 pairwise identity（§6.6）
            if ref_f is not None and aa:
                ref_cs = int((ref_f.qualifiers.get("codon_start") or ["1"])[0])
                try:
                    ref_aa = _translate(
                        _spliced_cds(ref_f.parts, ref_f.strand, ref_seq)[ref_cs - 1:],
                        table)
                except TranslationError:    # 参考含异常字符 → 跳过回检，不阻塞验证
                    ref_aa = None
                if ref_aa is not None:
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
        if nt is None:
            # 查不了 ≠ 通过：CDS 全无参考坐标（手工新增的行、或溯源丢失）时
            # 门禁无法计算，必须显式提示，不得静默跳过（历史缺陷：编辑后
            # 该门禁消失，低相似序列被误判为绿灯）
            issues.append(Issue(
                "warning", "ref_context_missing",
                "No reference coordinates are available for the CDS, so the nucleotide "
                "identity gate and the reference back-checks were skipped; "
                "verify the coordinates against the reference manually"))
    else:
        nt = mapping.identity()
    if nt is not None and nt * 100 < cfg.identity_threshold:
        issues.append(Issue(
            "error", "low_identity",
            f"Nucleotide identity {nt:.1%} is below threshold {cfg.identity_threshold}%; "
            "confirm the reference choice manually"))

    return issues


def _match_ref_cds(feature, ref_cds):
    """按参考坐标把迁移后的 CDS 配回来源参考 CDS（迁移会跳过/丢弃部分 feature，
    按下标配对会错位，导致密码表与蛋白回检取自错误的基因）。"""
    key = getattr(feature, "ref_key", None)
    if key is None:
        return None
    for rf in ref_cds:
        if not rf.parts:
            continue
        lo = min(p.start for p in rf.parts)
        hi = max(p.end for p in rf.parts)
        if lo <= key[0] and key[1] <= hi:      # 保留段必落在来源 CDS 区间内
            return rf
    return None


def ref_val_of(ref_feature):
    v = (ref_feature.qualifiers.get("transl_table") or [None])[0] if ref_feature else None
    return v
