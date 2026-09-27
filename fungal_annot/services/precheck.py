"""table2asn 官方预检（§6.7）：对本目录的 .fsa/.tbl 配对运行 NCBI 官方验证。

标志以 table2asn 官方文档为准；首次接入真实二进制时请用官方样例数据核对
命令行参数（-e 输入目录、-t 模板）。未安装时返回明确提示而不是报错。
"""
import glob
import os
import shutil
import subprocess


def find_table2asn(settings: dict | None = None) -> str | None:
    exe = (settings or {}).get("table2asn_path", "").strip()
    if exe and (shutil.which(exe) or os.path.isfile(exe)):
        return exe
    found = shutil.which("table2asn")
    return found


def run_precheck(directory: str, exe: str, sbt_template: str = "",
                 timeout: int = 180) -> tuple[bool, str]:
    """运行 table2asn 验证目录内全部 .fsa/.tbl 配对。

    返回 (ok, 汇总文本)。ok 依据返回码；.val 报告内容附加在文本末尾。
    """
    if not os.path.isdir(directory):
        return False, f"Directory not found: {directory}"
    cmd = [exe, "-e", directory]
    if sbt_template and os.path.isfile(sbt_template):
        cmd += ["-t", sbt_template]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, errors="replace")
    except (OSError, subprocess.TimeoutExpired) as ex:
        return False, f"table2asn failed to run: {ex}"
    parts = [f"Command: {' '.join(cmd)}", f"Return code: {proc.returncode}"]
    if proc.stdout.strip():
        parts.append("-- stdout --\n" + proc.stdout.strip())
    if proc.stderr.strip():
        parts.append("-- stderr --\n" + proc.stderr.strip())
    for val in sorted(glob.glob(os.path.join(directory, "*.val"))):
        with open(val, encoding="utf-8", errors="replace") as fh:
            content = fh.read().strip()
        if content:
            parts.append(f"-- {os.path.basename(val)} --\n{content}")
    return proc.returncode == 0, "\n\n".join(parts)
