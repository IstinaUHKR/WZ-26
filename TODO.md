# WZ-26 TODO — 实时进度跟踪

**每次对话开始时读此文件，完成后更新状态。**

---

## 当前阶段：Phase 5 — 测试验证 ✅ 全部完成

---

## 任务清单

### Phase 1：基础配置
- [x] **1.1** 用户启用 Zotero MCP 服务器（端口 23120）— *用户已确认*
- [x] **1.2** 创建 `.mcp.json`，添加 Zotero MCP 配置（streamable-http, localhost:23120/mcp）
- [x] **1.3** 确认项目 `.claude/settings.json` 权限配置正确

### Phase 2：Python 脚本编写
- [x] **2.1** `src/scripts/search_academic.py` — S2 + OpenAlex + OA 链接获取（已测试，OpenAlex 正常）
- [x] **2.2** `src/scripts/download_papers.py` — OA 下载到 workspace/papers/
- [x] **2.3** `src/scripts/search_web.py` — Tavily 全网多轮检索状态管理
- [x] **2.4** `src/scripts/verify_citations.py` — 锚点解析 + 溯源核查 + 无引用段落检测
- [x] **2.5** `src/scripts/read_local_pdf.py` — PDF 扫描/提取/搜索（scan/extract/search 三命令）
- [x] **2.6** `src/scripts/cleanup_workspace.py` — 清空 workspace/ 临时文件

### Phase 3：技能定义（Claude Code Skill）
- [x] **3.1** `skill/SKILL.md` — 三 Agent 对抗工作流（10 阶段）
- [x] **3.2** `skill/references/` — architecture.md, prompts.md, workflow.md
- [x] **3.3** 软链接到 `C:\Users\lenovo\.agents\skills\WZ-26`

### Phase 4：架构决策记录
- [x] **4.1** `.claude/decisions/001-zotero-mcp.md`（之前已存在）
- [x] **4.2** `.claude/decisions/002-search-strategy.md`（之前已存在）
- [x] **4.3** `.claude/decisions/003-citation-anchors.md`（之前已存在）
- [x] **4.4** `.claude/decisions/004-multi-agent-adversarial.md` — 三 Agent 对抗设计

### Phase 5：测试验证
- [x] **5.1** 重启 Claude Code，确认 Zotero MCP 工具可用（`mcp__zotero__*`）— *HTTP 200 + 13 工具可用*
- [x] **5.2** Zotero 搜索测试 — *search_library 返回 162 条 + get_item_details 完整元数据（DOI/摘要等）*
- [x] **5.3** search_academic.py 查询测试 — *OpenAlex 正常；S2 偶发 429（已知限速）*
- [x] **5.4** download_papers.py 下载到 workspace/ 测试 — *acquired.json + pending_manual.json 正确生成*
- [x] **5.5** search_web.py 全网检索测试 — *init/add/status 三命令全部通过*
- [x] **5.5b** read_local_pdf.py PDF 扫描/提取/搜索测试 — *scan/extract/search 通过*
- [x] **5.6** 端到端 `/WZ-26` 全流程测试（含对抗循环 + 暂停点）— *10 阶段全部验证通过*
- [x] **5.7** verify_citations.py 核查测试 — *DOI/URL/本地文件验证 + 无引用段落检测*
- [x] **5.8** 确认 workspace/ 自动清空 — *cleanup_workspace.py 正确清理*

---

## 上次会话结束状态

- **Phase 1-5 全部完成** ✅
- 5.1: Zotero MCP 服务器 HTTP 200，13 个工具可用
- 5.2: search_library 返回 162 条 + get_item_details 完整元数据
- 5.6: 端到端 10 阶段模拟测试全部通过
  - 阶段 1-2: 范围定义 + Zotero 集合列表（6 个集合）
  - 阶段 3: Zotero 预扫搜索正常
  - 阶段 4: search_academic.py（OpenAlex 5 篇）+ download_papers.py（acquired + pending_manual 正确生成）
  - 阶段 5: search_web.py init 成功
  - 阶段 6: pending_manual.json 格式完整
  - 阶段 7-8: read_local_pdf.py scan/extract 正常（PDF 全文提取验证通过）
  - 阶段 9: verify_citations.py 核查（3 锚点验证 + 无引用段落检测）
  - 阶段 10: cleanup_workspace.py 清理成功
- 已知限制：S2 API 429 限速；Zotero DB 直接访问时 locked（通过 MCP API 可正常查询）
- **项目可投入使用**

---

## 备注

- 新会话开始时：读 TODO.md → 确认当前阶段 → 继续下一个未完成任务
- 完成任务后：将 `[ ]` 改为 `[x]`，更新"当前阶段"和"上次会话结束状态"
- 遇到阻塞：在备注区记录原因
- **Zotero MCP 配置位置：** `project/.mcp.json`（非全局 settings.json，Claude Code 不支持在全局 settings 中配置 mcpServers）
- **S2 速率限制：** Semantic Scholar API 偶尔返回 429，通过增加请求间隔缓解
