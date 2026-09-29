"""单序列流水线编排（§4 数据流）：参考获取 → 比对 → 迁移 → source 组装 →
验证 → 导出文本。核心层复用：CLI 与未来 UI/后台线程共用同一入口。
"""
import os
import re
from dataclasses import dataclass, field

from Bio.Data.CodonTable import TranslationError

from ..core.align_mapper import AlignmentError, build_mapping
from ..core.blast_runner import BlastError, rank_hits, run_blast
from ..core.feature_parser import extract_features
from ..core.feature_transfer import transfer_features
from ..core.gb_fetcher import GbFetchError, fetch_gb_text, parse_gb
from ..core.models import Issue, Provenance, SeqInput
from ..core.presets import detect_from_titles, get as get_preset
from ..core.tbl_writer import write_fsa, write_report_csv, write_tbl
from ..core.validator import status_of, validate


@dataclass
class PipelineConfig:
    email: str = ""
    api_key: str = ""
    blast_db: str = "core_nt"   # NCBI 已将 nt 并入 core_nt（空库名会被 Message ID#56 拒绝）
    organism_filter: str = ""
    hitlist_size: int = 50
    identity_threshold: float = 97.0
    window_flank: int = 500
    max_window: int = 500_000
    cache_dir: str | None = None
    auto_partial: bool = True
    user_transl_table: int | None = None
    online: bool = True


@dataclass
class AnnotateDetail:
    """P4 审核页编辑后即时重验所需的对齐上下文（不随项目文件序列化）。"""
    mapping: object = None
    ref_features: list = field(default_factory=list)
    ref_seq: str = ""
    preset: object = None
    ref_len: int = 0                                  # 参考全长（参考 feature table 展示用）
    ref_source_quals: dict = field(default_factory=dict)  # 参考 source 修饰符（只读展示）
    # 管线早期（gene_type 自动判定等）与迁移期（exon_outside_aligned 等）的提示：
    # 重验只替换 validate() 的输出，这部分必须原样保留，否则重查后 warning 凭空消失
    base_issues: list = field(default_factory=list)


@dataclass
class SeqResult:
    seq_id: str
    status: str = "red"
    features: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)
    tbl_text: str = ""
    fsa_text: str = ""
    detail: AnnotateDetail | None = None

    def report_row(self) -> dict:
        p = self.provenance
        return {
            "seq_id": self.seq_id,
            "length": "",
            "gene_type": "",
            "status": self.status,
            "n_features": len(self.features),
            "source": p.source,
            "reference": p.reference,
            "region": p.region,
            "orientation": p.orientation,
            "pident": p.pident,
            "qcovs": p.qcovs,
            "nt_identity": (f"{p.nt_identity:.4f}" if p.nt_identity is not None else ""),
            "issues": "; ".join(f"[{i.level}] {i.code}: {i.message}" for i in self.issues),
        }


