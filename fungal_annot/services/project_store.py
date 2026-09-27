"""JSON 项目存取（§7.3）：保存/加载完整中间状态，可随时关闭续作。

含版本号字段，为将来格式变更预留迁移（§3）。比对上下文（AnnotateDetail）
不序列化——加载后如需编辑重验，重新执行一次注释即可。
"""
import json
import os
import time
from dataclasses import dataclass, field

PROJECT_VERSION = 1


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
    with open(_settings_path(), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(settings, fh, ensure_ascii=False, indent=1)


def save_project(path: str, sequences, hits: dict, selected_ref: dict,
                 results: dict, settings: dict | None = None) -> None:
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
        "selected_ref": selected_ref,
        "results": {k: {
            "seq_id": r.seq_id,
            "status": r.status,
            "issues": [{"level": i.level, "code": i.code, "message": i.message}
                       for i in r.issues],
            "provenance": vars(r.provenance),
            "tbl_text": r.tbl_text,
            "fsa_text": r.fsa_text,
        } for k, r in results.items()},
        "settings": settings or {},
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)   # 原子替换，避免半写文件


def load_project(path: str):
    """返回 (sequences, hits, selected_ref, results, settings)。

    results 反序列化为轻量 SeqResultLite（detail=None）。"""
    from ..core.blast_runner import BlastHit
    from ..core.models import Issue, Provenance, SeqInput

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
    selected_ref = data.get("selected_ref", {})
    results = {}
    for k, r in data.get("results", {}).items():
        res = SeqResultLite(seq_id=r["seq_id"], status=r["status"],
                            tbl_text=r["tbl_text"], fsa_text=r["fsa_text"])
        res.issues = [Issue(i["level"], i["code"], i["message"]) for i in r["issues"]]
        prov = Provenance()
        for f, v in r["provenance"].items():
            setattr(prov, f, v)
        res.provenance = prov
        results[k] = res

    return sequences, hits, selected_ref, results, data.get("settings", {})


@dataclass
class SeqResultLite:
    """加载项目时的轻量结果（无比对上下文，不支持编辑重验）。"""
    seq_id: str
    status: str = "red"
    tbl_text: str = ""
    fsa_text: str = ""
    issues: list = field(default_factory=list)
    provenance: object = None
    features: list = field(default_factory=list)
    detail: object = None
