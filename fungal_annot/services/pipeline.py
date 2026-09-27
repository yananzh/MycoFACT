"""单序列流水线编排（§4 数据流）：参考获取 → 比对 → 迁移 → source 组装 →
验证 → 导出文本。核心层复用：CLI 与未来 UI/后台线程共用同一入口。
"""
import os
from dataclasses import dataclass, field

from ..core.align_mapper import AlignmentError, build_mapping
from ..core.blast_runner import BlastError, rank_hits, run_blast
from ..core.feature_parser import extract_features
from ..core.feature_transfer import transfer_features
from ..core.gb_fetcher import GbFetchError, fetch_gb_text, parse_gb
from ..core.models import Feature, FeaturePart, Issue, Provenance, SeqInput
from ..core.presets import get as get_preset
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


def _source_feature(seq_input: SeqInput, length: int) -> Feature:
    quals = {}
    for k, v in seq_input.source_qualifiers.items():
        if v:
            quals[k] = [str(v)]
    quals.setdefault("mol_type", ["genomic DNA"])
    return Feature(ftype="source", strand=1,
                   parts=[FeaturePart(start=1, end=length)], qualifiers=quals)


def annotate_sequence(seq_input: SeqInput, cfg: PipelineConfig, hits=None,
                      reference_gb_text: str | None = None,
                      reference_accession: str | None = None,
                      progress=None) -> SeqResult:
    """处理单条序列。reference_gb_text（离线）/ reference_accession / hits 任选其一；
    三者皆无时走在线 BLAST。"""
    res = SeqResult(seq_id=seq_input.seq_id)
    L = len(seq_input.seq)
    preset = get_preset(seq_input.gene_type)
    if preset is None:
        res.issues.append(Issue("error", "preset_unknown",
                                f"Unknown gene type '{seq_input.gene_type}' (see the presets command)"))
        res.status = "red"
        return res
    if preset.manual_confirm:
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
                hits = rank_hits(hits, preset)
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
                                         cache_dir=cfg.cache_dir)
            rec = parse_gb(text, region)
            res.provenance.source = "blast"
            res.provenance.region = region
            res.provenance.reference = hit.accession
            res.provenance.pident = hit.pident
            res.provenance.qcovs = hit.qcovs

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
        outcome = transfer_features(ref_features, mapping, L, preset,
                                    auto_partial=cfg.auto_partial,
                                    user_transl_table=cfg.user_transl_table,
                                    query_seq=seq_input.seq)

        # ---- 4. source 组装 + 验证 ----
        features = [_source_feature(seq_input, L)] + outcome.features
        v_issues = validate(seq_input, features, mapping, ref_features, ref_seq,
                            preset, cfg)
        res.features = features
        res.issues = outcome.issues + v_issues
        res.status = status_of(res.issues)
        res.detail = AnnotateDetail(mapping=mapping, ref_features=ref_features,
                                    ref_seq=ref_seq, preset=preset)

        # ---- 5. 导出文本 ----
        res.tbl_text = write_tbl(features, seq_input.seq_id)
        res.fsa_text = write_fsa(seq_input.seq_id, seq_input.seq)
        if progress:
            progress("done", 1.0)
    except (GbFetchError, BlastError, AlignmentError) as ex:
        res.issues.append(Issue("error", "pipeline", str(ex)))
        res.status = "red"
    except ValueError as ex:
        res.issues.append(Issue("error", "pipeline", f"Parse failed: {ex}"))
        res.status = "red"
    return res


def run_batch(seq_inputs, cfg: PipelineConfig, **kwargs) -> list[SeqResult]:
    return [annotate_sequence(s, cfg, **kwargs) for s in seq_inputs]


def write_outputs(results: list[SeqResult], out_dir: str,
                  seq_inputs: list[SeqInput] | None = None) -> list[str]:
    """写出 .tbl/.fsa 配对与验证报告 CSV，返回文件路径列表。"""
    os.makedirs(out_dir, exist_ok=True)
    written = []
    rows = []
    inputs = {s.seq_id: s for s in (seq_inputs or [])}
    for r in results:
        row = r.report_row()
        s = inputs.get(r.seq_id)
        if s:
            row["length"] = len(s.seq)
            row["gene_type"] = s.gene_type
        rows.append(row)
        tbl = os.path.join(out_dir, f"{r.seq_id}.tbl")
        fsa = os.path.join(out_dir, f"{r.seq_id}.fsa")
        with open(tbl, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(r.tbl_text)
        with open(fsa, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(r.fsa_text)
        written += [tbl, fsa]
    report = os.path.join(out_dir, "validation_report.csv")
    with open(report, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(write_report_csv(rows))
    written.append(report)
    return written