def annotate_sequence(seq_input: SeqInput, cfg: PipelineConfig, hits=None,
                      reference_gb_text: str | None = None,
                      reference_accession: str | None = None,
                      progress=None) -> SeqResult:
    """处理单条序列。reference_gb_text（离线）/ reference_accession / hits 任选其一；
    三者皆无时走在线 BLAST。"""
    res = SeqResult(seq_id=seq_input.seq_id)
    L = len(seq_input.seq)
    preset = get_preset(seq_input.gene_type) if seq_input.gene_type else None
    explicit_unknown = bool(seq_input.gene_type) and preset is None
    if explicit_unknown:
        res.issues.append(Issue("error", "preset_unknown",
                                f"Unknown gene type '{seq_input.gene_type}' (see the presets command)"))
        res.status = "red"
        return res
    if preset is not None and preset.manual_confirm:
        res.issues.append(Issue("warning", "preset_manual_confirm",
                                f"{preset.name} is a mitochondrial/minor marker: few reference records, mostly auto-annotated;"
                                "manual confirmation required"))

    try:
        # ---- 1. 参考获取 ----
        rec = None
        if reference_gb_text:
            rec = parse_gb(reference_gb_text)
            res.provenance.source = "local-gb"
            res.provenance.region = "full"
            res.provenance.reference = rec.id
        elif reference_accession:
            text, region = fetch_gb_text(reference_accession, email=cfg.email,
                                         api_key=cfg.api_key, cache_dir=cfg.cache_dir)
            rec = parse_gb(text, region)
            res.provenance.source = "accession"
            res.provenance.region = region
            res.provenance.reference = reference_accession
        else:
            if hits is None:
                if progress:
                    progress("blast", 0.0)
                if not cfg.online:
                    raise BlastError("Offline mode requires --ref-gb or --accession")
                hits = run_blast(seq_input.seq, blast_db=cfg.blast_db,
                                 organism=cfg.organism_filter,
                                 hitlist_size=cfg.hitlist_size)
                hits = rank_hits(hits, preset)   # preset 可为 None（RefSeq 加分跳过）
            if not hits:
                raise BlastError("BLAST returned no hits")
            hit = hits[0]
            # 长参考（基因组级）按 HSP 窗口截取（§6.2）
            window = None
            if hit.subject_len > max(4 * L, 20000):
                window = (hit.subject_start, hit.subject_end)
            text, region = fetch_gb_text(hit.accession, email=cfg.email,
                                         api_key=cfg.api_key, window=window,
                                         flank=cfg.window_flank,
                                         max_window=cfg.max_window,
                                         cache_dir=cfg.cache_dir,
                                         seq_len=hit.subject_len or None)
            rec = parse_gb(text, region)
            res.provenance.source = "blast"
            res.provenance.region = region
            res.provenance.reference = hit.accession
            res.provenance.pident = hit.pident
            res.provenance.qcovs = hit.qcovs

        # ---- 1b. 基因类型自动判定（§6.1：从命中标题/参考注释推断）----
        if preset is None:
            titles = [h.title for h in (hits or [])[:5]]
            if rec is not None:
                for f in rec.features:
                    for qk in ("product", "gene"):
                        titles.extend(f.qualifiers.get(qk, []))
            detected = detect_from_titles(titles)
            if detected is not None:
                seq_input.gene_type = detected.name
                preset = detected
                src_desc = "BLAST hit titles" if hits else "reference annotation"
                res.issues.append(Issue(
                    "info", "gene_type_auto",
                    f"Gene type auto-detected as '{detected.name}' from {src_desc}; "
                    "if wrong, add the correct gene to presets.json"))
            else:
                preset = get_preset("Generic")
                seq_input.gene_type = "Generic"
                res.issues.append(Issue(
                    "warning", "gene_type_generic",
                    "Gene not recognized from hit titles/annotation - using the Generic "
                    "preset (broad feature whitelist, transl table from the reference "
                    "record only). Verify manually, or add the gene to presets.json "
                    "to enable tailored transfer."))
            if progress:
                progress(f"gene type: {seq_input.gene_type}", 0.2)

        # ---- 2. 比对与映射 ----
        if progress:
            progress("align", 0.4)
        ref_seq = str(rec.seq).upper()
        mapping = build_mapping(ref_seq, seq_input.seq)
        res.provenance.orientation = mapping.orientation
        res.provenance.nt_identity = mapping.identity()

        # ---- 3. 迁移 ----
        if progress:
            progress("transfer", 0.7)
        ref_features = extract_features(rec, preset)
        outcome = transfer_features(ref_features, mapping, L,
                                    auto_partial=cfg.auto_partial,
                                    query_seq=seq_input.seq)

        # ---- 4. 验证（source 不在 .tbl 中，由 BankIt 门户采集，§7.2）----
        features = outcome.features
        v_issues = validate(seq_input, features, mapping, ref_features, ref_seq,
                            preset, cfg)
        res.features = features
        base_issues = res.issues + outcome.issues   # 早期提示 + 迁移提示：重验时保留
        res.issues = base_issues + v_issues
        res.status = status_of(res.issues)
        src_feat = next((f for f in rec.features if f.type == "source"), None)
        res.detail = AnnotateDetail(
            mapping=mapping, ref_features=ref_features, ref_seq=ref_seq, preset=preset,
            ref_len=len(ref_seq),
            ref_source_quals=dict(src_feat.qualifiers) if src_feat else {},
            base_issues=base_issues)

        # ---- 5. 导出文本 ----
        res.tbl_text = write_tbl(features, seq_input.seq_id)
        res.fsa_text = write_fsa(seq_input.seq_id, seq_input.seq)
        if progress:
            progress("done", 1.0)
    except (GbFetchError, BlastError, AlignmentError) as ex:
        res.issues.append(Issue("error", "pipeline", str(ex)))
        res.status = "red"
    except (ValueError, TranslationError) as ex:
        # TranslationError 不是 ValueError 子类：序列含 gap 等不可翻译字符时
        # 若不在此兜底，会穿出本函数使 CLI 整批终止（UI 侧仅剩裸堆栈）
        res.issues.append(Issue("error", "pipeline", f"Parse failed: {ex}"))
        res.status = "red"
    return res


