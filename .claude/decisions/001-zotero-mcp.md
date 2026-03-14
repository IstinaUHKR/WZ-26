# ADR 001：使用 cookjohn/zotero-mcp 本地插件

**日期：** 2026-03-14
**状态：** 已确认

## 决策

使用已安装在 Zotero Desktop 中的 cookjohn/zotero-mcp 插件（HTTP 服务，端口 23120），
而非通过 zotero.org REST API 或 54yyyu/zotero-mcp npm 包访问文献库。

## 理由

1. 插件已安装（`zotero-mcp-vectors.sqlite` 已存在，说明向量索引曾运行）
2. 本地 HTTP 服务直接读取 `D:\PTU\LibUHKR\zotero.sqlite`，无需 API Key
3. 支持语义搜索（semantic_search 工具）
4. 可访问本地 PDF 全文，不受付费墙限制
5. 无网络延迟，无速率限制

## 前提条件

Zotero Desktop 必须运行，且在首选项中启用了 MCP 服务器（端口 23120）。
`verify_citations.py` 通过 sqlite3 直接查数据库，不依赖此服务，可离线运行。
