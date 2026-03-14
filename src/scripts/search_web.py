#!/usr/bin/env python
"""
search_web.py - 全网检索封装（配合 Tavily MCP 使用）

功能：
- 封装 Tavily 搜索结果处理
- 支持多轮迭代检索（读取上轮结果，生成新查询建议）
- 保存网页快照到 workspace/web_cache/
- 结果追加到 workspace/acquired.json

设计说明：
  实际的 Tavily 检索由 Claude 通过 MCP 工具（tavily_search / tavily_extract）执行。
  本脚本负责：
  1. 管理检索状态（多轮迭代追踪）
  2. 结构化存储网页来源
  3. 将网页来源追加到 acquired.json，与学术论文统一管理

用法：
  # 初始化检索会话
  python search_web.py init --query "ADS reactor safety" --workspace ./workspace

  # 记录一轮检索结果（由 Claude 调用 Tavily 后传入）
  python search_web.py add --session web_session.json --results tavily_results.json

  # 查看当前检索状态
  python search_web.py status --session web_session.json
"""

import argparse
import hashlib
import io
import json
import sys
from datetime import datetime
from pathlib import Path

# Windows 终端 GBK 编码兼容：强制 stdout/stderr 使用 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def cmd_init(args):
    """初始化检索会话"""
    ws = Path(args.workspace).resolve()  # 转换为绝对路径，避免跨目录调用时路径错误
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "web_cache").mkdir(exist_ok=True)

    session = {
        "query": args.query,
        "max_rounds": args.max_rounds,
        "current_round": 0,
        "created_at": datetime.now().isoformat(),
        "rounds": [],
        "all_urls": [],  # 已检索的 URL 列表（用于去重）
    }

    session_path = ws / "web_session.json"
    session_path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INFO] 检索会话已初始化: {session_path}", file=sys.stderr)
    print(json.dumps({"session_path": str(session_path), "query": args.query}))


def cmd_add(args):
    """添加一轮检索结果"""
    session_path = Path(args.session)
    if not session_path.exists():
        print(f"[ERROR] 会话文件不存在: {args.session}", file=sys.stderr)
        sys.exit(1)

    session = json.loads(session_path.read_text(encoding="utf-8"))

    # 读取 Tavily 结果
    if args.results == "-":
        results_data = json.loads(sys.stdin.read())
    else:
        results_path = Path(args.results)
        results_data = json.loads(results_path.read_text(encoding="utf-8"))

    # 处理结果列表（支持直接列表或 Tavily 格式的 { results: [...] }）
    if isinstance(results_data, list):
        items = results_data
    else:
        items = results_data.get("results", results_data.get("items", []))

    # 去重
    existing_urls = set(session.get("all_urls", []))
    new_items = []
    for item in items:
        url = item.get("url", "")
        if url and url not in existing_urls:
            new_items.append(item)
            existing_urls.add(url)

    # 保存网页快照到 web_cache
    ws = session_path.parent
    cache_dir = ws / "web_cache"
    cache_dir.mkdir(exist_ok=True)

    cached_items = []
    for item in new_items:
        url = item.get("url", "")
        title = item.get("title", "")
        content = item.get("content", item.get("text", item.get("snippet", "")))
        raw_content = item.get("raw_content", "")

        # 生成缓存文件名
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        cache_file = cache_dir / f"{url_hash}.json"
        cache_data = {
            "url": url,
            "title": title,
            "content": content,
            "raw_content": raw_content,
            "fetched_at": datetime.now().isoformat(),
            "round": session["current_round"] + 1,
        }
        cache_file.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")

        cached_items.append({
            "url": url,
            "title": title,
            "snippet": content[:500] if content else "",
            "cache_file": str(cache_file.relative_to(ws)),
        })

    # 更新会话
    session["current_round"] += 1
    session["rounds"].append({
        "round": session["current_round"],
        "timestamp": datetime.now().isoformat(),
        "new_results": len(cached_items),
        "query_used": args.query_used or session["query"],
        "items": cached_items,
    })
    session["all_urls"] = list(existing_urls)

    session_path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")

    # 追加到 acquired.json
    acquired_path = ws / "acquired.json"
    if acquired_path.exists():
        acquired = json.loads(acquired_path.read_text(encoding="utf-8"))
    else:
        acquired = {"papers": [], "web_sources": []}

    if "web_sources" not in acquired:
        acquired["web_sources"] = []

    for item in cached_items:
        acquired["web_sources"].append({
            "url": item["url"],
            "title": item["title"],
            "cache_file": item["cache_file"],
            "fetched_at": datetime.now().isoformat(),
            "type": "web",
        })

    acquired_path.write_text(json.dumps(acquired, ensure_ascii=False, indent=2), encoding="utf-8")

    # 输出状态
    print(f"[INFO] 第 {session['current_round']} 轮: 新增 {len(cached_items)} 条网页来源", file=sys.stderr)
    remaining = session["max_rounds"] - session["current_round"]
    print(f"[INFO] 剩余轮数: {remaining}", file=sys.stderr)

    print(json.dumps({
        "round": session["current_round"],
        "new_results": len(cached_items),
        "total_urls": len(session["all_urls"]),
        "remaining_rounds": remaining,
        "done": remaining <= 0,
    }))


def cmd_status(args):
    """查看检索状态"""
    session_path = Path(args.session)
    if not session_path.exists():
        print(f"[ERROR] 会话文件不存在: {args.session}", file=sys.stderr)
        sys.exit(1)

    session = json.loads(session_path.read_text(encoding="utf-8"))

    status = {
        "query": session["query"],
        "current_round": session["current_round"],
        "max_rounds": session["max_rounds"],
        "total_urls": len(session.get("all_urls", [])),
        "rounds_detail": [
            {"round": r["round"], "new_results": r["new_results"], "query_used": r.get("query_used", "")}
            for r in session.get("rounds", [])
        ],
    }
    print(json.dumps(status, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="全网检索状态管理")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="初始化检索会话")
    p_init.add_argument("--query", "-q", required=True, help="初始检索关键词")
    p_init.add_argument("--workspace", "-w", required=True, help="workspace 目录路径")
    p_init.add_argument("--max-rounds", type=int, default=5, help="最大检索轮数（默认 5）")

    # add
    p_add = subparsers.add_parser("add", help="添加一轮检索结果")
    p_add.add_argument("--session", "-s", required=True, help="会话文件路径")
    p_add.add_argument("--results", "-r", required=True, help="Tavily 结果 JSON 文件（- 表示 stdin）")
    p_add.add_argument("--query-used", type=str, default=None, help="本轮实际使用的查询词")

    # status
    p_status = subparsers.add_parser("status", help="查看检索状态")
    p_status.add_argument("--session", "-s", required=True, help="会话文件路径")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "add":
        cmd_add(args)
    elif args.command == "status":
        cmd_status(args)


if __name__ == "__main__":
    main()
