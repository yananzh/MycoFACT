"""资源路径解析：源码运行与 PyInstaller 打包（--onedir）统一入口。

源码运行时数据根目录是仓库根；打包后随 spec 的 datas 落到
sys._MEIPASS（onedir 时为 _internal 目录）。所有内置数据文件
（fungal_annot/resources/、demo/）都从这里解析，
避免各处按源码目录布局写死相对路径。
"""
import os
import sys


def base_dir() -> str:
    """数据文件根目录：打包后为 PyInstaller 解包目录，源码运行为仓库根目录。"""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return bundled
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    """解析相对数据根目录的资源路径，如 resource_path("demo", "example.fasta")。"""
    return os.path.join(base_dir(), *parts)
