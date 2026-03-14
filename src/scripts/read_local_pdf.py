#!/usr/bin/env python
"""
read_local_pdf.py - 本地 PDF 扫描 + 关键词相关性打分 + 按页码提取

功能：
- 用 pdfplumber 扫描指定文件夹中的 PDF
- 关键词相关性打分，返回 Top-N 相关文件及摘录
- 支持按页码/页码范围提取特定内容（供 Fact-Checker 使用）

用法：
  # 扫描文件夹，按关键词排序
  python read_local_pdf.py scan --folder workspace/papers/ --keywords "subcritical reactor safety"

  # 提取指定 PDF 的指定页面
  python read_local_pdf.py extract --file workspace/papers/xxx.pdf --pages 7-9

  # 在指定 PDF 中搜索关键词并返回上下文
  python read_local_pdf.py search --file workspace/papers/xxx.pdf --query "safety margin"
"""

import argparse
import io
import json
import re
import sys
from pathlib import Path

# Windows 终端 GBK 编码兼容：强制 stdout/stderr 使用 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

try:
    import pdfplumber
except ImportError:
    print("[ERROR] 需要安装 pdfplumber: pip install pdfplumber", file=sys.stderr)
    sys.exit(1)


def extract_page_text(pdf_path: str, page_num: int) -> str:
    """提取单页文本"""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_num < 1 or page_num > len(pdf.pages):
                return ""
            page = pdf.pages[page_num - 1]  # pdfplumber 是 0-indexed
            return page.extract_text() or ""
    except Exception as e:
        return f"[ERROR] {e}"


def extract_pages(pdf_path: str, page_range: str) -> list[dict]:
    """提取指定页码范围的文本"""
    results = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)

            # 解析页码范围: "7", "7-9", "1,3,5-7"
            pages_to_extract = set()
            for part in page_range.split(","):
                part = part.strip()
                if "-" in part:
                    start, end = part.split("-", 1)
                    for p in range(int(start), int(end) + 1):
                        pages_to_extract.add(p)
                else:
                    pages_to_extract.add(int(part))

            for pnum in sorted(pages_to_extract):
                if 1 <= pnum <= total:
                    text = pdf.pages[pnum - 1].extract_text() or ""
                    results.append({
                        "page": pnum,
                        "text": text,
                        "char_count": len(text),
                    })
                else:
                    results.append({
                        "page": pnum,
                        "text": "",
                        "char_count": 0,
                        "error": f"超出范围（总页数: {total}）",
                    })
    except Exception as e:
        results.append({"error": str(e)})

    return results


def score_relevance(text: str, keywords: list[str]) -> float:
    """简单关键词相关性评分"""
    if not text:
        return 0.0
    text_lower = text.lower()
    total_matches = 0
    for kw in keywords:
        total_matches += text_lower.count(kw.lower())
    # 归一化：每千字符匹配数
    return total_matches / max(len(text) / 1000, 1)


