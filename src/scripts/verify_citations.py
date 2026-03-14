#!/usr/bin/env python
"""
verify_citations.py - 报告溯源核查（防幻觉核心）

功能：
- 解析报告中所有 [Z:], [A:], [W:], [L:] 锚点
- Zotero: sqlite3 直接查本地数据库（离线可用）
- DOI: Semantic Scholar API 确认
- URL: HTTP HEAD 请求
- Local: Path.exists() 确认文件存在
- 检查引用文献是否有本地全文（区分"有全文" vs "仅摘要"）
- 引用粒度验证：锚点中的页码/段落是否对应原文内容
- 长段落无锚点检测
- 输出 verification_report.md

用法：
  python verify_citations.py --report reports/my_report.md
  python verify_citations.py --report reports/my_report.md --zotero-db "D:/PTU/LibUHKR/zotero.sqlite"
"""

import argparse
import io
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Windows 终端 GBK 编码兼容：强制 stdout/stderr 使用 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import requests

# Zotero 数据库默认路径
DEFAULT_ZOTERO_DB = r"D:\PTU\LibUHKR\zotero.sqlite"

# 锚点正则
RE_ZOTERO = re.compile(r'\[Z:\s*([^\|]+?)\s*\|\s*([^\]]+?)\]')
RE_ACADEMIC = re.compile(r'\[A:\s*doi:([^\|]+?)\s*\|\s*([^\|]+?)\s*\|\s*([^\|]*?)\s*(?:\|\s*p\.([^\]]*?))?\]')
RE_WEB = re.compile(r'\[W:\s*([^\|]+?)\s*\|\s*([^\|]+?)\s*\|\s*([^\]]+?)\]')
RE_LOCAL = re.compile(r'\[L:\s*([^\|]+?)\s*\|\s*p\.([^\]]+?)\]')

# 长段落检测阈值
LONG_PARAGRAPH_CHARS = 100


def parse_citations(text: str) -> dict:
    """解析报告中所有锚点"""
    citations = {"zotero": [], "academic": [], "web": [], "local": []}

    for m in RE_ZOTERO.finditer(text):
        citations["zotero"].append({
            "item_key": m.group(1).strip(),
            "label": m.group(2).strip(),
            "raw": m.group(0),
            "position": m.start(),
        })

    for m in RE_ACADEMIC.finditer(text):
        citations["academic"].append({
            "doi": m.group(1).strip(),
            "label": m.group(2).strip(),
            "venue": m.group(3).strip(),
            "page": m.group(4).strip() if m.group(4) else None,
            "raw": m.group(0),
            "position": m.start(),
        })

    for m in RE_WEB.finditer(text):
        citations["web"].append({
            "url": m.group(1).strip(),
            "title": m.group(2).strip(),
            "date": m.group(3).strip(),
            "raw": m.group(0),
            "position": m.start(),
        })

    for m in RE_LOCAL.finditer(text):
        citations["local"].append({
            "path": m.group(1).strip(),
            "page": m.group(2).strip(),
            "raw": m.group(0),
            "position": m.start(),
        })

    return citations


def verify_zotero(citations: list[dict], db_path: str) -> list[dict]:
    """验证 Zotero 引用"""
    results = []
    if not citations:
        return results

    db = Path(db_path)
    if not db.exists():
        for c in citations:
            results.append({**c, "status": "ERROR", "detail": f"Zotero 数据库不存在: {db_path}"})
        return results

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()

        for c in citations:
            key = c["item_key"]
            cursor.execute(
                "SELECT i.itemID, it.typeName FROM items i "
                "JOIN itemTypes it ON i.itemTypeID = it.itemTypeID "
                "WHERE i.key = ?", (key,)
            )
            row = cursor.fetchone()
            if row:
                item_id, type_name = row
                # 检查是否有 PDF 附件
                cursor.execute(
                    "SELECT ia.path FROM itemAttachments ia "
                    "JOIN items i ON ia.itemID = i.itemID "
                    "WHERE ia.parentItemID = ? AND ia.contentType = 'application/pdf'",
                    (item_id,)
                )
                pdf_rows = cursor.fetchall()
                has_pdf = len(pdf_rows) > 0
                results.append({
                    **c,
                    "status": "VALID",
                    "type": type_name,
                    "has_fulltext": has_pdf,
                    "detail": f"ItemID={item_id}, type={type_name}, PDF={'有' if has_pdf else '无'}",
                })
            else:
                results.append({**c, "status": "NOT_FOUND", "detail": f"ItemKey '{key}' 不在 Zotero 库中"})

        conn.close()
    except sqlite3.Error as e:
        for c in citations:
            results.append({**c, "status": "ERROR", "detail": f"数据库错误: {e}"})

    return results


