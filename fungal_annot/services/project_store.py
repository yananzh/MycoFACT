"""JSON 项目存取（§7.3）：保存/加载完整中间状态，可随时关闭续作。

v2 格式（多参考对比）：results[seq_id] = {chosen, variants{accession → 结果}}，
selected_refs[seq_id] = [accession, ...]（1-5 个，按排名序）。
v1 格式（单参考）加载时迁移：单结果 → 单 variant（accession 取 provenance.reference），
即为采纳者；selected_ref 单值 → 单元素列表。

比对上下文（AnnotateDetail）不序列化——加载后如需编辑重验，重新执行一次注释即可。
"""
import json
import os
import time
from dataclasses import dataclass, field

from ..core.tbl_writer import tbl_text_from

PROJECT_VERSION = 2


def _settings_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".fungal_annot", "settings.json")


def load_settings() -> dict:
    try:
        with open(_settings_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict) -> None:
    os.makedirs(os.path.dirname(_settings_path()), exist_ok=True)
    # 原子替换（与 save_project 同一标准）：中途崩溃/磁盘满不留半写文件，
    # 否则 load_settings 会把截断的 JSON 静默重置为 {}，丢失全部用户设置
    path = _settings_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(settings, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _feature_to_dict(f) -> dict:
    return {
        "ftype": f.ftype, "strand": int(f.strand),
        "parts": [[int(p.start), int(p.end), bool(p.partial_low),
                   bool(p.partial_high), int(p.ref_start), int(p.ref_end)]
                  for p in f.parts],
        "qualifiers": {k: list(v) for k, v in f.qualifiers.items()},
        "ref_key": list(f.ref_key) if f.ref_key else None,
    }


def _feature_from_dict(d):
    from ..core.models import Feature, FeaturePart
    return Feature(
        ftype=d["ftype"], strand=int(d["strand"]),
        parts=[FeaturePart(*p) for p in d["parts"]],
        qualifiers={k: list(v) for k, v in d["qualifiers"].items()},
        ref_key=tuple(d["ref_key"]) if d.get("ref_key") else None)


def _result_to_dict(r) -> dict:
    return {
        "seq_id": r.seq_id,
        "status": r.status,
        "gene_type": getattr(r, "gene_type", ""),
        "issues": [{"level": i.level, "code": i.code, "message": i.message}
                   for i in r.issues],
        "provenance": vars(r.provenance),
        # 与 features 现算保持一致：结果对象上缓存的文本可能落后于表格编辑，
        # 直接存会把"表与文本不符"冻结进项目文件
        "tbl_text": tbl_text_from(r.features, r.seq_id, r.tbl_text),
        "fsa_text": r.fsa_text,
        "features": [_feature_to_dict(f) for f in (r.features or [])],
    }


def _result_from_dict(r):
    from ..core.models import Issue, Provenance
    res = SeqResultLite(seq_id=r["seq_id"], status=r["status"],
                        tbl_text=r["tbl_text"], fsa_text=r["fsa_text"])
    res.gene_type = r.get("gene_type", "")
    res.features = [_feature_from_dict(d) for d in r.get("features", [])]
    # 旧项目文件里可能存着与 features 不符的文本：加载时按 features 校正
    res.tbl_text = tbl_text_from(res.features, res.seq_id, res.tbl_text)
    res.issues = [Issue(i["level"], i["code"], i["message"]) for i in r["issues"]]
    prov = Provenance()
    for f, v in r["provenance"].items():
        setattr(prov, f, v)
    res.provenance = prov
    return res


def save_project(path: str, sequences, hits: dict, selected_refs: dict,
                 results: dict, settings: dict | None = None,
                 confirmed: dict | None = None, exported: bool = False,
                 chosen_ref: dict | None = None) -> None:
    """results 形如 {seq_id: {accession: SeqResult}}；chosen_ref[seq_id] 为采纳导出的
    variant（缺省时取该序列的第一个 variant）。"""
    data = {
        "version": PROJECT_VERSION,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sequences": [
            {"seq_id": s.seq_id, "seq": s.seq, "gene_type": s.gene_type,
             "source_qualifiers": s.source_qualifiers}
            for s in sequences
        ],
        "hits": {k: [vars(h) | {"flags": dict(h.flags)} for h in v]
                 for k, v in hits.items()},
        "selected_refs": {k: list(v) for k, v in (selected_refs or {}).items()},
        "results": {k: {
            "chosen": (chosen_ref or {}).get(k, ""),
            "variants": {acc: _result_to_dict(r) for acc, r in v.items()},
        } for k, v in results.items()},
        # 审核状态一并持久化：红灯手动确认与已导出标记必须跨会话保留，
        # 否则重新打开项目后导出被再次拦截（确认作废）
        "confirmed": dict(confirmed or {}),
        "exported": bool(exported),
        "settings": settings or {},
    }
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)   # 原子替换，避免半写文件
    except BaseException:
        try:
            os.remove(tmp)      # 中途失败不留 .tmp 垃圾文件
        except OSError:
            pass
        raise