def cmd_scan(args):
    """扫描文件夹中的 PDF，按关键词相关性排序"""
    folder = Path(args.folder).resolve()  # 转换为绝对路径
    if not folder.exists():
        print(f"[ERROR] 文件夹不存在: {args.folder}", file=sys.stderr)
        sys.exit(1)

    pdf_files = list(folder.glob("*.pdf"))
    if not pdf_files:
        print(f"[INFO] 文件夹中无 PDF: {args.folder}", file=sys.stderr)
        print(json.dumps({"results": [], "total": 0}))
        return

    keywords = args.keywords.split()
    print(f"[INFO] 扫描 {len(pdf_files)} 个 PDF，关键词: {keywords}", file=sys.stderr)

    results = []
    for pdf_path in pdf_files:
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                total_pages = len(pdf.pages)
                # 采样前 5 页 + 最后 1 页评估相关性
                sample_pages = list(range(min(5, total_pages))) + [total_pages - 1] if total_pages > 5 else list(range(total_pages))
                sample_text = ""
                for idx in set(sample_pages):
                    sample_text += (pdf.pages[idx].extract_text() or "") + "\n"

                rel_score = score_relevance(sample_text, keywords)

                results.append({
                    "file": str(pdf_path),
                    "filename": pdf_path.name,
                    "total_pages": total_pages,
                    "relevance_score": round(rel_score, 3),
                    "sample_preview": sample_text[:300].strip(),
                })
        except Exception as e:
            print(f"  [WARN] 无法读取 {pdf_path.name}: {e}", file=sys.stderr)
            results.append({
                "file": str(pdf_path),
                "filename": pdf_path.name,
                "error": str(e),
                "relevance_score": 0,
            })

    # 按相关性排序
    results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    # 取 Top-N
    top_n = results[:args.top]

    print(f"[INFO] Top {len(top_n)} 相关文件:", file=sys.stderr)
    for r in top_n:
        print(f"  {r['relevance_score']:.3f} | {r['filename']}", file=sys.stderr)

    print(json.dumps({"results": top_n, "total_scanned": len(pdf_files)}, ensure_ascii=False, indent=2))


def cmd_extract(args):
    """提取指定页面内容"""
    pdf_path = Path(args.file).resolve()  # 转换为绝对路径
    if not pdf_path.exists():
        print(f"[ERROR] 文件不存在: {args.file}", file=sys.stderr)
        sys.exit(1)

    pages = extract_pages(str(pdf_path), args.pages)
    output = {
        "file": str(pdf_path),
        "filename": pdf_path.name,
        "requested_pages": args.pages,
        "pages": pages,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_search(args):
    """在 PDF 中搜索关键词"""
    pdf_path = Path(args.file).resolve()  # 转换为绝对路径
    if not pdf_path.exists():
        print(f"[ERROR] 文件不存在: {args.file}", file=sys.stderr)
        sys.exit(1)

    query = args.query.lower()
    context_chars = args.context

    matches = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                text_lower = text.lower()

                # 查找所有匹配位置
                start = 0
                while True:
                    pos = text_lower.find(query, start)
                    if pos == -1:
                        break

                    # 提取上下文
                    ctx_start = max(0, pos - context_chars)
                    ctx_end = min(len(text), pos + len(query) + context_chars)
                    context = text[ctx_start:ctx_end]

                    matches.append({
                        "page": i + 1,
                        "position": pos,
                        "context": context,
                    })
                    start = pos + 1

    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] 找到 {len(matches)} 处匹配", file=sys.stderr)
    output = {
        "file": str(pdf_path),
        "query": args.query,
        "total_matches": len(matches),
        "matches": matches[:args.limit],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="本地 PDF 扫描与提取")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = subparsers.add_parser("scan", help="扫描文件夹 PDF 并按关键词相关性排序")
    p_scan.add_argument("--folder", "-f", required=True, help="PDF 文件夹路径")
    p_scan.add_argument("--keywords", "-k", required=True, help="检索关键词（空格分隔）")
    p_scan.add_argument("--top", "-n", type=int, default=10, help="返回 Top-N 结果（默认 10）")

    # extract
    p_extract = subparsers.add_parser("extract", help="提取指定页面内容")
    p_extract.add_argument("--file", "-f", required=True, help="PDF 文件路径")
    p_extract.add_argument("--pages", "-p", required=True, help="页码范围（如 7, 7-9, 1,3,5-7）")

    # search
    p_search = subparsers.add_parser("search", help="在 PDF 中搜索关键词")
    p_search.add_argument("--file", "-f", required=True, help="PDF 文件路径")
    p_search.add_argument("--query", "-q", required=True, help="搜索关键词")
    p_search.add_argument("--context", "-c", type=int, default=200, help="上下文字符数（默认 200）")
    p_search.add_argument("--limit", "-l", type=int, default=20, help="最多返回匹配数（默认 20）")

    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "extract":
        cmd_extract(args)
    elif args.command == "search":
        cmd_search(args)


if __name__ == "__main__":
    main()
