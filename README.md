# fungal_annot — 真菌多基因鉴定序列 Feature Table 自动生成工具

通过"参考注释迁移"为真菌 marker 基因序列（LSU/SSU/tef1/rpb1/rpb2/tub2/act/cal 及线粒体
marker）自动生成 NCBI 五列 feature table（.tbl）。设计文档见《真菌多基因序列FeatureTable工具-开发计划.md》。

## 当前状态

- **M0–M2 已完成**：core/ 核心层全部模块 + CLI + 测试（计划 §8 里程碑 M0–M2）。
- **M3–M5 已完成**：PyQt6 四页向导 UI（导入&BLAST / 参考选择 / 注释审核 / 导出）、
  后台线程队列、项目 JSON 存取、审核编辑即时重验、table2asn 应用内预检入口。
- 待办：在线 BLAST 对 NCBI 实网验证（建议按计划 M2 用实验室真实序列做黄金集）、
  table2asn CI 门禁（需 BankIt 模板 .sbt）、PyInstaller 打包（M6）。

## 图形界面

```bash
python main.py        # 启动 GUI
```

四步流程：序列导入并跑 BLAST（拖入 / 浏览 / 粘贴 FASTA 或裸序列；队列排空后自动进入
下一步）→ 参考选择（命中表行内单选 / 直接输入 accession）→ 注释审核（可编辑 feature
表格、即时重验、比对视图、红灯人工确认）→ 验证汇总与导出（.tbl + .fsa + 报告）。
.tbl 为 BankIt 门户格式（只含 gene/CDS 等 feature，organism 在门户表单录入）。
四个步骤以水平步骤条置于窗口顶部，点击已解锁的步骤即可跳转。
参考统一在线解析（命中 accession / 直接下载）；本地参考 GenBank 离线模式仅 CLI
`--ref-gb` 保留。
菜单栏 File 可保存/打开项目（JSON），随时关闭续作。

## 安装

```bash
pip install -r requirements.txt
```

## 快速上手（CLI）

```bash
# 一键演示：生成参考 GB + 两条查询（正链带插入 / 反向互补），离线跑通端到端
python scripts/make_demo.py
python main.py run --input demo/tef1_queries.fasta --out demo_out --gene-type tef1 \
    --ref-gb demo/reference.gb

# 离线模式：用本地参考 GenBank 文件（测试/无网络环境）
python main.py run --input seqs.fasta --out outdir --gene-type tef1 --ref-gb reference.gb
# 省略 --gene-type 时自动从命中标题/参考注释判定；无法识别则用 Generic 通用预设

# 在线模式：BLAST 选参考（需要网络；email 为 NCBI 要求）
python main.py run --input seqs.fasta --out outdir --gene-type tef1 --email you@example.org

# 直接指定参考 accession（跳过 BLAST）
python main.py run --input seqs.fasta --out outdir --gene-type tef1 --accession LCxxxxxx.1

# 查看全部基因预设
python main.py presets
```

输出：每条序列一个 `<SeqID>.tbl` + 配对 `<SeqID>.fsa` + 总体验证报告 `validation_report.csv`。

## 运行测试

```bash
pytest
```