def _load_v1_results(data: dict):
    """v1（单参考）→ v2 结构：单结果成为唯一 variant，accession 取 provenance.reference。"""
    variants_by_sid = {}
    for sid, r in data.get("results", {}).items():
        acc = ((r.get("provenance") or {}).get("reference")
               or (data.get("selected_ref", {}) or {}).get(sid) or "reference")
        variants_by_sid[sid] = {acc: r}
    selected_refs = {k: ([v] if v else [])
                     for k, v in (data.get("selected_ref", {}) or {}).items()}
    return variants_by_sid, selected_refs


def load_project(path: str):
    """返回 (sequences, hits, selected_refs, results, settings, confirmed,
    exported, chosen_ref)。

    results 形如 {seq_id: {accession: SeqResultLite}}（detail=None）；
    chosen_ref[seq_id] 为采纳导出的 variant accession。"""
    from ..core.blast_runner import BlastHit
    from ..core.models import SeqInput

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    version = data.get("version", 0)
    if version > PROJECT_VERSION:
        raise ValueError(f"Project file version {version} is newer than the supported version {PROJECT_VERSION}")

    sequences = [SeqInput(seq_id=d["seq_id"], seq=d["seq"],
                          gene_type=d.get("gene_type", ""),
                          source_qualifiers=d.get("source_qualifiers", {}))
                 for d in data.get("sequences", [])]
    hits = {k: [BlastHit(accession=h["accession"], title=h["title"],
                         pident=h["pident"], qcovs=h["qcovs"], evalue=h["evalue"],
                         subject_len=h["subject_len"], subject_start=h["subject_start"],
                         subject_end=h["subject_end"], flags=h["flags"])
                for h in v]
            for k, v in data.get("hits", {}).items()}
    if version >= 2:
        selected_refs = {k: list(v) for k, v in data.get("selected_refs", {}).items()}
        raw = {sid: (v.get("variants", {}), v.get("chosen", ""))
               for sid, v in data.get("results", {}).items()}
    else:
        raw_variants, selected_refs = _load_v1_results(data)
        raw = {sid: (variants, "") for sid, variants in raw_variants.items()}

    results: dict[str, dict] = {}
    chosen_ref: dict[str, str] = {}
    for sid, (variants_raw, chosen) in raw.items():
        variants = {acc: _result_from_dict(r) for acc, r in variants_raw.items()}
        results[sid] = variants
        chosen_ref[sid] = chosen if chosen in variants else (
            next(iter(variants)) if variants else "")

    return (sequences, hits, selected_refs, results, data.get("settings", {}),
            data.get("confirmed", {}), bool(data.get("exported", False)), chosen_ref)


@dataclass
class SeqResultLite:
    """加载项目时的轻量结果（无比对上下文，不支持编辑重验）。

    features 从项目文件恢复，因此审核表格与导出汇总对已加载项目同样正确；
    detail 仍为 None（映射上下文不序列化），编辑后重验会被拒绝并提示重新注释。
    """
    seq_id: str
    status: str = "red"
    tbl_text: str = ""
    fsa_text: str = ""
    gene_type: str = ""
    issues: list = field(default_factory=list)
    provenance: object = None
    features: list = field(default_factory=list)
    detail: object = None

    def report_row(self) -> dict:
        """与 pipeline.SeqResult.report_row 同构（键与取值语义完全一致）。"""
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
            "nt_identity": (f"{p.nt_identity:.4f}"
                            if p.nt_identity is not None else ""),
            "issues": "; ".join(f"[{i.level}] {i.code}: {i.message}"
                                for i in self.issues),
        }
