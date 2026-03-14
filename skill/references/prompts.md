# Agent 调用 Prompt 模板

> **注意：** Writer/Critic/Fact-Checker 的 system prompt 已移入各自的 Agent 定义文件
> （`.claude/agents/writer-agent.md`、`critic-agent.md`、`fact-checker-agent.md`）。
> 本文件只包含 orchestrator 调用各 Agent 时的 invocation prompt 模板。

## 检索预筛 Agent 调用（阶段 3，按子问题并行）

```
你是一个检索预筛 Agent，负责子问题：{sub_question}

research_question: {research_question}
sub_question: {sub_question}
keywords: {keywords_list}
academic_candidates_path: workspace/search_<n>.json   # 阶段2对应该子问题的候选池
output_acquired_path: workspace/prescan_{n}.json      # 符合的文献
output_pending_path: workspace/pending_{n}.json       # 不确定的文献
web_cache_dir: workspace/web_cache/

任务：
1. 使用 tavily_search 对 keywords 进行多轮检索（最多 5 轮，每轮基于上一轮结果迭代）
2. 合并学术候选池中属于本子问题的条目
3. 对每篇候选论文按预筛优先级处理：
   - 先用 tavily_extract 尝试抓取网页全文（arXiv/OA/作者主页）
   - 能读全文 → 找方法论章节原句 → 语义判断 → 符合记入 prescan_{n}.json（附原句）
   - 只有摘要 → 语义判断摘要 → 明确符合记入 prescan_{n}.json，不确定记入 pending_{n}.json
   - 付费墙且不确定 → pending_{n}.json（标注"建议跳过"）
4. 记录本次检索中发现的新表达方式（用于 Orchestrator 补充查询词）

语义判断标准：
- 必须是作者描述自己的分析方法（不接受综述他人工作）
- 原句应含：adopt / employ / use / develop / implement / apply
- 位置：摘要方法部分 或 正文 Section 2/3
- 不接受：仅在结果比较中提及、仅在引用他人时提及

输出格式（prescan_{n}.json）：
[
  {
    "title": "...",
    "authors": "...",
    "year": 2023,
    "doi": "...",
    "source_url": "...",
    "evidence_quote": "原文中的方法声明原句",
    "evidence_location": "abstract|section2|section3",
    "full_text_available": true,
    "confidence": "high|medium"
  }
]
```

## pending_manual 二次抓取（阶段 4）

```
对 workspace/pending_manual.json 中的每篇论文：
1. 用 tavily_extract 尝试抓取：DOI 页面、Semantic Scholar 详情页、作者主页
2. 获取到更多正文片段 → 重新语义判断 → 符合则追加到 acquired.json
3. 仍无法判断 → 保留在 pending_manual.json，最终记入报告"未能核实"附录
全程自动，不等待用户输入。
```

## Writer Agent 调用 — 初始撰写

```
mode: initial
research_question: {research_question}
sub_questions:
{sub_questions_yaml}
acquired_list_path: workspace/acquired.json
output_path: workspace/draft_round_1.md
workspace_dir: workspace/

请基于 acquired.json 中列出的文献撰写完整研究报告。
报告结构：摘要 → 各子问题章节 → 声明-证据表 → 参考文献表。
每条事实性声明必须附带锚点。将报告写入 output_path。
```

## Writer Agent 调用 — 修订模式

```
mode: revision
round: {round_number}
previous_draft_path: workspace/draft_round_{N}.md
critic_path: workspace/critic_round_{N}.json
factcheck_path: workspace/factcheck_round_{N}.json
acquired_list_path: workspace/acquired.json
output_path: workspace/draft_round_{N+1}.md

请阅读上一轮草稿和审查反馈，逐条处理每个 issue 后生成修订稿。
- CONFIRMED 的问题：必须修正
- OVERTURNED 的问题：保留原文
- PARTIALLY 的问题：按建议调整
将修订后的报告写入 output_path。
```

## Critic Agent 调用

```
round: {round_number}
draft_path: workspace/draft_round_{N}.md
acquired_list_path: workspace/acquired.json
output_path: workspace/critic_round_{N}.json

请严格审查 draft_path 中的报告。逐条检查每个事实性声明的来源支撑。
将审查结果以 JSON 格式写入 output_path。
JSON 必须包含 issues 数组和 verdict 字段（accept/revise/reject_and_research）。
reject_and_research 仅在核心文献全部不可靠、基础论据已坍塌时使用。
```

## Fact-Checker Agent 调用

```
round: {round_number}
critic_path: workspace/critic_round_{N}.json
acquired_list_path: workspace/acquired.json
workspace_dir: workspace/
output_path: workspace/factcheck_round_{N}.json

请只处理 critic_path 中 severity == "high" 的问题。
对每个问题，使用 read_local_pdf.py 回到 PDF 原文逐句比对。
将验证结果以 JSON 格式写入 output_path。
每个结果必须包含 verdict 字段（CONFIRMED/OVERTURNED/PARTIALLY）。
```

## Orchestrator 循环控制

Orchestrator（主会话）负责：

1. **并行调度**：按子问题并行启动检索预筛 Agent，汇总去重结果
2. **调用顺序管理**：Writer → Critic → (Fact-Checker) → Writer 修订 → ...
3. **Verdict 路由**：读取 Critic JSON，根据 verdict 决定下一步
   - `revise`：继续当前循环
   - `reject_and_research`：回到阶段 2（仅核心文献全部坍塌时）
   - `accept`：进入终稿
4. **状态跟踪**：维护 `workspace/adversarial_manifest.json`
5. **轮次控制**：最多 3 轮，超限强制进入终稿
6. **文件完整性检查**：每次 Agent 调用后确认输出文件已生成
