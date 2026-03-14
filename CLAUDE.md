# WZ-26 深度检索工具链

## 项目概述

为学术研究/论文写作构建**多 Agent 对抗式**深度检索工具链。
核心目标：广泛检索 + 准确理解，每条声明必须附带可核查来源锚点。

## 目录结构

```
WZ-26/project/
├── CLAUDE.md               ← 你在这里
├── PLAN.md                 ← 工作计划 v3（三 Agent 对抗架构）
├── TODO.md                 ← 实时进度跟踪（每次对话必读）
├── .claude/
│   ├── settings.json       ← 权限配置（MCP 服务器等）
│   └── decisions/          ← 架构决策记录 (ADR)
│       ├── 001-zotero-mcp.md
│       ├── 002-search-strategy.md
│       ├── 003-citation-anchors.md
│       └── 004-multi-agent-adversarial.md
├── src/
│   └── scripts/
│       ├── search_academic.py     ← Semantic Scholar + OpenAlex + OA 链接
│       ├── download_papers.py     ← OA 全文下载到 workspace/papers/
│       ├── search_web.py          ← Tavily 全网多轮检索
│       ├── verify_citations.py    ← 报告溯源核查（防幻觉核心）
│       ├── read_local_pdf.py      ← 本地 PDF 扫描 + 按页码提取
│       └── cleanup_workspace.py   ← 报告完成后清空 workspace/
├── skill/
│   ├── SKILL.md             ← Claude Code 技能定义（/WZ-26）
│   └── references/          ← 详细文档（architecture, prompts, workflow）
├── workspace/               ← 临时工作区（报告完成后自动清空）
│   ├── papers/              ← 下载的 PDF
│   ├── web_cache/           ← 网页快照
│   ├── acquired.json        ← 已获取文献清单
│   └── pending_manual.json  ← 待手动下载清单
└── reports/                 ← 输出报告（永久保留）
```

## 核心架构：三 Agent 对抗

- **Writer** — 基于本地文献撰写报告，强制锚点
- **Critic** — 逐条审查（夸大？虚构？来源不支持？），输出结构化 JSON 反馈
- **Fact-Checker** — 回到 PDF 原文逐句比对，验证引用准确性
- 最多 3 轮对抗迭代；若文献全被打掉则触发补充检索

## 关键路径（按本机环境修改）

- **Zotero 数据库：** `<YOUR_ZOTERO_DATA_DIR>/zotero.sqlite`
- **Zotero MCP 插件：** cookjohn/zotero-mcp，端口 23120（需在 Zotero UI 中启用）
- **Claude Code 技能目录：** `<YOUR_HOME>/.claude/skills/` 或 `<YOUR_HOME>/.agents/skills/`

## 启动前检查

1. Zotero Desktop 运行中，MCP 服务器已启用（端口 23120）
2. 当前会话 Tavily MCP 工具可用（tavily_search / extract / research）
3. Python 环境已安装依赖：`pip install -r requirements.txt`
4. 项目根目录存在 `.mcp.json`（参考 `.mcp.json.example`）
5. **每次对话开头读 TODO.md**

## 检索策略

使用 Claude 自身（通过 Tavily MCP）作为检索引擎，不依赖外部 LLM API。
检索范围：学术数据库（S2 + OpenAlex）+ 全网（Tavily）+ 本地 Zotero 库。

每条声明强制使用锚点格式：
- `[Z: ItemKey | 作者 年份]` - Zotero 库
- `[A: doi:10.xxx | 作者 年份 | 期刊 | p.N]` - 学术论文（精确到页码）
- `[W: URL | 标题 | 日期]` - 网络来源
- `[L: workspace/papers/file.pdf | p.N]` - 本地文件
