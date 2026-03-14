# 工作计划：深度检索工具链（WZ-26）

**最后更新：** 2026-03-14（v3）
**状态：** 已规划，待实施

---

## 问题背景

AI 生成的研究报告存在两个核心问题：
1. **检索不充分** — 遗漏关键文献，结论基于片面证据
2. **理解不准确** — 虚构、夸大、或错误解读文献内容

目标：构建多 Agent 对抗式工具链，同时解决广度（检索）和准度（理解）问题。

---

## 已知环境

| 资产 | 位置 | 状态 |
|------|------|------|
| Zotero 数据库 | `D:\PTU\LibUHKR\zotero.sqlite` | ✅ 可用（~202项，171个PDF） |
| Zotero MCP 插件 | cookjohn/zotero-mcp，端口 23120 | ⏳ 需在 Zotero UI 中启用 |
| Tavily MCP 工具 | 当前 Claude 会话内置 | ✅ 可用 |
| Python 3.12.7 | Anaconda，pdfplumber/requests 已装 | ✅ 可用 |
| gpt-researcher | `D:\PTU\gptresearcher\gpt-researcher\` | 📋 参考架构（multi_agents/ 目录） |
| Claude Code 技能目录 | `C:\Users\lenovo\.agents\skills\` | ✅ |

### 参考架构：gpt-researcher multi_agents/

```
ChiefEditor (LangGraph 编排)
  → Researcher (检索)
  → Editor (规划大纲)
  → Reviewer (审查) ←→ Revisor (修订)  ← 对抗循环
  → Writer (终稿)
  → Publisher (导出)
```

**借鉴点：** Reviewer↔Revisor 对抗循环、并行子话题研究、LangGraph 状态机
**不用：** 其 LLM 配置、简单 URL 引用（我们用结构化锚点）

---

## 核心架构：三 Agent 对抗

```
┌─────────────────────────────────────────────────────┐
│                      /WZ-26                          │
│                  (SKILL.md 入口)                      │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Phase A: 检索与收集                                   │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐       │
│  │ 学术检索  │    │ 全网检索  │    │ 本地 PDF │       │
│  │ S2+OA+UP │    │  Tavily   │    │ Zotero   │       │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘       │
│       └───────────┬───┘───────────────┘              │
│                   ▼                                   │
│         workspace/papers/  (项目本地文件夹)            │
│                   │                                   │
│  Phase B: 用户补充暂停点                               │
│                   │                                   │
│  Phase C: 三 Agent 对抗式写作                          │
│  ┌─────────────────────────────────────────┐         │
│  │  ┌─────────┐   反馈   ┌──────────┐     │         │
│  │  │ Writer  │◄────────│  Critic  │     │  最多    │
│  │  │ (写报告) │────────►│ (挑刺)   │     │  3 轮    │
│  │  └─────────┘  初稿/   └────┬─────┘     │         │
│  │       ▲       修订稿        │            │         │
│  │       │              逐句比对原文         │         │
│  │       │                    │            │         │
│  │       │         ┌──────────▼─────┐     │         │
│  │       └─────────│ Fact-Checker   │     │         │
│  │        验证结果  │ (回到PDF原文)   │     │         │
│  │                 └────────────────┘     │         │
│  └─────────────────────────────────────────┘         │
│                   │                                   │
│         Critic 打掉所有文献？                          │
│          ├── 是 → 触发补充检索 → 回到 Phase A          │
│          └── 否 → Phase D                             │
│                   │                                   │
│  Phase D: 终稿 + 核查                                 │
│  verify_citations.py → 清理 workspace/papers/         │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### 三 Agent 职责

| Agent | 职责 | 工作方式 |
|-------|------|----------|
| **Writer** | 基于本地文献撰写报告，每条声明附锚点 | 只能引用 workspace/papers/ 中的文献 |
| **Critic** | 逐条审查：来源是否支持结论？有无过度推断/夸大？ | 输出结构化 JSON 反馈（哪条声明、什么问题、严重程度） |
| **Fact-Checker** | 回到 PDF 原文逐句比对，验证引用准确性 | 用 read_local_pdf.py 读取具体页码段落 |

### 对抗规则

- Writer-Critic 最多 **3 轮** 迭代，防止无限循环
- Critic 反馈格式：`{"claim": "...", "issue": "unsupported|exaggerated|misquoted|fabricated", "severity": "high|medium|low", "evidence": "..."}`
- 若某声明所有支撑文献被 Critic 打掉 → 降级为 `UNVERIFIED`，触发补充检索
- 补充检索仍无结果 → 声明移入"当前证据不支持"附录，不删除

---

## 实施步骤

### Phase 1：基础配置

**Step 1.1** - 启用 Zotero MCP 服务器（**用户手动操作**）
> Zotero → 编辑 → 首选项 → Zotero MCP Plugin → 勾选 Enable Server（端口 23120）

