# ADR 005：从 Prompt 角色切换升级为真正隔离的多 Agent 架构

**日期：** 2026-03-14
**状态：** 已确认
**取代：** ADR 004 中"所有 Agent 均为 Claude 自身（prompt 切换）"的部分

## 决策

将 Writer-Critic-Fact-Checker 三个 Agent 从同一上下文窗口中的 prompt 角色切换，升级为通过 `.claude/agents/` 定义的**真正隔离子进程**，每个 Agent 有独立的上下文窗口、受限的工具权限和可配置的模型。

## 背景

ADR 004 确立了三角对抗架构的价值，但也记录了一个关键限制：

> "三个 Agent 实际上是同一个 Claude 实例通过 prompt 切换角色"
> "角色切换依赖 prompt 指令，不是完全独立的系统"

这导致了结构性的一致性偏误——Critic "审查" Writer 时能看到 Writer 的全部推理过程（思考链、被否决的选项、内部犹豫），本质上是"自己审自己"。即使 prompt 要求 Critic 严格审查，同一上下文窗口中的共享认知使得 Critic 倾向于"理解" Writer 的推理而非独立评判输出。

## 方案对比

| 维度 | 旧方案（prompt 切换） | 新方案（Agent tool 隔离） |
|------|---------------------|-------------------------|
| 上下文隔离 | 共享同一窗口 | 独立子进程，独立上下文 |
| 一致性偏误 | Critic 能看到 Writer 推理 | Critic 只能看到 Writer 输出文件 |
| 模型差异 | 同一模型同一权重 | Writer(sonnet) + Critic(opus) |
| 工具权限 | 所有角色共享工具 | 每个 Agent 受限（如 Critic 无 Bash） |
| 数据传递 | 内存中传递 | 文件系统 workspace/ |
| Token 消耗 | 较低（共享上下文） | 较高（各自独立读取文献） |

## 技术实现

使用 Claude Code 的 `.claude/agents/` 自定义 Agent 功能：

```
project/.claude/agents/
  writer-agent.md      # model: sonnet, tools: [Read,Grep,Glob,Bash,Write]
  critic-agent.md      # model: opus,   tools: [Read,Grep,Glob,Write]
  fact-checker-agent.md # model: inherit, tools: [Read,Grep,Glob,Bash,Write]
```

Orchestrator（主会话）通过 Agent tool 依次调用各 Agent，通过 `workspace/` 下的文件传递数据。

### 模型选择理由

- **Writer → sonnet**: 生成任务注重流畅度和效率，sonnet 性价比更高
- **Critic → opus**: 审查任务需要深度推理；不同模型权重天然产生视角差异，是打破一致性偏误的核心机制
- **Fact-Checker → inherit**: 机械比对任务（PDF 原文 vs 声明），不需要特定模型能力

## 影响

- 阶段 7-8 从 prompt 切换改为 Agent tool 调用 + 文件传递
- Token 消耗增加（每个 Agent 独立读取文献），但审查质量显著提升
- 需要维护 `workspace/adversarial_manifest.json` 跟踪循环状态
- 阶段 1-6、9-10 不受影响

## 风险

- Agent 输出文件格式不符合预期 → 通过 Agent 定义中的严格 JSON schema 和 orchestrator 验证缓解
- Token 消耗增加 → Fact-Checker 只处理 high severity 问题，控制总消耗
- Agent 调用失败 → Orchestrator 可降级为直接在主上下文中执行（兼容旧方案）
