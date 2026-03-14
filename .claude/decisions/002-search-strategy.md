# ADR 002：使用 Claude+Tavily 自身执行检索，不使用 gpt-researcher 的 LLM 调用

**日期：** 2026-03-14
**状态：** 已确认

## 决策

`D:\PTU\gptresearcher\gpt-researcher\` 已有完整的 gpt-researcher 代码，
但其 `.env` 配置的是 zenmux.ai 上的 Gemini 模型。
本项目**不使用**该 LLM 配置，而是让 Claude 自身通过 Tavily MCP 工具直接执行多轮检索。

## 理由

1. 用户明确表示"想让你来检索"，即由 Claude 本身执行，而非调用另一个 LLM
2. 避免双重 LLM 调用的成本和延迟
3. Claude 可直接控制检索策略、来源选择和报告生成，质量更可控
4. gpt-researcher 的代码可作为**参考**（检索策略、prompt 设计），但不作为运行时依赖

## 保留 gpt-researcher 的价值

- `gpt_researcher/prompts.py`：研究问题拆解的 prompt 模板可参考
- `gpt_researcher/mcp/`：MCP 工具选择策略可参考
- 不复制到工作目录，仅在需要时查阅原始路径
