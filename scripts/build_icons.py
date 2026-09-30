"""从 SVG logo 生成跨平台应用图标（写入 fungal_annot/resources/icons/）。

输入：assets/logos/logo_a_helix_mushroom.svg（设计源，改 logo 后重跑本脚本）
输出：
- mycofact_{16,24,32,48,64,128,256,512,1024}.png  各尺寸位图（Qt 窗口图标/Linux）
- mycofact.ico   多尺寸 Windows EXE 图标
- mycofact.icns  macOS App 图标

用法：python scripts/build_icons.py
依赖：PyQt6（QSvgRenderer 栅格化，offscreen 平台无需显示器）+ Pillow（ICO/ICNS）。
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG = os.path.join(REPO, "assets", "logos", "logo_a_helix_mushroom.svg")
OUT_DIR = os.path.join(REPO, "fungal_annot", "resources", "icons")

# 16-512 供 Qt 窗口图标逐尺寸取用；1024 另存（macOS dock / hicolor 常用上限）
PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = ((16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
             (128, 128), (256, 256))
ICNS_SIZES = (16, 32, 64, 128, 256, 512, 1024)   # ICNS 规范尺寸


def render_pngs() -> None:
    """用 QSvgRenderer 把 SVG 栅格化为各尺寸带透明通道的 PNG。"""
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QGuiApplication, QColor, QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    # offscreen：无显示器的 CI/远程环境同样可跑；PyQt6 wheel 自带该平台插件
    app = QGuiApplication(["build_icons", "-platform", "offscreen"])
    renderer = QSvgRenderer(SVG)
    if not renderer.isValid():
        sys.exit(f"SVG 无法解析：{SVG}")
    for size in PNG_SIZES:
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        img.save(os.path.join(OUT_DIR, f"mycofact_{size}.png"), "PNG")
    app.quit()          # 显式退出，避免多 QGuiApplication 实例警告


def build_ico() -> None:
    from PIL import Image

    base = Image.open(os.path.join(OUT_DIR, f"mycofact_{ICO_SIZES[-1][0]}.png"))
    base.save(os.path.join(OUT_DIR, "mycofact.ico"),
              format="ICO", sizes=ICO_SIZES)


def build_icns() -> None:
    from PIL import Image

    frames = [Image.open(os.path.join(OUT_DIR, f"mycofact_{s}.png"))
              for s in ICNS_SIZES]
    frames[-1].save(os.path.join(OUT_DIR, "mycofact.icns"),
                    format="ICNS", append_images=frames[:-1])


def main() -> None:
    if not os.path.isfile(SVG):
        sys.exit(f"找不到 logo 源文件：{SVG}")
    os.makedirs(OUT_DIR, exist_ok=True)
    render_pngs()
    build_ico()
    build_icns()
    print(f"图标已生成 → {OUT_DIR}")


if __name__ == "__main__":
    main()
