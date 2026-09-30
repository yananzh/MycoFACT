<div align="right">

[English](./README.md) | 简体中文

</div>

<div align="center">

<img src="assets/logos/logo_a_helix_mushroom_preview.png" alt="MycoFACT logo" width="128"/>

# MycoFACT

[![CI](https://github.com/yananzh/MycoFACT/actions/workflows/ci.yml/badge.svg)](https://github.com/yananzh/MycoFACT/actions/workflows/ci.yml)
[![Build](https://github.com/yananzh/MycoFACT/actions/workflows/build.yml/badge.svg)](https://github.com/yananzh/MycoFACT/actions/workflows/build.yml)

**真菌多基因鉴定序列 Feature Table 自动生成工具**

</div>

**MycoFACT**（**F**ungal **F**eature **A**nnotation & **C**omparison **T**ool，包名
`fungal_annot`）为真菌 marker 基因序列准备 NCBI BankIt 提交材料。选定参考序列后，
参考 GenBank 记录的注释会按比对坐标迁移到查询序列上——自动产出五列 feature
table（.tbl）、配套 .fsa 文件与验证报告，直接可用于提交。

支持基因：LSU、SSU、tef1、rpb1、rpb2、tub2、act、cal、chs，以及线粒体 marker
（mtLSU、mtSSU、cox1、cob、nad1/nad2/nad4/nad5、atp6、rps3）。

## 工作流程

1. **导入 & BLAST** — 拖入 / 浏览 / 粘贴 FASTA，命中结果按排名返回。
2. **参考选择** — 在命中表中选定参考记录（默认预选推荐行）。
3. **注释审核** — 迁移得到的 feature 表格可编辑，修改后即时重验；比对视图辅助
   人工核查，红灯项需人工确认。
4. **验证导出** — 每条序列输出一份五列 feature table，并汇总为多记录 feature
   table（界面导出仅 .tbl；.fsa 配对文件与验证报告 CSV 仅命令行提供）。

窗口顶部的水平步骤条可点击跳转到任意已解锁步骤；项目可保存（JSON）并随时续作。
BLAST 与解析在后台线程执行，界面保持响应。

## 功能特性

- **参考注释迁移** — 参考 GenBank 的注释按比对坐标迁移到查询序列，自动生成
  BankIt 门户格式的五列 feature table（只含 gene/CDS 等 feature，organism 在
  BankIt 门户表单录入）。
- **多基因预设** — 基因类型自动从 BLAST 命中标题 / 参考注释识别，无法识别时
  回退通用 Generic 预设。
- **三种指定参考的方式** — 在线 BLAST、直接指定 accession（跳过 BLAST）、
  本地参考 GenBank 离线模式（仅 CLI）。
- **审核编辑即时重验** — 红灯项需人工确认方可导出。

## 安装

需要 Python ≥ 3.10（CI 在 3.12 上测试，覆盖 Windows / macOS / Linux）。

```bash
git clone https://github.com/yananzh/MycoFACT.git
cd MycoFACT
pip install -r requirements.txt
```

免安装的打包版：`Build` workflow 用 PyInstaller（--onedir）在每次 push 到 `main`
与 `v*` tag 时产出三平台包（Windows zip / macOS .app zip / Linux tar.gz），打 tag
（如 `v0.1.0`）会自动附到 GitHub Releases。

> [!WARNING]
> 当前二进制未签名。Windows 首次运行 SmartScreen 会告警（点"仍要运行"），
> macOS 首启需右键 → 打开。

应用图标（蘑菇 + DNA 螺旋，见 [assets/logos](assets/logos)）三平台统一：Windows
EXE 内嵌多尺寸 `.ico`，macOS .app 使用 `.icns`，各平台窗口/任务栏图标用多尺寸
PNG。修改 logo 后用 `python scripts/build_icons.py` 重新生成（依赖 PyQt6 +
Pillow）。

## 使用

### 图形界面

```bash
python main.py
```

打开上文所述的四步向导。首页点 **Example** 可载入内置示例（`demo/example.fasta`）
先行浏览向导；注释本身需要在线 BLAST 或参考 accession（完整离线流程仅命令行支持，
经 `--ref-gb`）。

### 命令行

```bash
# 一键演示：生成参考 GB + 两条查询（正链带插入 / 反向互补），离线跑通端到端
python scripts/make_demo.py
python main.py run --input demo/tef1_queries.fasta --out demo_out --gene-type tef1 \
    --ref-gb demo/reference.gb

# 离线模式：用本地参考 GenBank 文件（测试 / 无网络环境）
python main.py run --input seqs.fasta --out outdir --gene-type tef1 --ref-gb reference.gb
# 省略 --gene-type 时自动从命中标题 / 参考注释判定；无法识别则用 Generic 通用预设

# 在线模式：BLAST 选参考
python main.py run --input seqs.fasta --out outdir --gene-type tef1 --email you@example.org

# 直接指定参考 accession（跳过 BLAST）
python main.py run --input seqs.fasta --out outdir --gene-type tef1 --accession LCxxxxxx.1

# 查看全部基因预设
python main.py presets
```

> [!NOTE]
> 在线 BLAST 需要联网，NCBI 要求提供联系邮箱（`--email`）。可选参数：
> `--api-key`（更高的 Entrez 限速）、`--organism`（Entrez 过滤，如 `Fusarium`）、
> `--db`（BLAST 数据库，默认 `core_nt`）、`--identity`（命中一致性阈值，默认 97）、
> `--no-auto-partial`（关闭对触及序列末端的 feature 自动 partial）。

### 输出文件

| 文件 | 说明 |
| ---- | ---- |
| `<SeqID>.tbl` + `<SeqID>.fsa` | 每条序列的 feature table 与配对 FASTA |
| `all_features.tbl` | 所有已注释序列的 `>Feature` 记录合并为一个多记录文件，可整文件上传 BankIt（无任何序列产出 feature 时不生成） |
| `validation_report.csv` | 总体验证报告 |

## 项目结构

```text
MycoFACT/
├── main.py                # 入口：python main.py → GUI；run / presets → CLI
├── fungal_annot/
│   ├── core/              # 核心层：BLAST、参考获取、注释迁移、验证、.tbl 写出
│   ├── services/          # 流水线、后台线程、项目 JSON 存取
│   ├── ui/                # PyQt6 四页向导界面
│   ├── resources/         # 样式表、图标、基因预设
│   └── tests/             # pytest 测试
├── scripts/
│   ├── make_demo.py       # 一键生成演示数据
│   └── build_icons.py     # 从 SVG logo 重新生成图标
└── demo/                  # 内置示例（查询 FASTA / 参考 GenBank）
```

## 当前状态

- **核心层 + CLI + 测试**（M0–M2）与 **PyQt6 向导界面**（M3–M5：后台线程队列、
  项目 JSON 存取、审核编辑即时重验）均已完成。（此前提到的 table2asn 应用内预检
  入口已移除：organism 等来源信息改在 BankIt 门户表单录入，预检不适用。）
- **待办**：在线 BLAST 对 NCBI 实网验证（建议用实验室真实序列做黄金集）、
  table2asn CI 门禁（需 BankIt 模板 .sbt）、Windows 代码签名与 macOS 公证。

运行测试：

```bash
pytest
```
