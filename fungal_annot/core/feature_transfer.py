"""注释迁移规则（§6.5）：partial / join 逐段 / 链组合 / codon_start / qualifier 三分表。

坐标转换模型：所有迁移先在"比对空间"（参考→查询或其 RC）完成，再统一换算回宿主
（FASTA 原始方向）坐标——反向互补时链取组合、'<'/'> '标记随坐标端对调，由
FeaturePart.partial_low/high 绑定坐标端的语义保证。
"""
import re

from .models import Feature, FeaturePart, Issue

# §6.5 三分表
INHERIT_QUALIFIERS = ("product", "gene", "gene_synonym", "EC_number", "note")
_COMPLETE_RE = re.compile(r"complete\s+(cds|sequence)", re.I)
_STOPS = ("TAA", "TAG", "TGA")


class TransferOutcome:
    def __init__(self, features, issues):
        self.features = features
        self.issues = issues


def codon_start_for(missing_5: int, ref_codon_start: int = 1) -> int:
    """§2.1 公式：codon_start = ((3 − m mod 3) mod 3) + 1，m 为 5' 端缺失的碱基数。

    参考 CDS 自身 5' partial 时需计入其缺失量。注意 codon_start 与缺失数是**模 3
    互补**关系：codon_start=k 表示参考在首个完整密码子前跳过了 k-1 个碱基，即相对
    完整基因缺失 (3-(k-1)) mod 3 个碱基——不是 k-1 个。不变式：查询与参考 CDS 完全
    一致（missing_5=0）时，输出 codon_start 必须等于参考自身的 codon_start。
    """
    m = missing_5 + (3 - (ref_codon_start - 1)) % 3
    return ((3 - m % 3) % 3) + 1


def resolve_transl_table(ref_feature, preset, user_table: int | None = None):
    """§2.3 密码表优先级：参考 qualifier 优先 → 用户覆盖 → 预设兜底。

    返回 (table, conflict, certain)。conflict=参考与最终选择不一致（不静默取其一）；
    certain=是否可确定为最终表（决定翻译失败的判级，§6.6）。
    """
    ref_val = None
    if ref_feature is not None:
        v = ref_feature.qualifiers.get("transl_table")
        if v:
            try:
                ref_val = int(v[0])
            except (TypeError, ValueError):
                ref_val = None
    preset_val = preset.transl_table if preset else None
    if user_table is not None:
        chosen = user_table
    elif ref_val is not None:
        chosen = ref_val
    elif preset_val is not None:
        chosen = preset_val
    else:
        return None, False, False
    conflict = ref_val is not None and chosen != ref_val
    certain = ref_val is not None or preset_val is not None or user_table is not None
    return chosen, conflict, certain


def _missing_5(ref_parts, lo: int, hi: int, strand: int) -> int | None:
    """5' 端（CDS 读码方向）缺失的 CDS（exon）碱基数。

    plus：累计位于首个保留碱基低坐标侧的 CDS 段全长及同段内被裁掉的部分；
    minus：累计高坐标侧。ref_parts 即参考 CDS 的全部 exon 段（升序）。
    """
    retained = [p for p in ref_parts if p.end >= lo and p.start <= hi]
    if not retained:
        return None
    if strand >= 0:
        p0 = min(retained, key=lambda p: max(p.start, lo))
        first = max(p0.start, lo)
        m = sum(p.end - p.start + 1 for p in ref_parts if p.end < first)
        m += first - p0.start
    else:
        p0 = max(retained, key=lambda p: min(p.end, hi))
        first = min(p0.end, hi)
        m = sum(p.end - p.start + 1 for p in ref_parts if p.start > first)
        m += p0.end - first
    return m


def _rewrite_note(text: str, is_partial: bool) -> str:
    """partial 化后清除 "complete cds / complete sequence" 类完整性断言（§6.5）。"""
    if not is_partial:
        return text
    return _COMPLETE_RE.sub(lambda m: f"partial {m.group(1)}", text)


def _spliced_cds(parts, strand: int, seq: str) -> str:
    """宿主坐标 → 拼接 CDS（读码方向）。minus 链 = revcomp(升序拼接)，
    数学上等价于各段 revcomp 后倒序连接。"""
    s = "".join(seq[p.start - 1:p.end] for p in parts)
    if strand < 0:
        from .align_mapper import revcomp
        s = revcomp(s)
    return s