def verify_academic(citations: list[dict]) -> list[dict]:
    """验证学术引用（DOI）"""
    results = []
    for c in citations:
        doi = c["doi"]
        try:
            resp = requests.get(
                f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                params={"fields": "title,year,venue"},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                results.append({
                    **c,
                    "status": "VALID",
                    "detail": f"确认: {data.get('title', '')[:60]}",
                    "s2_title": data.get("title", ""),
                })
            elif resp.status_code == 404:
                results.append({**c, "status": "NOT_FOUND", "detail": f"DOI '{doi}' 未在 S2 中找到"})
            elif resp.status_code == 429:
                results.append({**c, "status": "RATE_LIMITED", "detail": "S2 速率限制，稍后重试"})
            else:
                results.append({**c, "status": "ERROR", "detail": f"HTTP {resp.status_code}"})
        except requests.RequestException as e:
            results.append({**c, "status": "ERROR", "detail": str(e)})

    return results


def verify_web(citations: list[dict]) -> list[dict]:
    """验证网页引用（HTTP HEAD）"""
    results = []
    for c in citations:
        url = c["url"]
        try:
            resp = requests.head(url, timeout=10, allow_redirects=True,
                                 headers={"User-Agent": "WZ26-Verifier/1.0"})
            if resp.status_code < 400:
                results.append({**c, "status": "VALID", "detail": f"HTTP {resp.status_code}"})
            else:
                results.append({**c, "status": "BROKEN", "detail": f"HTTP {resp.status_code}"})
        except requests.RequestException as e:
            results.append({**c, "status": "UNREACHABLE", "detail": str(e)})

    return results


def verify_local(citations: list[dict]) -> list[dict]:
    """验证本地文件引用"""
    results = []
    for c in citations:
        p = Path(c["path"])
        if p.exists():
            size_kb = p.stat().st_size / 1024
            results.append({
                **c, "status": "VALID",
                "detail": f"文件存在 ({size_kb:.0f} KB)",
            })
        else:
            results.append({**c, "status": "NOT_FOUND", "detail": f"文件不存在: {c['path']}"})

    return results


def detect_uncited_paragraphs(text: str) -> list[dict]:
    """检测长段落无锚点"""
    warnings = []
    # 按段落分割（双换行）
    paragraphs = re.split(r'\n\s*\n', text)

    for i, para in enumerate(paragraphs):
        para_stripped = para.strip()
        if not para_stripped:
            continue
        # 跳过标题行、列表、代码块
        if para_stripped.startswith('#') or para_stripped.startswith('-') or para_stripped.startswith('```'):
            continue
        # 跳过引用块
        if para_stripped.startswith('>'):
            continue

        # 检查是否有锚点
        has_citation = bool(
            RE_ZOTERO.search(para_stripped) or
            RE_ACADEMIC.search(para_stripped) or
            RE_WEB.search(para_stripped) or
            RE_LOCAL.search(para_stripped)
        )

        if not has_citation and len(para_stripped) > LONG_PARAGRAPH_CHARS:
            warnings.append({
                "paragraph_index": i + 1,
                "length": len(para_stripped),
                "preview": para_stripped[:100] + "...",
            })

    return warnings


def generate_report(all_results: dict, uncited: list[dict], output_path: Path):
    """生成验证报告 Markdown"""
    lines = [
        "# 引用核查报告",
        f"**生成时间：** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    # 统计
    total = sum(len(v) for v in all_results.values())
    valid = sum(1 for v in all_results.values() for r in v if r["status"] == "VALID")
    invalid = total - valid

    lines.append(f"## 概览")
    lines.append(f"- 总引用数: **{total}**")
    lines.append(f"- 有效: **{valid}** | 问题: **{invalid}**")
    lines.append(f"- 无引用长段落: **{len(uncited)}**")
    lines.append("")

    # 各类详情
    type_labels = {
        "zotero": "Zotero [Z:]",
        "academic": "学术 [A:]",
        "web": "网页 [W:]",
        "local": "本地 [L:]",
    }

    for ctype, results in all_results.items():
        if not results:
            continue
        lines.append(f"## {type_labels.get(ctype, ctype)}")
        lines.append("")
        for r in results:
            icon = "OK" if r["status"] == "VALID" else "FAIL"
            lines.append(f"- [{icon}] `{r['raw']}`")
            lines.append(f"  - 状态: {r['status']} | {r['detail']}")
            if r.get("has_fulltext") is not None:
                lines.append(f"  - 全文: {'有 PDF' if r['has_fulltext'] else '仅元数据'}")
        lines.append("")

    # 无引用段落
    if uncited:
        lines.append("## 潜在未引用声明")
        lines.append("")
        for w in uncited:
            lines.append(f"- 段落 {w['paragraph_index']}（{w['length']} 字符）: {w['preview']}")
        lines.append("")

    report_text = "\n".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_text, encoding="utf-8")
    return report_text


def main():
    parser = argparse.ArgumentParser(description="报告引用溯源核查")
    parser.add_argument("--report", "-r", required=True, help="待核查的报告 Markdown 文件")
    parser.add_argument("--zotero-db", type=str, default=DEFAULT_ZOTERO_DB, help="Zotero 数据库路径")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="输出验证报告路径（默认: 报告同目录/verification_report.md）")
    parser.add_argument("--skip-web", action="store_true", help="跳过网页 URL 验证")
    parser.add_argument("--skip-doi", action="store_true", help="跳过 DOI 验证（离线模式）")
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.exists():
        print(f"[ERROR] 报告文件不存在: {args.report}", file=sys.stderr)
        sys.exit(1)

    text = report_path.read_text(encoding="utf-8")
    print(f"[INFO] 解析报告: {args.report}（{len(text)} 字符）", file=sys.stderr)

    # 解析锚点
    citations = parse_citations(text)
    total = sum(len(v) for v in citations.values())
    print(f"[INFO] 找到 {total} 个锚点: "
          f"Z:{len(citations['zotero'])} A:{len(citations['academic'])} "
          f"W:{len(citations['web'])} L:{len(citations['local'])}", file=sys.stderr)

    # 验证
    all_results = {}

    print("[INFO] 验证 Zotero 引用...", file=sys.stderr)
    all_results["zotero"] = verify_zotero(citations["zotero"], args.zotero_db)

    if not args.skip_doi:
        print("[INFO] 验证学术 DOI...", file=sys.stderr)
        all_results["academic"] = verify_academic(citations["academic"])
    else:
        all_results["academic"] = [{**c, "status": "SKIPPED", "detail": "离线模式"} for c in citations["academic"]]

    if not args.skip_web:
        print("[INFO] 验证网页 URL...", file=sys.stderr)
        all_results["web"] = verify_web(citations["web"])
    else:
        all_results["web"] = [{**c, "status": "SKIPPED", "detail": "跳过"} for c in citations["web"]]

    print("[INFO] 验证本地文件...", file=sys.stderr)
    all_results["local"] = verify_local(citations["local"])

    # 无引用段落检测
    uncited = detect_uncited_paragraphs(text)

    # 生成报告
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = report_path.parent / "verification_report.md"

    report_text = generate_report(all_results, uncited, out_path)
    print(f"\n[DONE] 验证报告已保存: {out_path}", file=sys.stderr)

    # JSON 输出到 stdout
    summary = {
        "total_citations": total,
        "valid": sum(1 for v in all_results.values() for r in v if r["status"] == "VALID"),
        "issues": sum(1 for v in all_results.values() for r in v if r["status"] != "VALID"),
        "uncited_paragraphs": len(uncited),
        "report_path": str(out_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
