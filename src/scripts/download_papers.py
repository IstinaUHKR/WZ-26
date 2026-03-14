#!/usr/bin/env python
"""
download_papers.py - OA 全文下载到 workspace/papers/

功能：
- 输入 search_academic.py 的 JSON 结果
- OA 可用 → 下载 PDF 到 workspace/papers/<doi_hash>.pdf
- 付费墙 → 仅记录元数据，标记 paywall
- 输出：
  - workspace/acquired.json — 已下载清单
  - workspace/pending_manual.json — 待手动下载清单

用法：
  python download_papers.py --input results.json
  python download_papers.py --input results.json --workspace ./workspace
"""

import argparse
import hashlib
import io
import json
import sys
import time
from pathlib import Path

# Windows 终端 GBK 编码兼容：强制 stdout/stderr 使用 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import requests

REQUEST_DELAY = 1.5  # 下载间隔
DOWNLOAD_TIMEOUT = 60  # 单个文件下载超时


def doi_to_filename(doi: str) -> str:
    """将 DOI 转为安全的文件名"""
    if not doi:
        return ""
    h = hashlib.md5(doi.lower().encode()).hexdigest()[:12]
    safe = doi.replace("/", "_").replace(":", "_")[:60]
    return f"{safe}_{h}.pdf"


def download_pdf(url: str, dest: Path) -> bool:
    """下载 PDF 到指定路径，返回是否成功"""
    try:
        headers = {
            "User-Agent": "WZ26-DeepResearch/1.0 (Academic Research Tool)",
            "Accept": "application/pdf,*/*",
        }
        resp = requests.get(url, headers=headers, timeout=DOWNLOAD_TIMEOUT,
                            stream=True, allow_redirects=True)
        resp.raise_for_status()

        # 检查是否真的是 PDF
        content_type = resp.headers.get("Content-Type", "")
        first_bytes = b""
        total = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if not first_bytes:
                    first_bytes = chunk[:5]
                f.write(chunk)
                total += len(chunk)

        # 验证 PDF 头部
        if first_bytes[:4] != b"%PDF":
            print(f"  [WARN] 非 PDF 文件（Content-Type: {content_type}），已删除", file=sys.stderr)
            dest.unlink(missing_ok=True)
            return False

        size_mb = total / (1024 * 1024)
        print(f"  [OK] 下载成功: {dest.name} ({size_mb:.1f} MB)", file=sys.stderr)
        return True

    except requests.RequestException as e:
        print(f"  [FAIL] 下载失败: {e}", file=sys.stderr)
        dest.unlink(missing_ok=True)
        return False


def main():
    parser = argparse.ArgumentParser(description="OA 全文下载到 workspace/papers/")
    parser.add_argument("--input", "-i", required=True, help="search_academic.py 输出的 JSON 文件")
    parser.add_argument("--workspace", "-w", type=str, default=None,
                        help="workspace 目录路径（默认: 脚本所在项目的 workspace/）")
    args = parser.parse_args()

    # 读取检索结果
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] 文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(input_path.read_text(encoding="utf-8"))
    results = data.get("results", [])

    if not results:
        print("[INFO] 无检索结果，退出", file=sys.stderr)
        sys.exit(0)

    # 确定 workspace 路径
    if args.workspace:
        ws = Path(args.workspace)
    else:
        # 默认：脚本所在目录的 ../../workspace/
        ws = Path(__file__).resolve().parent.parent.parent / "workspace"

    papers_dir = ws / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    # 加载已有的 acquired.json（增量下载）
    acquired_path = ws / "acquired.json"
    if acquired_path.exists():
        acquired = json.loads(acquired_path.read_text(encoding="utf-8"))
    else:
        acquired = {"papers": []}

    existing_dois = {p.get("doi", "").lower() for p in acquired["papers"] if p.get("doi")}

    # 分类处理
    downloaded = []
    pending = []
    skipped = 0

    for item in results:
        doi = item.get("doi", "")
        if doi and doi.lower() in existing_dois:
            skipped += 1
            continue

        if item.get("pdf_status") == "oa_available" and item.get("open_access_url"):
            # 尝试下载
            filename = doi_to_filename(doi) if doi else f"no_doi_{hashlib.md5(item['title'].encode()).hexdigest()[:12]}.pdf"
            dest = papers_dir / filename

            print(f"[DOWNLOAD] {item['title'][:60]}...", file=sys.stderr)
            time.sleep(REQUEST_DELAY)

            if download_pdf(item["open_access_url"], dest):
                entry = {
                    "doi": doi,
                    "title": item["title"],
                    "authors": item["authors"],
                    "year": item["year"],
                    "venue": item["venue"],
                    "citation_count": item["citation_count"],
                    "local_path": str(dest.resolve()),  # 绝对路径，跨目录调用时可直接使用
                    "source_url": item["open_access_url"],
                    "status": "downloaded",
                }
                downloaded.append(entry)
                acquired["papers"].append(entry)
            else:
                # 下载失败，归入待手动列表
                pending.append({
                    "doi": doi,
                    "title": item["title"],
                    "authors": item["authors"],
                    "year": item["year"],
                    "venue": item["venue"],
                    "citation_count": item["citation_count"],
                    "reason": "download_failed",
                    "attempted_url": item["open_access_url"],
                })
        else:
            # 付费墙
            pending.append({
                "doi": doi,
                "title": item["title"],
                "authors": item["authors"],
                "year": item["year"],
                "venue": item["venue"],
                "citation_count": item["citation_count"],
                "reason": "paywall",
            })

    # 保存 acquired.json
    acquired_path.write_text(json.dumps(acquired, ensure_ascii=False, indent=2), encoding="utf-8")

    # 保存 pending_manual.json
    pending_path = ws / "pending_manual.json"
    pending_data = {
        "query": data.get("query", ""),
        "total_pending": len(pending),
        "papers": pending,
    }
    pending_path.write_text(json.dumps(pending_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 输出统计
    print(f"\n[SUMMARY]", file=sys.stderr)
    print(f"  新下载: {len(downloaded)} 篇", file=sys.stderr)
    print(f"  待手动: {len(pending)} 篇（付费墙/下载失败）", file=sys.stderr)
    print(f"  已跳过: {skipped} 篇（之前已下载）", file=sys.stderr)
    print(f"  acquired.json: {acquired_path}", file=sys.stderr)
    print(f"  pending_manual.json: {pending_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
