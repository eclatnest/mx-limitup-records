#!/usr/bin/env python3
"""
Cursor Automation 每日入口：
1. 扫描实时候选（新浪，不用妙想）
2. 周日顺带刷新历史回测
3. 更新 records/README.md
4. 提交并推送到 GitHub
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> None:
    scan_cmd = [sys.executable, str(ROOT / "scan_live.py")]
    if datetime.now().weekday() == 6:
        scan_cmd.append("--full-history")
    run(scan_cmd)

    run(["git", "add", "records/"])
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    if not status.stdout.strip():
        print("no changes to commit")
        return

    msg = f"records: update {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    run(["git", "commit", "-m", msg])
    run(["git", "push", "origin", "HEAD"])


if __name__ == "__main__":
    main()
