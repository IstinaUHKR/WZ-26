#!/usr/bin/env python
"""
search_academic.py - 学术数据库检索（Semantic Scholar + OpenAlex + OA链接获取）

功能：
- 查询 Semantic Scholar API 和 OpenAlex API（均免费，无需 API Key）
- 按 DOI 去重，按引用量排序
- 自动获取 OA 全文链接（Unpaywall / OpenAlex / S2）
- 输出 JSON：title, authors, year, doi, abstract, citation_count, venue, open_access_url, pdf_status

用法：
  python search_academic.py --query "accelerator driven subcritical" --limit 20
  python search_academic.py --query "ADS reactor safety" --limit 10 --output results.json
"""

import argparse
import io
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

# Windows 终端 GBK 编码兼容：强制 stdout/stderr 使用 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import requests

# API 端点
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "title,authors,year,externalIds,abstract,citationCount,venue,isOpenAccess,openAccessPdf"

OPENALEX_API = "https://api.openalex.org/works"
UNPAYWALL_API = "https://api.unpaywall.org/v2"
UNPAYWALL_EMAIL = "wz26-tool@example.com"  # Unpaywall 要求提供邮箱

# 请求间隔（秒），避免触发速率限制
REQUEST_DELAY = 1.0


def search_semantic_scholar(query: str, limit: int = 20, offset: int = 0) -> list[dict]:
    """查询 Semantic Scholar API"""
    params = {
        "query": query,
        "limit": min(limit, 100),  # S2 单次最多 100
        "offset": offset,
        "fields": S2_FIELDS,
    }
    try:
        resp = requests.get(S2_API, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        print(f"[WARN] Semantic Scholar 查询失败: {e}", file=sys.stderr)
        return []

    results = []
    for paper in data.get("data", []):
        doi = (paper.get("externalIds") or {}).get("DOI")
        oa_pdf = paper.get("openAccessPdf") or {}
        results.append({
            "source": "semantic_scholar",
            "title": paper.get("title", ""),
            "authors": [a.get("name", "") for a in (paper.get("authors") or [])],
            "year": paper.get("year"),
            "doi": doi,
            "abstract": paper.get("abstract", ""),
            "citation_count": paper.get("citationCount", 0),
            "venue": paper.get("venue", ""),
            "is_open_access": paper.get("isOpenAccess", False),
            "open_access_url": oa_pdf.get("url", ""),
            "pdf_status": "oa_available" if oa_pdf.get("url") else "unknown",
        })
    return results


def search_openalex(query: str, limit: int = 20) -> list[dict]:
    """查询 OpenAlex API"""
    params = {
        "search": query,
        "per_page": min(limit, 200),  # OpenAlex 单次最多 200
        "select": "id,doi,title,authorships,publication_year,cited_by_count,"
                  "primary_location,open_access,abstract_inverted_index",
    }
    headers = {"User-Agent": "WZ26-DeepResearch/1.0 (mailto:wz26-tool@example.com)"}
    try:
        resp = requests.get(OPENALEX_API, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        print(f"[WARN] OpenAlex 查询失败: {e}", file=sys.stderr)
        return []

    results = []
    for work in data.get("results", []):
        doi_raw = work.get("doi", "") or ""
        doi = doi_raw.replace("https://doi.org/", "") if doi_raw else None

        # 还原倒排索引为摘要文本
        abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))

        # OA 信息
        oa_info = work.get("open_access") or {}
        oa_url = oa_info.get("oa_url", "")

        # 期刊/会议
        primary = work.get("primary_location") or {}
        source = primary.get("source") or {}
        venue = source.get("display_name", "")

        results.append({
            "source": "openalex",
            "title": work.get("title", ""),
            "authors": [
                (a.get("author") or {}).get("display_name", "")
                for a in (work.get("authorships") or [])
            ],
            "year": work.get("publication_year"),
            "doi": doi,
            "abstract": abstract,
            "citation_count": work.get("cited_by_count", 0),
            "venue": venue,
            "is_open_access": oa_info.get("is_oa", False),
            "open_access_url": oa_url,
            "pdf_status": "oa_available" if oa_url else "unknown",
        })
    return results


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """从 OpenAlex 的倒排索引还原摘要文本"""
    if not inverted_index:
        return ""
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in word_positions)


def lookup_unpaywall(doi: str) -> str:
    """通过 Unpaywall 查找 OA 链接"""
    if not doi:
        return ""
    url = f"{UNPAYWALL_API}/{quote(doi, safe='')}?email={UNPAYWALL_EMAIL}"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            best = data.get("best_oa_location") or {}
            return best.get("url_for_pdf", "") or best.get("url", "")
    except requests.RequestException:
        pass
    return ""


