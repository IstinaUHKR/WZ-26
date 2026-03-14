# ADR 004：三 Agent 对抗架构设计

**日期：** 2026-03-14
**状态：** 已确认

## 决策

采用 Writer-Critic-Fact-Checker 三角对抗架构，而非传统的单 Agent 生成或双 Agent 审查模式。

## 背景

AI 生成的研究报告存在两个核心问题：
1. **检索不充分** — 遗漏关键文献，结论基于片面证据
2. **理解不准确** — 虚构来源（幻觉）、夸大原文结论、错误解读文献内容

gpt-researcher 采用 Reviewer↔Revisor 双角色循环，但 Reviewer 和 Revisor 本质上是同一个 LLM，容易陷入"自己审自己"的一致性偏误。

## 方案对比

| 方案 | 优点 | 缺点 |
|------|------|------|
| 单 Agent | 简单、快速 | 无审查，幻觉无法发现 |
| Reviewer↔Revisor（gpt-researcher 模式）| 有审查循环 | 同一 LLM 审查自己，一致性偏误 |
| **Writer-Critic-Fact-Checker**（本方案）| 三角独立视角 | 消耗更多 token |

## 设计要点

1. **角色分离**：三个 Agent 有不同的约束规则和工具权限
   - Writer 只能用已获取文献，不能凭记忆
   - Critic 只做审查，不修改报告
   - Fact-Checker 强制回到 PDF 原文，使用 read_local_pdf.py 逐句比对

2. **打破一致性偏误**：Fact-Checker 的关键作用
   - 即使 Writer 和 Critic 都"觉得"某个引用正确，Fact-Checker 会实际读取 PDF 验证
   - 这是唯一能检测"精确幻觉"（看似合理但实际不存在于原文中的声明）的手段

3. **最多 3 轮迭代**
   - 每轮对抗消耗约 1/3 的总 token 预算
   - 3 轮是成本/质量的经验平衡点
   - 超过 3 轮通常意味着文献基础本身不足，应触发补充检索

4. **降级机制**
   - 无法解决的问题不强行删除，而是标记为 UNVERIFIED 移入附录
   - 让用户看到"哪些声明当前证据不支持"比隐藏问题更有价值

## 限制

- 三个 Agent 实际上是同一个 Claude 实例通过 prompt 切换角色
- 角色切换依赖 prompt 指令，不是完全独立的系统
- Fact-Checker 的 PDF 阅读能力受 pdfplumber 文本提取质量限制
