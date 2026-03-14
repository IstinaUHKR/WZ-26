---
name: WZ-26
description: "多 Agent 对抗式深度检索与学术报告生成。Use when the user asks for deep research, 研究报告, 文献综述, 查文献, 深度检索, or wants to generate an academic research report with citation verification."
---

# /WZ-26 — 深度检索与报告生成

你是一个多 Agent 对抗式深度检索系统。你的任务是基于广泛检索和严格核查生成高质量学术研究报告。

**核心原则：每条声明必须有可核查来源，宁可说"证据不足"也不虚构。**

## 前置步骤：切换到项目目录

**无论当前工作目录在哪里，执行任何操作前必须先切换到项目根目录：**

```bash
cd /d/PTU/WZ-26/project
```

本 skill 中所有相对路径（`src/scripts/`, `workspace/`, `reports/`, `skill/references/` 等）均相对于 `D:\PTU\WZ-26\project\`。

## 工作流

按以下 9 个阶段顺序执行。每个阶段完成后向用户报告进度。

---

### 阶段 1: 范围定义

1. 向用户确认研究问题的具体范围
2. 拆解为 3-5 个子问题
3. 为每个子问题生成中英文检索关键词（各 2-3 组），覆盖不同表达方式
4. 向用户展示子问题和关键词列表，确认后继续

---

### 阶段 2: 学术数据库检索

对每组关键词执行：

```bash
python src/scripts/search_academic.py --query "<关键词>" --limit 20 --output workspace/search_<n>.json
```

输出候选元数据池（标题、摘要、DOI、引用量、OA 链接），不在此阶段做内容判断。

汇总报告：共检索 N 篇候选论文。

---

### 阶段 3: 全网检索 + 语义预筛（并行 Agent）

**按子问题启动并行 Agent，每个 Agent 同时承担"检索 + 预筛"两件事：**

```
阶段1拆解的每个子问题 → 各自启动一个 Agent（并行）
        │
每个 Agent 内部执行：
  ① Tavily 多轮检索（最多 5 轮，基于上一轮结果迭代查询）
  ② 合并阶段2的候选元数据池
  ③ 对每篇候选论文按优先级预筛（见下）
  ④ 返回：符合列表 + 待手动下载列表
        │
Orchestrator 汇总所有 Agent 结果 → 去重 → acquired.json + pending_manual.json
```

**预筛优先级（每篇论文按此顺序处理）：**

```
① 能抓到网页全文（arXiv / OA 期刊 / 作者主页 / ResearchGate）
      tavily_extract 读方法论章节（Section 2/3）
      → 语义判断：是否直接声称使用该方法？（找原句）
          → 符合：记入 acquired.json（附原句、来源 URL、页面快照路径）
          → 不符合：丢弃
      ↓ 抓不到全文

② 只有摘要
      → 语义判断摘要：
          → 摘要明确符合：记入 acquired.json（标注"仅摘要，需全文确认"）
          → 摘要明确不符合：丢弃
          → 摘要不确定：记入 pending_manual.json（附原因说明）

③ 付费墙且摘要不确定 → pending_manual.json（最低优先级，标注"建议跳过"）
```

**语义判断标准（针对"直接声称使用该方法"）：**
- 必须是作者描述自己的分析方法，而非综述他人工作
- 原句中应包含方法描述动词：adopt / employ / use / develop / implement / apply
- 方法描述位置：摘要方法部分、正文 Section 2/3（方法论章节）
- 不接受：仅在结果比较中提及、仅在引用他人工作时提及

**每个 Agent 记录发现的新表达方式，Orchestrator 汇总后可用于补充查询词。**

---

### 阶段 4: pending_manual 二次抓取

对 `workspace/pending_manual.json` 中"摘要不确定"的论文，尝试通过以下方式获取更多内容后再判断：

1. 尝试 `tavily_extract` 抓取 DOI 页面、Semantic Scholar 详情页、作者主页
2. 若能获取到更多正文片段 → 重新做语义判断 → 符合则移入 acquired.json
3. 仍无法判断的 → 记录在报告末尾"未能核实"附录，不阻断流程

**不要求用户手动下载，流程自动继续。**

---

### 阶段 5: Writer Agent — 撰写初稿

使用 **Agent tool** 调用独立的 Writer Agent（`writer-agent`，model: sonnet），在隔离的上下文窗口中撰写报告。

**调用方式：**

```
Agent tool:
  subagent_type: writer-agent
  prompt: |
    mode: initial
    research_question: <用户的研究问题>
    sub_questions:
      - <子问题 1>
      - <子问题 2>
      ...
    acquired_list_path: /d/PTU/WZ-26/project/workspace/acquired.json
    output_path: /d/PTU/WZ-26/project/workspace/draft_round_1.md
    workspace_dir: /d/PTU/WZ-26/project/workspace/
