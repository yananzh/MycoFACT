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
参考 GenBank 记录的注释会按比对坐标迁移到查询序列上——自动产出可直接提交的五列
feature table（.tbl）。命令行额外产出配套 .fsa 文件与验证报告；界面导出仅 .tbl。

内置常见 marker 的专属预设：5.8S、LSU、SSU、tef1、rpb1、rpb2、tub2、tub1、act、cal、
chs、gapdh、his3、tsr1、mcm7，以及线粒体 marker（mtLSU、mtSSU、cox1、cob、
nad1/nad2/nad4/nad5、atp6、rps3——均需人工确认）。不在列表中的基因同样支持：自动落入
Generic 兜底预设（宽松的 feature 白名单，密码表取自参考记录）。

## 工作流程

> [!IMPORTANT]
> **注释之前，先核查桑格测序的峰图质量。** 用 SnapGene 等峰图查看软件（如 Chromas、
> 4Peaks）打开每条测序的原始 .ab1 文件，检查峰形质量，切除前、后端的低质量序列
> （引物之后的杂峰起始段与测序末端的衰减段），只把干净、高置信度的区域导出为 FASTA
> 再导入本工具。注释是按你提供的碱基逐一迁移的——输入序列不准确，产出的
> feature table 同样不准确。

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
  本地参考 GenBank 离线模式（GUI 与 CLI 均支持）。
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
先行浏览向导。要跳过 BLAST，点 **Use reference**，然后在第 2 步通过
**View match** 填写 accession，或点 **Local GenBank** 加载本地参考，完成离线注释。
本地参考默认应用于所有已导入序列；开始注释前可调整每条序列的参考选择。

通过 **Save / Save As** 保存 JSON 项目，通过 **Open** 恢复。项目包含已导入序列、
尚未导入的文本、参考、结果、确认状态、设置和任务日志。由于比对上下文不序列化，
恢复的注释可查看、导出，重新注释后才可编辑。**Log** 保留任务消息与失败详情；
关闭或替换未保存项目时，可选择保存、丢弃或取消。

编辑后显示 **Awaiting validation**，导出前会完成验证；无法解析的单元格必须先修正。
人工确认绑定采纳结果，编辑、切换参考、重新注释或验证变化后会失效。

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
| `.mycofact-outputs.json` | 内部产物清单；保留在输出目录中，不上传 BankIt |

导出会先整批暂存，再替换上一批产物。重复导出到同一目录时，只更新清单内未被手工
修改的文件，并清理过时产物，包括本次失败序列的旧表。手工修改的文件和无清单的
同名文件会被保留，此时请选择新目录。旧版本生成的输出目录也请改用新的空目录。

没有任何 feature 可迁移的序列（参考记录无匹配白名单的 feature，或全部区段被丢弃）
会报 error，且**不产出 `.tbl`/`.fsa`**：只有 `>Feature` 记录头的空表会被 BankIt 拒收，
因此"没有文件"意味着该序列需要人工处理，而不是"没问题"。

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
