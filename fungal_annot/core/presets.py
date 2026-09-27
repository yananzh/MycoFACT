"""基因预设（§6.3）：feature 白名单、密码表兜底值、别名。配置见 resources/presets.json。

线粒体蛋白编码 marker 的预设密码表为 4（霉菌型线粒体）；酵母型线粒体（3 号表）与
Candida 类核基因（12 号表）由参考 qualifier / 用户覆盖决定，见 §2.3 与
feature_transfer.resolve_transl_table。
"""
import json
import os
from dataclasses import dataclass, field

_PRESETS_PATH = os.path.join(os.path.dirname(__file__), "..", "resources", "presets.json")


@dataclass
class GenePreset:
    name: str
    kind: str                      # "CDS" / "rRNA"
    transl_table: int | None       # 密码表兜底值；rRNA 为 None（非编码不得赋表，§2.3）
    feature_types: list
    mito: bool = False
    manual_confirm: bool = False   # 线粒体 marker 默认"需人工确认"（§1.1 范围说明）
    aliases: list = field(default_factory=list)


def load_presets(path: str | None = None) -> dict[str, GenePreset]:
    path = path or _PRESETS_PATH
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    out = {}
    for name, d in raw.items():
        out[name] = GenePreset(
            name=name,
            kind=d["kind"],
            transl_table=d.get("transl_table"),
            feature_types=d.get("feature_types", []),
            mito=bool(d.get("mito")),
            manual_confirm=bool(d.get("manual_confirm")),
            aliases=d.get("aliases", []),
        )
    return out


def get(name: str, presets: dict[str, GenePreset] | None = None) -> GenePreset | None:
    """按预设名或别名查找，大小写不敏感。"""
    if not name:
        return None
    presets = presets if presets is not None else load_presets()
    key = name.strip().lower()
    for p in presets.values():
        if p.name.lower() == key:
            return p
    for p in presets.values():
        if key in (a.lower() for a in p.aliases):
            return p
    return None