def deduplicate_and_merge(s2_results: list[dict], oa_results: list[dict]) -> list[dict]:
    """按 DOI 去重，合并两个来源的结果"""
    seen_dois = {}
    merged = []

    # S2 结果优先
    for item in s2_results:
        doi = item.get("doi")
        if doi:
            doi_lower = doi.lower()
            if doi_lower not in seen_dois:
                seen_dois[doi_lower] = len(merged)
                merged.append(item)
            else:
                # 合并：取更高引用数、补充缺失字段
                idx = seen_dois[doi_lower]
                existing = merged[idx]
                if item["citation_count"] > existing["citation_count"]:
                    existing["citation_count"] = item["citation_count"]
                if not existing["abstract"] and item["abstract"]:
                    existing["abstract"] = item["abstract"]
                if not existing["open_access_url"] and item["open_access_url"]:
                    existing["open_access_url"] = item["open_access_url"]
                    existing["pdf_status"] = item["pdf_status"]
        else:
            # 无 DOI，按标题去重
            title_key = (item.get("title") or "").lower().strip()
            if title_key and title_key not in seen_dois:
                seen_dois[title_key] = len(merged)
                merged.append(item)

    # OpenAlex 结果补充
    for item in oa_results:
        doi = item.get("doi")
        if doi:
            doi_lower = doi.lower()
            if doi_lower not in seen_dois:
                seen_dois[doi_lower] = len(merged)
                merged.append(item)
            else:
                idx = seen_dois[doi_lower]
                existing = merged[idx]
                if not existing["open_access_url"] and item["open_access_url"]:
                    existing["open_access_url"] = item["open_access_url"]
                    existing["pdf_status"] = item["pdf_status"]
                if not existing["abstract"] and item["abstract"]:
                    existing["abstract"] = item["abstract"]
        else:
            title_key = (item.get("title") or "").lower().strip()
            if title_key and title_key not in seen_dois:
                seen_dois[title_key] = len(merged)
                merged.append(item)

    return merged


def enrich_oa_links(results: list[dict], use_unpaywall: bool = True) -> list[dict]:
    """对尚无 OA 链接的结果尝试通过 Unpaywall 补充"""
    if not use_unpaywall:
        return results

    for item in results:
        if item["pdf_status"] == "unknown" and item.get("doi"):
            time.sleep(REQUEST_DELAY)
            oa_url = lookup_unpaywall(item["doi"])
            if oa_url:
                item["open_access_url"] = oa_url
                item["pdf_status"] = "oa_available"
            else:
                item["pdf_status"] = "paywall"

    return results


def main():
    parser = argparse.ArgumentParser(description="学术数据库检索（S2 + OpenAlex + OA）")
    parser.add_argument("--query", "-q", required=True, help="检索关键词")
    parser.add_argument("--limit", "-l", type=int, default=20, help="每个数据库返回条数上限（默认 20）")
    parser.add_argument("--output", "-o", type=str, default=None, help="输出 JSON 文件路径（默认 stdout）")
    parser.add_argument("--no-unpaywall", action="store_true", help="跳过 Unpaywall 查询")
    args = parser.parse_args()

    print(f"[INFO] 检索关键词: {args.query}", file=sys.stderr)
    print(f"[INFO] 每源限制: {args.limit} 条", file=sys.stderr)

    # 并行查询两个数据库
    print("[INFO] 查询 Semantic Scholar...", file=sys.stderr)
    s2_results = search_semantic_scholar(args.query, limit=args.limit)
    print(f"[INFO] Semantic Scholar 返回 {len(s2_results)} 条", file=sys.stderr)

    time.sleep(REQUEST_DELAY)

    print("[INFO] 查询 OpenAlex...", file=sys.stderr)
    oa_results = search_openalex(args.query, limit=args.limit)
    print(f"[INFO] OpenAlex 返回 {len(oa_results)} 条", file=sys.stderr)

    # 去重合并
    merged = deduplicate_and_merge(s2_results, oa_results)
    print(f"[INFO] 去重后共 {len(merged)} 条", file=sys.stderr)

    # Unpaywall 补充 OA 链接
    if not args.no_unpaywall:
        unknown_count = sum(1 for r in merged if r["pdf_status"] == "unknown")
        if unknown_count > 0:
            print(f"[INFO] 对 {unknown_count} 条无 OA 链接的结果查询 Unpaywall...", file=sys.stderr)
            merged = enrich_oa_links(merged, use_unpaywall=True)

    # 按引用量降序排序
    merged.sort(key=lambda x: x.get("citation_count", 0), reverse=True)

    # 标记最终状态
    for item in merged:
        if item["pdf_status"] == "unknown":
            item["pdf_status"] = "paywall"

    # 统计
    oa_count = sum(1 for r in merged if r["pdf_status"] == "oa_available")
    paywall_count = sum(1 for r in merged if r["pdf_status"] == "paywall")
    print(f"\n[SUMMARY] 总计 {len(merged)} 篇 | OA 可下载 {oa_count} 篇 | 付费墙 {paywall_count} 篇",
          file=sys.stderr)

    # 输出
    output_data = {
        "query": args.query,
        "total": len(merged),
        "oa_available": oa_count,
        "paywall": paywall_count,
        "results": merged,
    }

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[INFO] 结果已保存到 {args.output}", file=sys.stderr)
    else:
        print(json.dumps(output_data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
