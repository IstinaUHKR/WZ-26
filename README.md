# WZ-26 — 多 Agent 对抗式深度检索工具链

基于 Claude Code 的学术研究报告生成系统。三个独立 Agent（Writer / Critic / Fact-Checker）通过对抗循环协作，解决 AI 生成报告的两个核心问题：**检索不充分**和**理解不准确**。

## 核心特性

- **对抗式写作**：Writer 撰写初稿，Critic 逐条挑刺，Fact-Checker 回到 PDF 原文逐句比对，最多 3 轮迭代
- **强制引用锚点**：每条声明必须附带可核查来源（精确到页码/段落），宁可说"证据不足"也不虚构
- **多源检索**：学术数据库（Semantic Scholar + OpenAlex）+ 全网（Tavily）+ 本地 Zotero 文献库
- **自动核查**：`verify_citations.py` 解析所有锚点，验证 DOI / URL / 本地文件有效性
- **Claude Code Skill**：通过 `/WZ-26` 一键触发完整 8 阶段工作流

## 架构

```
/WZ-26 (Orchestrator)
│
├── 阶段 1-4: 检索与收集
│   ├── Zotero 本地文献库 (MCP)
│   ├── search_academic.py  → Semantic Scholar + OpenAlex
│   ├── download_papers.py  → OA 全文下载
│   └── search_web.py       → Tavily 多轮检索
│
├── 阶段 5-6: 三 Agent 对抗循环 (最多 3 轮)
│   ├── Writer  (sonnet) — 基于本地文献撰写，强制锚点
│   ├── Critic  (opus)   — 逐条审查，输出结构化 JSON 反馈
│   └── Fact-Checker     — 回到 PDF 原文逐句比对
│
└── 阶段 7-8: 终稿 + 核查 + 清理
    ├── verify_citations.py → 锚点核查报告
    └── cleanup_workspace.py → 清空临时文件
```

三个 Agent 定义在 `.claude/agents/` 中，通过 Claude Code Agent tool 作为独立子进程运行，**上下文完全隔离**，打破一致性偏误。

## 引用锚点格式

报告中每条声明使用以下格式标注来源：

| 锚点 | 含义 |
|------|------|
| `[Z: ItemKey \| 作者 年份]` | Zotero 本地文献库 |
| `[A: doi:10.xxx \| 作者 年份 \| 期刊 \| p.N]` | 学术论文（精确到页码） |
| `[W: URL \| 标题 \| 日期]` | 网络来源 |
| `[L: workspace/papers/file.pdf \| p.N]` | 本地文件 |

## 置信等级

| 等级 | 条件 |
|------|------|
| **High** | ≥2 独立同行评审来源 + 至少 1 篇有全文 + Fact-Checker 验证通过 |
| **Medium** | 1 篇同行评审 OR ≥2 可信网络来源 |
| **Low** | 单一非同行评审来源 |
| **UNVERIFIED** | 无来源或 Critic 打掉所有支撑 → 列入"待核查"附录 |

## 目录结构

```
project/
├── .claude/
│   ├── agents/          # 三个独立 Agent 定义
│   │   ├── writer-agent.md
│   │   ├── critic-agent.md
│   │   └── fact-checker-agent.md
│   ├── decisions/       # 架构决策记录 (ADR 001-005)
│   └── settings.json    # 工具权限配置
├── src/scripts/
│   ├── search_academic.py    # S2 + OpenAlex 检索
│   ├── download_papers.py    # OA 全文下载
│   ├── search_web.py         # Tavily 多轮检索
│   ├── verify_citations.py   # 引用锚点核查
│   ├── read_local_pdf.py     # PDF 扫描 / 提取 / 搜索
│   └── cleanup_workspace.py  # 清空工作区
├── skill/
│   ├── SKILL.md             # Claude Code Skill 定义 (/WZ-26)
│   └── references/          # 架构说明 / Prompt 模板 / 工作流文档
├── workspace/               # 运行时临时文件（不纳入版本控制）
└── reports/                 # 输出报告（不纳入版本控制）
```

## 依赖

- **Claude Code** — 运行环境
- **Tavily MCP** — 全网检索
- **Python 3.12+** — `requests`, `pdfplumber`（Anaconda 环境）

```bash
pip install -r requirements.txt
```

### 可选：Zotero 集成

如果你有本地 Zotero 文献库，可以安装 [zotero-mcp](https://github.com/cookjohn/zotero-mcp) 插件（端口 23120），并配置 `.mcp.json`。`verify_citations.py` 支持通过 `--zotero-db` 参数核查 `[Z:]` 锚点，但不强制要求。

## 使用

在 Claude Code 中输入研究问题，触发 `/WZ-26` Skill：

```
/WZ-26 加速器驱动次临界系统(ADS)的热工安全分析方法综述
```

工作流将自动执行 8 个阶段，在阶段 4（Pending 文献二次抓取）后自动继续，无需人工干预。

## 配置

克隆到本地后需要：

1. 配置 Tavily MCP（参考 `~/.claude.json`）
2. 将 `skill/` 软链接到 Claude Code Skills 目录

## 已知限制

- Semantic Scholar API 偶尔返回 429（已知限速，自动重试）
- OA 全文覆盖率约 30-40%，付费墙论文需通过机构渠道获取
- Zotero Desktop 必须运行，MCP 工具才可用
- 对抗循环最多 3 轮，防止 token 过度消耗
