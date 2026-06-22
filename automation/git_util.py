#!/usr/bin/env python3
"""Git 提交/推送（Cloud Agent 无全局 user.name 时使用）"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GIT_NAME = os.environ.get("GIT_AUTHOR_NAME", "mx-limitup-bot")
GIT_EMAIL = os.environ.get("GIT_AUTHOR_EMAIL", "mx-limitup-bot@users.noreply.github.com")


def git_base_args() -> list[str]:
    return ["-c", f"user.name={GIT_NAME}", "-c", f"user.email={GIT_EMAIL}"]


def git_push_records(commit_msg: str, paths: str = "records/") -> bool:
    env = {**os.environ, "GIT_AUTHOR_NAME": GIT_NAME, "GIT_AUTHOR_EMAIL": GIT_EMAIL}
    subprocess.run(["git", *git_base_args(), "add", paths], cwd=ROOT, check=False, env=env)
    st = subprocess.run(
        ["git", *git_base_args(), "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    if not st.stdout.strip():
        print("no changes to push")
        return False
    subprocess.run(
        ["git", *git_base_args(), "commit", "-m", commit_msg],
        cwd=ROOT,
        check=True,
        env=env,
    )
    subprocess.run(
        ["git", *git_base_args(), "push", "-u", "origin", "HEAD"],
        cwd=ROOT,
        check=True,
        env=env,
    )
    return True
