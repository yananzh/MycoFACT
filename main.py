"""应用入口。

- `python main.py` → 启动 PyQt6 图形界面（M3–M5）
- `python main.py run|presets …` → CLI（M1–M2，见 fungal_annot/cli.py）
"""
import os
import sys

from fungal_annot.paths import resource_path


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] in ("run", "presets", "-h", "--help"):
        from fungal_annot.cli import main as cli_main
        return cli_main(argv)
    from PyQt6.QtWidgets import QApplication

    from fungal_annot.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    qss = resource_path("fungal_annot", "resources", "style.qss")
    if os.path.isfile(qss):
        with open(qss, encoding="utf-8") as fh:
            app.setStyleSheet(fh.read())
    win = MainWindow()

    # PyQt6 对 slot 内未捕获的异常默认 qFatal（整个进程退出）。安装自定义
    # excepthook 后改为记录日志，界面保持可用（§7.3 非阻塞与异常处理）。
    def _gui_excepthook(etype, value, tb):
        import traceback
        text = "".join(traceback.format_exception(etype, value, tb))
        sys.stderr.write(text)
        try:
            win.log("Unhandled error: " + text.strip().splitlines()[-1])
        except Exception:
            pass

    sys.excepthook = _gui_excepthook

    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