def transfer_features(ref_features, mapping, query_len: int,
                      auto_partial: bool = True, query_seq: str = "") -> TransferOutcome:
    """将参考 feature 迁移到查询序列（宿主坐标）。

    ref_features 顺序保持；无法迁移的 feature 跳过并记 issue，
    因此输出的 CDS 列表与 ref 中 CDS 列表可能不同长——validator 按 CDS 顺序配对。
    CDS 恒显式输出 codon_start（含 =1）；transl_table 不写入 .tbl。
    """
    lo, hi = mapping.aligned_ref_interval
    out, issues = [], []

    for feat in ref_features:
        is_cds = feat.ftype == "CDS"
        ref_cs = 1
        if is_cds:
            v = feat.qualifiers.get("codon_start")
            if v:
                ref_cs = int(v[0])

        # ---- 逐段映射（比对空间）----
        parts_rc, dropped_outside, clipped = [], 0, 0
        dropped_before = dropped_after = False
        for p in feat.parts:
            if p.end < lo or p.start > hi:
                dropped_outside += 1          # §6.5：区间外 = 正常 partial 语义，非 error
                if p.end < lo:
                    dropped_before = True     # 低坐标侧被截断（读码方向取决 strand）
                else:
                    dropped_after = True
                continue
            s = max(p.start, lo)
            e = min(p.end, hi)
            clip_low = p.start < lo
            clip_high = p.end > hi
            if clip_low or clip_high:
                clipped += 1                  # 部分覆盖（查询只覆盖基因一端）同样是 partial 语义
            qs, shrink_l = mapping.map_point(s, "right")
            qe, shrink_r = mapping.map_point(e, "left")
            if qs is None or qe is None or qs >= qe:
                # 区间内却映射失败或塌缩（查询缺失该段），禁止静默（§6.5）
                issues.append(Issue(
                    "error", "exon_map_fail",
                    f"{feat.ftype} segment {p.start}..{p.end} lies inside the aligned interval but cannot be mapped"
                    " (deletion/gap in query); segment dropped - manual review required"))
                continue
            parts_rc.append(FeaturePart(
                start=int(qs), end=int(qe),
                partial_low=bool(p.partial_low or clip_low or shrink_l),
                partial_high=bool(p.partial_high or clip_high or shrink_r),
                ref_start=int(s), ref_end=int(e)))
        if not parts_rc:
            issues.append(Issue("info", "feature_skipped",
                                f"{feat.ftype} reference feature does not overlap the query-covered region; not transferred"))
            continue
        if dropped_before or dropped_after:
            # A2：被丢弃的段是参考 feature 在查询覆盖区外的延续，其截断语义必须落到
            # 保留段对应的坐标端（partial 标记绑定坐标端，故与 strand 无关；反向查询
            # 的换端在后续 RC 转换里统一处理）。
            if dropped_before:
                parts_rc[0].partial_low = True
            if dropped_after:
                parts_rc[-1].partial_high = True
        if dropped_outside or clipped:
            n = dropped_outside + clipped
            issues.append(Issue(
                "warning", "exon_outside_aligned",
                f"{feat.ftype}: {n} segment(s) outside the query-covered region ({dropped_outside} fully outside, "
                f"clipped {clipped}); treated as partial (partial amplicons are normal, not an error)"))

        # ---- RC → 宿主坐标：链取组合，partial 标记换端 ----
        if mapping.orientation == "reverse":
            conv = [FeaturePart(start=query_len + 1 - p.end, end=query_len + 1 - p.start,
                                partial_low=p.partial_high, partial_high=p.partial_low,
                                ref_start=p.ref_start, ref_end=p.ref_end)
                    for p in parts_rc]
            strand_native = -feat.strand
        else:
            conv = parts_rc
            strand_native = feat.strand
        conv.sort(key=lambda x: (x.start, x.end))
        first, last = conv[0], conv[-1]

        # ---- CDS：缺失碱基数 / codon_start / 完整性（豁免判定用）----
        m_total, cs_val, cds_reads, complete_start, complete_stop = 0, 1, "", False, False
        if is_cds:
            m = _missing_5(feat.parts, lo, hi, feat.strand)
            m_total = m or 0
            cs_val = codon_start_for(m_total, ref_cs)
            cds_reads = _spliced_cds(conv, strand_native, query_seq)
            frame = cds_reads[cs_val - 1:]
            # 参考自身在该端 partial 时，完整密码子不可能存在（其起始/终止在记录之外）
            # codon_start>1 按定义即表示 5' 截断（即便记录漏写 '<' 标记）
            ref_p5 = (feat.parts[-1].partial_high if feat.strand < 0
                      else feat.parts[0].partial_low) or ref_cs > 1
            ref_p3 = (feat.parts[0].partial_low if feat.strand < 0
                      else feat.parts[-1].partial_high)
            complete_start = (m_total == 0 and not ref_p5 and not dropped_before
                              and frame[:3] == "ATG")
            complete_stop = (len(frame) % 3 == 0 and frame[-3:] in _STOPS
                             and not ref_p3 and not dropped_after)

        # ---- 触及序列端点的自动 partial（§2.1，可全局关闭；完整密码子豁免）----
        touches_low = first.start == 1
        touches_high = last.end == query_len
        auto5 = touches_high if strand_native < 0 else touches_low
        auto3 = touches_low if strand_native < 0 else touches_high
        if auto_partial and (auto5 or auto3):
            if is_cds:
                if auto5 and not complete_start:
                    if strand_native < 0:
                        last.partial_high = True
                    else:
                        first.partial_low = True
                if auto3 and not complete_stop:
                    if strand_native < 0:
                        first.partial_low = True
                    else:
                        last.partial_high = True
            else:
                if auto5:      # 5' 端：正链=低坐标端，负链=高坐标端
                    if strand_native < 0:
                        last.partial_high = True
                    else:
                        first.partial_low = True
                if auto3:      # 3' 端：正链=高坐标端，负链=低坐标端
                    if strand_native < 0:
                        first.partial_low = True
                    else:
                        last.partial_high = True
        struct5 = last.partial_high if strand_native < 0 else first.partial_low
        struct3 = first.partial_low if strand_native < 0 else last.partial_high

        # ---- qualifier 三分表：继承白名单，其余一律丢弃（含标识类，§6.5）----
        is_partial = struct5 or struct3
        new_q = {}
        for k, vals in feat.qualifiers.items():
            if k in INHERIT_QUALIFIERS:
                if k in ("note", "product"):
                    vals = [_rewrite_note(v, is_partial) for v in vals]
                new_q[k] = list(vals)
        if is_cds:
            new_q["codon_start"] = [str(cs_val)]   # 恒写（含 =1，显式相位）

        spans = [(p.ref_start, p.ref_end) for p in conv if p.ref_start and p.ref_end]
        ref_key = ((min(s for s, _ in spans), max(e for _, e in spans))
                   if spans else None)
        out.append(Feature(ftype=feat.ftype, strand=strand_native,
                           parts=conv, qualifiers=new_q, ref_key=ref_key))

    return TransferOutcome(out, issues)
