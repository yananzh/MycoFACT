<div align="right">

[English](./README.md) | 简体中文

</div>

# MycoFACT — 真菌多基因鉴定序列 Feature Table 自动生成工具

[![CI](https://github.com/yananzh/MycoFACT/actions/workflows/ci.yml/badge.svg)](https://github.com/yananzh/MycoFACT/actions/workflows/ci.yml)
[![Build](https://github.com/yananzh/MycoFACT/actions/workflows/build.yml/badge.svg)](https://github.com/yananzh/MycoFACT/actions/workflows/build.yml)

**MycoFACT**（**F**ungal **F**eature **A**nnotation & **C**omparison **T**ool，包名
`fungal_annot`）通过"参考注释迁移"为真菌 marker 基因序列（LSU/SSU/tef1/rpb1/rpb2/tub2/act/cal/chs
及线粒体 marker）自动生成 NCBI 五列 feature table（.tbl），并配套输出 BankIt 提交所需的
.fsa 文件与验证报告。

## ✨ 功能特性

- **参考注释迁移**：BLAST 选定参考序列后，将参考 GenBank 的注释按比对坐标迁移到查询序列，
  自动生成 BankIt 门户格式的五列 feature table（.tbl，只含 gene/CDS 等 feature，
  organism 在 BankIt 门户表单录入）。
- **多基因预设**：内置 LSU、SSU、tef1、rpb1、rpb2、tub2、act、cal、chs 及线粒体 marker 等基因预设；
  可自动从命中标题 / 参考注释识别基因类型，无法识别时回退通用 Generic 预设。
- **三种指定参考的方式**：在线 BLAST 选参考（需联网，NCBI 要求提供 email）、本地参考
  GenBank 离线模式、直接指定 accession 跳过 BLAST。
- **四步向导 GUI**：导入 & BLAST → 参考选择 → 注释审核 → 验证导出；水平步骤条置于窗口
  顶部，点击已解锁的步骤即可跳转。
- **审核编辑即时重验**：feature 表格可编辑，修改后即时重验；比对视图辅助人工核查，
  红灯项需人工确认方可导出。
- **项目保存 / 恢复**：菜单栏 File 可保存 / 打开项目（JSON），随时关闭续作。
- **后台线程队列**：BLAST 与解析在后台线程执行，界面保持响应。

## 📌 当前状态

- **M0–M2 已完成**：core/ 核心层全部模块 + CLI + 测试（计划 §8 里程碑 M0–M2）。
- **M3–M5 已完成**：PyQt6 四页向导 UI、后台线程队列、项目 JSON 存取、审核编辑即时重验、
  table2asn 应用内预检入口。
- **待办**：在线 BLAST 对 NCBI 实网验证（建议按计划 M2 用实验室真实序列做黄金集）、
  table2asn CI 门禁（需 BankIt 模板 .sbt）、Windows 代码签名与 macOS 公证。

## 📦 安装

需要 Python ≥ 3.10（CI 在 3.12 上测试，覆盖 Windows / macOS / Linux）。

```bash
git clone https://github.com/yananzh/MycoFACT.git
cd MycoFACT
pip install -r requirements.txt
```

免安装的打包版：`Build` workflow 用 PyInstaller（--onedir）在每次 push 与
`v*` tag 时产出三平台包（Windows zip / macOS .app zip / Linux tar.gz），
打 tag（如 `v0.1.0`）会自动附到 GitHub Releases。当前未签名：Windows
首次运行 SmartScreen 会告警（点"仍要运行"），macOS 首启需右键 → 打开。

应用图标（蘑菇 + DNA 螺旋，见 [assets/logos](assets/logos)）三平台统一：
Windows EXE 内嵌多尺寸 `.ico`，macOS .app 使用 `.icns`，各平台窗口/任务栏
图标用多尺寸 PNG。修改 logo 后用 `python scripts/build_icons.py` 重新生成
（依赖 PyQt6 + Pillow）。

## 🖥 图形界面

```bash
python main.py        # 启动 GUI
```

四步流程：序列导入并跑 BLAST（拖入 / 浏览 / 粘贴 FASTA 或裸序列，或点 **Example** 载入
内置示例 demo/example.fasta；队列排空后自动进入下一步）→ 参考选择（命中表行内单选，
默认推荐行）→ 注释审核（可编辑 feature 表格、即时重验、比对视图、红灯人工
确认）→ 验证汇总与导出（.tbl + .fsa + 汇总表 + 报告）。

参考统一在线解析（命中 accession / 直接下载）；本地参考 GenBank 离线模式仅 CLI
`--ref-gb` 保留。

## ⌨️ 快速上手（CLI）

```bash
# 一键演示：生成参考 GB + 两条查询（正链带插入 / 反向互补），离线跑通端到端
python scripts/make_demo.py
python main.py run --input demo/tef1_queries.fasta --out demo_out --gene-type tef1 \
    --ref-gb demo/reference.gb

# 离线模式：用本地参考 GenBank 文件（测试 / 无网络环境）
python main.py run --input seqs.fasta --out outdir --gene-type tef1 --ref-gb reference.gb
# 省略 --gene-type 时自动从命中标题 / 参考注释判定；无法识别则用 Generic 通用预设

# 在线模式：BLAST 选参考（需要网络；email 为 NCBI 要求）
python main.py run --input seqs.fasta --out outdir --gene-type tef1 --email you@example.org

# 直接指定参考 accession（跳过 BLAST）
python main.py run --input seqs.fasta --out outdir --gene-type tef1 --accession LCxxxxxx.1

# 查看全部基因预设
python main.py presets
```

## 📤 输出

- 每条序列一个 `<SeqID>.tbl`（feature table）+ 配对 `<SeqID>.fsa`
- `all_features.tbl`——汇总 feature table：所有已注释序列的 `>Feature` 记录合并
  为一个多记录文件，可整文件上传 BankIt（无任何序列产出 feature 时不生成）
- 总体验证报告 `validation_report.csv`

## ✅ 运行测试

```bash
pytest
```

## 📁 项目结构

```text
MycoFACT/
├── main.py                # 入口：python main.py → GUI；run / presets → CLI
├── fungal_annot/
│   ├── core/              # 核心层：BLAST、参考获取、注释迁移、验证、.tbl 写出
│   ├── services/          # 流水线、后台线程、项目 JSON 存取
│   ├── ui/                # PyQt6 四页向导界面
│   ├── resources/         # 样式表、图标
│   └── tests/             # pytest 测试
├── scripts/make_demo.py   # 一键生成演示数据
└── demo/                  # 内置示例（查询 FASTA / 参考 GenBank）
```

## 📄 设计文档

详细设计见《真菌多基因序列FeatureTable工具-开发计划.md》（内部设计文档，暂不随仓库公开）。
