# 工作流详细说明

## 整体流程

```
用户输入研究问题
        │
        ▼
阶段 1: 范围定义（拆解子问题、生成关键词）
        │
        ▼
阶段 2: 学术数据库检索（S2 + OpenAlex，无内容判断）
        │
        ▼
阶段 3: 全网检索 + 语义预筛（按子问题并行 Agent）
        │
        ▼
阶段 4: pending_manual 二次抓取（自动，无需用户介入）
        │
        ▼
阶段 5: Writer 撰写初稿
        │
        ▼
阶段 6: Critic + Fact-Checker 对抗（≤3 轮）
        │    │
        │    ├── accept → 阶段 7
        │    ├── revise → Writer 修订 → 再审
        │    └── reject_and_research（核心文献全部坍塌）→ 回到阶段 2
        │
        ▼
阶段 7: 终稿生成 + verify_citations.py
        │
        ▼
阶段 8: cleanup_workspace.py
```

## 各阶段详细说明

### 阶段 1: 范围定义

- 拆解为 3-5 个子问题
- 为每个子问题生成中英文检索关键词（各 2-3 组），覆盖不同表达方式
- 用户确认后继续

### 阶段 2: 学术数据库检索

调用 `search_academic.py`，查询 Semantic Scholar + OpenAlex + Unpaywall。

- **只收集元数据，不做内容判断**
- 输出：候选元数据池（标题/摘要/DOI/引用量/OA链接）
- 关键文件：`workspace/search_<n>.json`

### 阶段 3: 全网检索 + 语义预筛

**并行粒度：按子问题**，每个子问题启动一个独立 Agent，避免预筛重复。

每个 Agent 内部：
1. Tavily 多轮迭代检索（≤5 轮，基于上一轮结果调整查询）
2. 合并阶段 2 对应子问题的候选元数据
3. 对每篇论文按优先级预筛：

```
① 能抓到网页全文（arXiv / OA 期刊 / 作者主页 / ResearchGate）
      tavily_extract 读方法论章节（Section 2/3）
      语义判断 → 找"作者直接声称使用该方法"的原句
        → 符合：acquired.json（附原句 + URL + 快照路径）
        → 不符合：丢弃

② 只有摘要
      语义判断摘要
        → 明确符合：acquired.json（标注"仅摘要，需全文确认"）
        → 明确不符合：丢弃
        → 不确定：pending_manual.json（附原因）

③ 付费墙且摘要不确定 → pending_manual.json（标注"建议跳过"）
```

语义判断标准：
- 必须是作者描述自己的分析方法，不接受综述他人工作
- 原句应含方法动词：adopt / employ / use / develop / implement / apply
- 方法描述位置：摘要方法部分、正文 Section 2/3
- 不接受：仅在结果比较中提及、仅在引用他人工作时提及

每个 Agent 记录发现的新表达方式，Orchestrator 汇总后可用于补充查询词。

Orchestrator 汇总所有 Agent 结果 → DOI 去重 → `acquired.json` + `pending_manual.json`

关键文件：
- `workspace/acquired.json` — 已确认符合的文献（附证据原句）
- `workspace/pending_manual.json` — 摘要不确定、需二次处理的文献
- `workspace/web_cache/` — 网页快照

### 阶段 4: pending_manual 二次抓取

对 `pending_manual.json` 中的论文自动尝试获取更多内容：

1. `tavily_extract` 抓取 DOI 页面、Semantic Scholar 详情页、作者主页
2. 获取到更多正文片段 → 重新语义判断 → 符合则移入 `acquired.json`
3. 仍无法判断 → 记录在报告末尾"未能核实"附录

**全程自动，不暂停等待用户。**

### 阶段 5-6: 写作与对抗（Agent tool 隔离架构）

使用 `.claude/agents/` 定义的独立 Agent，通过 Agent tool 在隔离的上下文窗口中执行。

**阶段 5: Writer Agent（sonnet）撰写初稿**

- 输入：`workspace/acquired.json` + 本地文献/网页快照
- 输出：`workspace/draft_round_1.md`
- 约束：只能引用 acquired.json 中已有文献，不能凭记忆添加来源

**阶段 6: 对抗循环（Orchestrator 管理，最多 3 轮）**

```
WHILE round <= 3:
  6a: Critic Agent（opus）审查 → critic_round_N.json
      verdict: accept → 阶段 7
      verdict: reject_and_research（核心文献全部坍塌）→ 回到阶段 2
      verdict: revise →
  6b: Fact-Checker（仅 high severity）→ factcheck_round_N.json
  6c: Writer 修订 → draft_round_{N+1}.md
  round += 1

3 轮后仍未 accept → 强制进入阶段 7，未解决问题标 [UNVERIFIED]
```

文件传递协议：Agent 间不共享内存，所有数据通过 `workspace/` 文件传递。
Orchestrator 维护 `workspace/adversarial_manifest.json` 跟踪循环状态。

### 阶段 7-8: 收尾

`verify_citations.py` 最后一道防线：
- 确认所有锚点的来源存在
- 检测无引用的长段落
- 区分"有全文"和"仅摘要"的引用

## 置信等级规则

| 级别 | 条件 |
|------|------|
| High | ≥2 独立同行评审来源 + 至少 1 篇有网页全文或本地全文 + Fact-Checker 通过 |
| Medium | 1 篇同行评审 OR ≥2 可信网络来源 |
| Low | 单一非同行评审来源 |
| UNVERIFIED | 无来源 OR Critic 打掉所有支撑 |

## 错误恢复

- S2/OpenAlex API 失败 → 跳过该源，用另一个源的结果
- tavily_extract 抓取失败 → 降级为摘要判断，记入 pending_manual
- verify_citations.py 发现问题 → 在终稿中标注，不自动删除