**Step 1.2** - 修改 `C:\Users\lenovo\.claude\settings.json`
> 添加 `mcpServers` 块，接入 Zotero 本地 HTTP MCP

**Step 1.3** - 确认项目 `.claude/settings.json` 权限配置

---

### Phase 2：Python 脚本编写

**Step 2.1** - `src/scripts/search_academic.py`
- 查询 Semantic Scholar + OpenAlex（均免费，无需 API Key）
- 按 DOI 去重，按引用量排序
- **自动获取 OA 全文链接**（Unpaywall / OpenAlex `open_access.oa_url` / Semantic Scholar `openAccessPdf`）
- 输出 JSON：title, authors, year, doi, abstract, citation_count, venue, open_access_url, **pdf_status**

**Step 2.2** - `src/scripts/download_papers.py`（改：下载到项目本地文件夹）
- 输入：search_academic.py 的 JSON 结果
- OA 可用 → 下载 PDF 到 `workspace/papers/<doi_hash>.pdf`，同时写 `workspace/papers/metadata.json`
- 付费墙 → 仅记录元数据，标记 `paywall`
- 输出：
  - `workspace/acquired.json` — 已下载清单
  - `workspace/pending_manual.json` — 待手动下载清单（DOI、标题、期刊）

**Step 2.3** - `src/scripts/search_web.py`（新增：全网检索）
- 封装 Tavily MCP 调用（tavily_search / tavily_extract）
- 支持多轮迭代检索（最多 5 轮，每轮基于上一轮结果生成新查询）
- 对网页来源：提取关键段落 + 保存快照到 `workspace/web_cache/`
- 输出追加到 `workspace/acquired.json`

**Step 2.4** - `src/scripts/verify_citations.py`
- 解析报告中所有 `[Z:]`、`[A:]`、`[W:]`、`[L:]` 锚点
- Zotero：sqlite3 直接查本地数据库（离线可用）
- DOI：Semantic Scholar API 确认
- URL：HTTP HEAD 请求
- **检查引用文献是否有本地全文（区分"有全文"vs"仅摘要"）**
- **引用粒度验证：锚点中的页码/段落是否对应原文内容**
- 输出 `verification_report.md`

**Step 2.5** - `src/scripts/read_local_pdf.py`
- pdfplumber 扫描指定文件夹 PDF，关键词相关性打分
- 支持按页码/段落提取特定内容（供 Fact-Checker 使用）
- 返回 Top-N 相关文件及摘录

**Step 2.6** - `src/scripts/cleanup_workspace.py`（新增）
- 清空 `workspace/papers/` 和 `workspace/web_cache/`
- 在报告终稿完成后自动调用

---

### Phase 3：技能定义（Claude Code Skill）

**Step 3.1** - `skill/SKILL.md`
触发词：deep research、研究报告、文献综述、查文献

**工作流（含多 Agent 对抗 + 人机交互）：**

```
阶段 1: 范围定义
  └─ 拆解子问题，确定检索关键词（中英文）

阶段 2: 用户指定 Zotero 目标库
  └─ Zotero MCP 验证库名 → 不存在则重新输入 → 循环直到匹配

阶段 3: Zotero 预扫
  └─ 检索现有库中相关文献 → 复制 PDF 到 workspace/papers/

阶段 4: 学术数据库检索
  └─ search_academic.py → Semantic Scholar + OpenAlex
  └─ download_papers.py → OA 全文下载到 workspace/papers/

阶段 5: 全网检索
  └─ search_web.py → Tavily 多轮检索（最多 5 轮）
  └─ 网页快照存入 workspace/web_cache/

阶段 6: ⏸️ 用户手动补充（暂停点）
  └─ 展示 pending_manual.json（付费墙文献清单）
  └─ 用户下载到 Zotero 指定库后通知继续
  └─ 重新扫描库，将新增 PDF 复制到 workspace/papers/

阶段 7: Writer Agent 撰写初稿
  └─ 仅基于 workspace/ 中的本地文献
  └─ 每条声明强制附带锚点（精确到页码/段落）

阶段 8: Critic Agent 审查（对抗循环，最多 3 轮）
  └─ 逐条检查：来源是否支持结论？有无夸大/虚构？
  └─ 输出结构化 JSON 反馈
  └─ Fact-Checker 回到 PDF 原文逐句比对
  └─ Writer 根据反馈修订
  └─ 若所有文献被打掉 → 触发补充检索（回到阶段 4）

阶段 9: 终稿生成
  └─ 声明-证据表 + 置信等级
  └─ verify_citations.py 自动核查

阶段 10: 清理
  └─ cleanup_workspace.py 清空临时文件夹
  └─ 报告输出到 reports/
```

