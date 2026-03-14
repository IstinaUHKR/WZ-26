#!/usr/bin/env python
"""
cleanup_workspace.py - 清空 workspace/ 临时文件

功能：
- 清空 workspace/papers/ 和 workspace/web_cache/
- 删除 workspace/acquired.json, pending_manual.json, web_session.json
- 在报告终稿完成后调用

用法：
  python cleanup_workspace.py --workspace ./workspace
  python cleanup_workspace.py --workspace ./workspace --dry-run
"""

import argparse
import io
import shutil
import sys
from pathlib import Path

# Windows 终端 GBK 编码兼容：强制 stdout/stderr 使用 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def cleanup(workspace: Path, dry_run: bool = False):
    """清空 workspace 临时文件"""
    if not workspace.exists():
        print(f"[INFO] workspace 不存在，无需清理: {workspace}", file=sys.stderr)
        return

    # 要清空的子目录
    dirs_to_clean = ["papers", "web_cache"]
    # 要删除的文件
    files_to_delete = ["acquired.json", "pending_manual.json", "web_session.json"]

    total_files = 0
    total_size = 0

    # 清空子目录内容（保留目录本身）
    for dirname in dirs_to_clean:
        dirpath = workspace / dirname
        if dirpath.exists():
            for item in dirpath.iterdir():
                size = item.stat().st_size if item.is_file() else 0
                total_files += 1
                total_size += size
                if dry_run:
                    print(f"  [DRY] 删除: {item}", file=sys.stderr)
                else:
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)

    # 删除 JSON 文件
    for filename in files_to_delete:
        filepath = workspace / filename
        if filepath.exists():
            size = filepath.stat().st_size
            total_files += 1
            total_size += size
            if dry_run:
                print(f"  [DRY] 删除: {filepath}", file=sys.stderr)
            else:
                filepath.unlink()

    size_mb = total_size / (1024 * 1024)
    action = "将删除" if dry_run else "已删除"
    print(f"[DONE] {action} {total_files} 个文件（{size_mb:.2f} MB）", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="清空 workspace 临时文件")
    parser.add_argument("--workspace", "-w", type=str, default=None,
                        help="workspace 目录路径（默认: 脚本所在项目的 workspace/）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际删除")
    args = parser.parse_args()

    if args.workspace:
        ws = Path(args.workspace)
    else:
        ws = Path(__file__).resolve().parent.parent.parent / "workspace"

    print(f"[INFO] 清理目标: {ws}", file=sys.stderr)
    cleanup(ws, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
