# -*- mode: python ; coding: utf-8 -*-
"""MycoFACT PyInstaller 打包配置（开发计划 §10 / M6）：--onedir 三平台分发。

数据文件按源码树布局落进解包目录，运行时由 fungal_annot.paths.resource_path
解析。macOS 额外产出 MycoFACT.app（未签名，首启需右键 → 打开绕过 Gatekeeper）。
"""
import sys

from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["main.py"],
    datas=[
        ("fungal_annot/resources/presets.json", "fungal_annot/resources"),
        ("fungal_annot/resources/style.qss", "fungal_annot/resources"),
        ("demo/example.fasta", "demo"),
    ],
    hiddenimports=[
        m for m in collect_submodules("fungal_annot")
        if not m.startswith("fungal_annot.tests")
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MycoFACT",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MycoFACT",
)

if sys.platform == "darwin":
    app = BUNDLE(coll, name="MycoFACT.app")