**Step 3.2** - `skill/references/` 目录（参考 gpt-researcher 的 skill 结构）
- `architecture.md` — 三 Agent 架构说明
- `prompts.md` — Writer / Critic / Fact-Checker 的 prompt 模板
- `workflow.md` — 详细阶段说明

**Step 3.3** - 软链接到 Claude Code 技能目录
```bash
ln -s /d/PTU/WZ-26/project/skill /c/Users/lenovo/.agents/skills/WZ-26
```

---

### Phase 4：架构决策记录

**Step 4.1** - `.claude/decisions/001-zotero-mcp.md`
> 为何选 cookjohn 本地插件而非 zotero.org API

**Step 4.2** - `.claude/decisions/002-search-strategy.md`
> 为何用 Claude+Tavily 自身检索而非 gpt-researcher 的 LLM 调用

**Step 4.3** - `.claude/decisions/003-citation-anchors.md`
> 锚点格式设计与防幻觉机制

**Step 4.4** - `.claude/decisions/004-multi-agent-adversarial.md`（新增）
> 三 Agent 对抗架构设计：为何需要 Writer/Critic/Fact-Checker 分离

---

### Phase 5：测试验证

1. 重启 Claude Code（Zotero 运行中）→ 确认 `mcp__zotero__*` 工具出现
2. `mcp__zotero__search_library { "q": "nuclear" }` → 返回库中条目
3. `python src/scripts/search_academic.py --query "accelerator driven subcritical" --limit 5`
4. `python src/scripts/download_papers.py --input results.json` → 验证下载到 workspace/papers/
5. `python src/scripts/search_web.py --query "ADS reactor safety" --rounds 2` → 验证全网检索
6. 用真实问题触发 `/WZ-26`，走完全流程（含对抗循环 + 暂停点）
7. `python src/scripts/verify_citations.py --report reports/xxx.md`
8. 确认 workspace/ 已自动清空

---

## 置信等级规则

| 级别 | 条件 |
|------|------|
| **High** | ≥2 独立同行评审来源 + 至少 1 篇有本地全文 PDF + Fact-Checker 验证通过 |
| **Medium** | 1 篇同行评审 OR ≥2 可信网络来源（含仅摘要的文献）|
| **Low** | 单一非同行评审来源 |
| **UNVERIFIED** | 无来源 OR Critic 打掉所有支撑 → 不得出现在正文，列入"待核查"附录 |

---

## 工作流暂停点说明

在阶段 6（用户手动补充），工具链会：
1. 输出 `workspace/pending_manual.json`，列出所有付费墙文献的 DOI、标题、期刊
2. 向用户展示清单，提示"请下载以下文献到 Zotero 文献库 `<库名>`"
3. **暂停等待用户通知**（用户说"已下载完成"后继续）
4. 重新扫描指定库，将新增 PDF 复制到 workspace/papers/
5. 更新文献清单后进入 Agent 对抗阶段

---

## Critic 反馈格式

```json
{
  "round": 1,
  "total_claims": 25,
  "issues": [
    {
      "claim_id": 3,
      "claim_text": "ADS 反应堆可在亚临界状态下安全运行",
      "issue": "exaggerated",
      "severity": "high",
      "detail": "原文 Smith 2023 p.7 仅说'理论上可行'，未说'可安全运行'",
      "source_ref": "[A: doi:10.xxx | Smith 2023 | p.7]",
      "suggestion": "改为'理论上具备亚临界运行的可行性'"
    }
  ],
  "verdict": "revise"  // "accept" | "revise" | "reject_and_research"
}
```

当 `verdict = "reject_and_research"` → 回到 Phase A 补充检索。

---

## 文件存储策略

| 路径 | 用途 | 生命周期 |
|------|------|----------|
| `workspace/papers/` | 下载的 OA PDF + Zotero 复制的 PDF | 报告完成后清空 |
| `workspace/web_cache/` | 网页快照 | 报告完成后清空 |
| `workspace/acquired.json` | 已获取文献清单 | 报告完成后清空 |
| `workspace/pending_manual.json` | 待手动下载清单 | 报告完成后清空 |
| `reports/` | 最终报告 | 永久保留 |

---

## 已知限制

- Zotero 必须运行时 `mcp__zotero__*` 才可用（verify_citations.py 离线可用）
- Semantic Scholar / OpenAlex 对 CNKI/万方覆盖有限，中文论文用 Tavily 补充
- 付费墙论文：OA 版本不可用时仅记录元数据，全文依赖用户手动下载
- OA 覆盖率约 30-40%，其余需用户通过机构渠道补充
- Writer-Critic 对抗最多 3 轮，避免无限循环消耗 token
- 三 Agent 通过 `.claude/agents/` 定义为独立子进程（Writer/sonnet、Critic/opus、Fact-Checker/inherit），上下文隔离