def run_batch(seq_inputs, cfg: PipelineConfig, **kwargs) -> list[SeqResult]:
    return [annotate_sequence(s, cfg, **kwargs) for s in seq_inputs]


# Windows 保留文件名字符——其中 : | 是 GenBank Seq ID 的合法字符（validator 的
# SEQID_RE 放行），直接用作文件名会在导出时抛 WinError 123
_WIN_UNSAFE = re.compile(r'[<>:"/\\|?*]')


def _safe_stem(seq_id: str) -> str:
    """Seq ID → 文件名安全主名（Windows 保留字符与首尾点/空格处理）。"""
    return _WIN_UNSAFE.sub("_", seq_id).strip(". ") or "sequence"


def _unique_path(out_dir: str, stem: str, ext: str, used: set[str]) -> str:
    """清洗后的名字若与其他序列冲突（如 'a|b' 与 'a:b' 都变 'a_b'）则追加序号；
    大小写不敏感比较（Windows 文件系统不区分大小写）。"""
    path = os.path.join(out_dir, stem + ext)
    n = 2
    while path.lower() in used:
        path = os.path.join(out_dir, f"{stem}_{n}{ext}")
        n += 1
    used.add(path.lower())
    return path


def write_outputs(results: list[SeqResult], out_dir: str,
                  seq_inputs: list[SeqInput] | None = None,
                  with_fsa: bool = True, with_report: bool = True,
                  stems: list[str] | None = None) -> list[str]:
    """写出 .tbl（每条序列一个）与可选的 .fsa / 验证报告 CSV，返回文件路径列表。

    stems 与 results 对齐的文件名主干覆盖（多参考对比导出未采纳 variant 时用
    "<seq_id>__<accession>"）；缺省取 _safe_stem(seq_id)。

    BankIt 门户模式（GB2sequin 同款工作流）：.tbl 只含 gene/CDS 等 feature，
    不含 source——organism 与来源修饰符在门户表单采集（§7.2 P1/P5）。
    界面导出只要 .tbl（序列本身已在序列表、验证摘要已在审核页呈现）；
    with_fsa / with_report 供 CLI 与测试保留完整产物。
    """
    os.makedirs(out_dir, exist_ok=True)
    written = []
    rows = []
    inputs = {s.seq_id: s for s in (seq_inputs or [])}
    used: set[str] = set()
    for i, r in enumerate(results):
        if with_report:
            row = r.report_row()
            s = inputs.get(r.seq_id)
            if s:
                row["length"] = len(s.seq)
                row["gene_type"] = s.gene_type
            rows.append(row)
        stem = _safe_stem(stems[i]) if stems and i < len(stems) else _safe_stem(r.seq_id)
        tbl = _unique_path(out_dir, stem, ".tbl", used)
        with open(tbl, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(r.tbl_text)
        written.append(tbl)
        if with_fsa:
            fsa = _unique_path(out_dir, stem, ".fsa", used)
            with open(fsa, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(r.fsa_text)
            written.append(fsa)
    if with_report:
        report = os.path.join(out_dir, "validation_report.csv")
        with open(report, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(write_report_csv(rows))
        written.append(report)
    return written
