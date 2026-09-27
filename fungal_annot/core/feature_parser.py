"""GB → 内部 Feature 结构，白名单过滤（§6.3）。

source feature 不在此提取——其 qualifier 只采信用户输入，绝不从参考继承（§2.4/§6.5）。
"""
from Bio.SeqFeature import AfterPosition, BeforePosition

from .models import Feature, FeaturePart


def parse_location(feature):
    """解析 feature location → (strand, parts)。

    parts 按 start 升序（参考坐标）；'<'/'> ' partial 标记绑定坐标端
    （partial_low/high），与 5'/3' 端无关。
    """
    loc = feature.location
    strand = loc.strand if loc.strand is not None else 1
    if hasattr(loc, "parts") and len(loc.parts) > 1:
        raw = list(loc.parts)
    else:
        raw = [loc]
    parts = []
    for p in raw:
        s = int(p.start) + 1
        e = int(p.end)
        parts.append(FeaturePart(
            start=s, end=e,
            partial_low=isinstance(p.start, BeforePosition),
            partial_high=isinstance(p.end, AfterPosition),
        ))
    parts.sort(key=lambda x: (x.start, x.end))
    return strand, parts


def extract_features(record, preset) -> list[Feature]:
    """按预设白名单提取可迁移 feature。"""
    whitelist = set(preset.feature_types)
    out = []
    for f in record.features:
        if f.type == "source" or f.type not in whitelist:
            continue
        strand, parts = parse_location(f)
        out.append(Feature(
            ftype=f.type,
            strand=strand,
            parts=parts,
            qualifiers={k: list(v) for k, v in f.qualifiers.items()},
        ))
    return out
