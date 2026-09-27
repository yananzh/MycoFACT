"""图标助手（Phase 1）：qtawesome 封装，缺失时优雅降级为无图标。"""
from PyQt6.QtGui import QIcon

ACCENT = "#2D7DD2"
NEUTRAL = "#57606a"
OK = "#1a7f37"
WARN = "#9a6700"
BAD = "#cf222e"


def icon(name: str, color: str = NEUTRAL) -> QIcon:
    """按 fa5 名称取图标；qtawesome 不可用或名称无效时返回空图标。"""
    try:
        import qtawesome as qta
        return qta.icon(name, color=color)
    except Exception:
        return QIcon()