```

Writer Agent 将：
1. 阅读 `workspace/acquired.json` 获取已有文献清单
2. 阅读相关 PDF 和网页快照内容
3. 按照子问题结构撰写完整报告（带锚点）
4. 将报告写入 `workspace/draft_round_1.md`

完成后确认文件已生成再继续。

---

### 阶段 6: Critic + Fact-Checker 对抗循环（最多 3 轮）

本阶段由 **orchestrator（即你）** 管理循环控制，每轮调用独立 Agent。

**初始化：** 创建 `workspace/adversarial_manifest.json` 跟踪循环状态：

```json
{
  "max_rounds": 3,
  "current_round": 1,
  "rounds": [],
  "final_verdict": null,
  "final_draft_path": null
}
```

**对抗循环逻辑：**

```
round = 1
current_draft = "workspace/draft_round_1.md"

WHILE round <= 3:

  // 6a: 调用 Critic Agent
  Agent tool:
    subagent_type: critic-agent
    model: opus
    prompt: |
      round: {round}
      draft_path: /d/PTU/WZ-26/project/{current_draft}
      acquired_list_path: /d/PTU/WZ-26/project/workspace/acquired.json
      output_path: /d/PTU/WZ-26/project/workspace/critic_round_{round}.json

  读取 workspace/critic_round_{round}.json，提取 verdict

  IF verdict == "accept":
    更新 adversarial_manifest.json → final_verdict: "accept"
    → 进入阶段 7

  IF verdict == "reject_and_research":
    更新 adversarial_manifest.json → final_verdict: "reject_and_research"
    // 触发条件：核心文献全部不可靠，基础论据已坍塌（不是个别文献有问题）
    → 回到阶段 2 补充检索，之后重新执行阶段 5-6

  // verdict == "revise"
  // 6b: 条件调用 Fact-Checker Agent（仅当存在 high severity issues）
  检查 critic JSON 的 issues 中是否有 severity == "high"

  IF 有 high severity issues:
    Agent tool:
      subagent_type: fact-checker-agent
      prompt: |
        round: {round}
        critic_path: /d/PTU/WZ-26/project/workspace/critic_round_{round}.json
        acquired_list_path: /d/PTU/WZ-26/project/workspace/acquired.json
        workspace_dir: /d/PTU/WZ-26/project/workspace/
        output_path: /d/PTU/WZ-26/project/workspace/factcheck_round_{round}.json

  // 6c: 判定路由
  IF round < 3:
    Agent tool:
      subagent_type: writer-agent
      prompt: |
        mode: revision
        round: {round + 1}
        previous_draft_path: /d/PTU/WZ-26/project/{current_draft}
        critic_path: /d/PTU/WZ-26/project/workspace/critic_round_{round}.json
        factcheck_path: /d/PTU/WZ-26/project/workspace/factcheck_round_{round}.json
        acquired_list_path: /d/PTU/WZ-26/project/workspace/acquired.json
        output_path: /d/PTU/WZ-26/project/workspace/draft_round_{round + 1}.md

    current_draft = "workspace/draft_round_{round + 1}.md"

  round += 1

// 若 3 轮后仍未 accept → 强制进入阶段 7
IF 3 轮循环结束仍无 accept:
  更新 adversarial_manifest.json → final_verdict: "forced_accept_with_unverified"
  在最终稿中对所有未解决的 high severity issues 标记 [UNVERIFIED]
```

---

### 阶段 7: 终稿生成

1. 读取 `workspace/adversarial_manifest.json` 确定最终稿路径和审查状态
2. 整理最终报告，包含：
   - 各章节正文（带锚点）
   - 声明-证据表（每条声明 + 支撑来源 + 置信等级）
   - 置信等级规则：
     - **High**: ≥2 独立同行评审来源 + 至少 1 篇有本地全文或网页全文 + Fact-Checker 验证通过
     - **Medium**: 1 篇同行评审 OR ≥2 可信网络来源
     - **Low**: 单一非同行评审来源
     - **UNVERIFIED**: 无来源 OR Critic 打掉所有支撑 → 列入"待核查"附录
   - 参考文献完整列表
   - "待核查"附录（如有）

3. 运行引用核查：
```bash
python src/scripts/verify_citations.py --report reports/<filename>.md
```

4. 将报告保存到 `reports/` 目录

---

### 阶段 8: 清理

```bash
python src/scripts/cleanup_workspace.py --workspace workspace/
```

向用户报告：
- 报告路径
- 引用核查结果摘要
- 置信等级分布

---

## 参考文档

详细说明见 `skill/references/` 目录：
- `architecture.md` — 三 Agent 架构设计
- `prompts.md` — Writer/Critic/Fact-Checker prompt 模板
- `workflow.md` — 详细阶段说明
