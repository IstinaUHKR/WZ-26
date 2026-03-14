# 三 Agent 对抗架构设计

## 概述

本工具链采用 Writer-Critic-Fact-Checker 三角对抗架构。每个 Agent 运行在**独立的上下文窗口**中，通过 `.claude/agents/` 定义文件配置，使用文件系统传递数据。

## 整体架构图

```
┌─── Orchestrator（主会话）─────────────────────────────────────┐
│                                                               │
│  【检索层】                                                    │
│  search_academic.py → 候选元数据池（无偏宽检索）                │
│         +                                                     │
│  按子问题并行 Agent → 全网检索 + 语义预筛 → acquired.json       │
│         +                                                     │
│  pending_manual 二次抓取（自动）                               │
│                                                               │
│  【写作-对抗层】                                               │
│  ┌────────────────────────────────────────────────────────┐   │
│  │           对抗循环（最多 3 轮）                          │   │
│  │                                                        │   │
│  │  ┌──────────────┐  draft_round_N.md  ┌─────────────┐  │   │
│  │  │ Writer Agent  │──────────────────►│ Critic Agent│  │   │
│  │  │ (sonnet)      │                   │ (opus)      │  │   │
│  │  │ 独立上下文     │◄─────────────┐   │ 独立上下文   │  │   │
│  │  └──────────────┘  revision     │   └──────┬──────┘  │   │
│  │                                 │          │          │   │
│  │                    factcheck_N  │  critic_N.json      │   │
│  │                                 │          │          │   │
│  │              ┌──────────────────┴──────────▼──────┐   │   │
│  │              │      Fact-Checker Agent             │   │   │
│  │              │      (inherit model，独立上下文)     │   │   │
│  │              └────────────────────────────────────┘   │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                               │
│  workspace/adversarial_manifest.json ← 循环状态跟踪            │
└───────────────────────────────────────────────────────────────┘
```

## 隔离机制

每个 Agent 通过 Claude Code 的 **Agent tool** 启动为独立子进程：

| Agent | 定义文件 | Model | 工具权限 |
|-------|---------|-------|---------|
| 检索预筛 Agent | （通用 Agent） | sonnet | tavily_search, tavily_extract, WebFetch |
| Writer | `.claude/agents/writer-agent.md` | sonnet | Read, Grep, Glob, Bash, Write |
| Critic | `.claude/agents/critic-agent.md` | opus | Read, Grep, Glob, Write（无 Bash） |
| Fact-Checker | `.claude/agents/fact-checker-agent.md` | inherit | Read, Grep, Glob, Bash, Write |

关键隔离特性：
- **独立上下文窗口**：Critic 无法看到 Writer 的推理过程，只能看到 Writer 输出的报告文件
- **不同模型**：Writer(sonnet) 和 Critic(opus) 使用不同模型权重，天然产生视角差异
- **受限工具权限**：Critic 无 Bash 权限，只能阅读文件和输出审查 JSON

## 文件传递协议

Agent 间不共享内存，通过 `workspace/` 下的文件通信：

```
workspace/
  search_<n>.json            ← 阶段 2 学术检索原始结果
  acquired.json              ← 阶段 3-4 预筛通过的文献（附证据原句）
  pending_manual.json        ← 阶段 3 摘要不确定的文献
  web_cache/                 ← 网页快照
  draft_round_1.md           ← Writer 初稿
  draft_round_2.md           ← Writer 修订稿（如需）
  draft_round_3.md           ← Writer 第三稿（如需）
  critic_round_1.json        ← Critic 审查反馈（结构化 JSON）
  critic_round_2.json
  factcheck_round_1.json     ← Fact-Checker 验证结果
  factcheck_round_2.json
  adversarial_manifest.json  ← Orchestrator 循环状态跟踪
```

## 各 Agent 职责

### 检索预筛 Agent（按子问题并行）
- **输入：** 子问题 + 关键词 + 阶段2元数据池
- **执行：** Tavily 多轮检索 + tavily_extract 抓全文 + 语义判断
- **输出：** 符合列表（附原句）+ 不确定列表
- **并行粒度：** 每个子问题一个 Agent，避免预筛重复

### Writer（sonnet）
- **输入：** `workspace/acquired.json` + 本地文献/网页快照
- **输出：** 带锚点的研究报告 → `workspace/draft_round_N.md`
- **约束：** 只能引用已获取的文献，不能凭记忆添加来源
- **模式：** 支持 initial（初稿）和 revision（修订）两种模式

### Critic（opus）
- **输入：** Writer 的报告文件（只能看到输出，看不到推理过程）
- **输出：** 结构化 JSON 反馈 → `workspace/critic_round_N.json`
- **审查维度：**
  1. `unsupported` — 声明无对应来源支撑
  2. `exaggerated` — 原文表述被夸大
  3. `misquoted` — 引用内容与原文不符
  4. `fabricated` — 来源本身不存在或虚构
- **verdict：** accept / revise / reject_and_research（核心文献全部坍塌才触发）
- **限制：** 无 Bash 权限，不能运行脚本

### Fact-Checker（inherit）
- **输入：** Critic 标记的 high severity 问题
- **工具：** `read_local_pdf.py`（按页码提取、关键词搜索）
- **输出：** 逐条裁决 → `workspace/factcheck_round_N.json`
- **裁决类型：** CONFIRMED / OVERTURNED / PARTIALLY

## 对抗规则

1. **最多 3 轮：** 防止无限循环消耗 token
2. **严重度分级：** Fact-Checker 只验证 high severity 问题
3. **回退触发条件：** `reject_and_research` 仅在核心文献全部不可靠、基础论据已坍塌时触发；个别文献有问题走 `revise` 路径，不回退
4. **降级机制：** 3 轮后仍未 accept，强制进入终稿，未解决问题标记 UNVERIFIED

## 设计理由

借鉴 gpt-researcher 的 Reviewer↔Revisor 循环，但做了三项根本性改进：

1. **检索与判断解耦**
   - 脚本（search_academic.py）负责无偏宽检索，不做内容判断
   - 预筛 Agent 负责语义判断，在下载前完成过滤
   - 避免"搜索-判断"合并时的确认偏误

2. **真正的上下文隔离**
   - 旧方案：Critic 能看到 Writer 的全部推理过程，导致结构性一致性偏误
   - 新方案：每个 Agent 是独立子进程，只能通过文件看到其他 Agent 的输出

3. **不同模型权重 + Fact-Checker 兜底**
   - Writer(sonnet) + Critic(opus)：不同模型天然产生视角差异
   - Fact-Checker 强制回到原文逐句比对，是唯一能检测"精确幻觉"的手段
