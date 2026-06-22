#!/usr/bin/env python3
"""更新 records/README.md 看板并 push 到 GitHub"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "records" / "live" / "trade_state.json"
CONFIG_PATH = ROOT / "records" / "live" / "strategy_config.json"
README_PATH = ROOT / "records" / "README.md"
EQUITY_CSV = ROOT / "records" / "live" / "equity_daily.csv"


def load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def latest_equity() -> tuple[float | None, float | None]:
    if not EQUITY_CSV.exists():
        return None, None
    lines = EQUITY_CSV.read_text(encoding="utf-8").strip().splitlines()
    if len(lines) < 2:
        return None, None
    last = lines[-1].split(",")
    try:
        equity = float(last[3])
        daily_ret = float(last[5])
        return equity, daily_ret
    except (IndexError, ValueError):
        return None, None


def build_readme() -> str:
    state = load_json(STATE_PATH)
    cfg = load_json(CONFIG_PATH)
    equity, daily_ret = latest_equity()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    picks = []
    if state.get("last_select") and state["last_select"].get("picks"):
        picks = state["last_select"]["picks"]
        sel_time = state["last_select"].get("time", "")[:10]
    else:
        sel_time = "-"

    pending = state.get("pending_sells") or []
    codes = ", ".join(p["code"] for p in picks) if picks else "-"
    pending_codes = ", ".join(f"{p['code']}({p.get('qty',0)}股)" for p in pending) if pending else "无"

    eq_line = f"**{equity/1e4:.2f}万**" if equity else "待首笔交易"
    ret_line = f"{daily_ret:+.2f}%" if daily_ret is not None else "-"
    cum_ret = f"{(equity / state.get('equity_start', 1_000_000) - 1) * 100:+.2f}%" if equity else "-"

    return f"""# 弱转强策略 · 妙想模拟盘 & 历史回测

> 最后更新：{now}（Automation 自动推送）

## 妙想模拟盘（实时）

| 项目 | 状态 |
|------|------|
| 时间线 | 14:45选股 → 14:57全仓买 → 次日14:57卖 |
| 资金模式 | 日复利全仓（账户总资产滚仓） |
| 账户权益 | {eq_line} |
| 累计收益 | {cum_ret} |
| 最近日收益 | {ret_line} |
| 最近选股日 | {sel_time} |
| 今日候选 | {codes} |
| 待次日卖出 | {pending_codes} |
| 已初始化清仓 | {state.get('initialized', False)} |

### 实时文件

- [策略参数](live/strategy_config.json)
- [交易状态](live/trade_state.json)
- [权益曲线 CSV](live/equity_daily.csv)
- [最新候选](live/latest_candidates.csv)

## 历史回测（新浪日K · 含成本）

| 指标 | 数值 |
|------|------|
| 回测区间 | 2016-06-22 ~ 2026-06-15 |
| 收盘回测累计 | 1850.64% |
| 妙想时间线回测 | 见本地 backtest（固定本金约 +640%） |
| 最大回撤 | -23.64% |

- [全量信号](history/signals_all.csv)
- [逐笔成交价](history/trades_prices.csv)
- [日度PnL](history/pnl_daily.csv)
- [回测摘要](history/summary.json)

## 当前妙想策略参数

```json
{json.dumps(cfg, ensure_ascii=False, indent=2)}
```

## Automation 说明

| 时间 | Automation | 动作 |
|------|------------|------|
| 14:45 | 弱转强-妙想14:45选股 | mx-xuangu 选股 |
| 14:57 | 弱转强-妙想14:57买卖 | 卖出→买入 |
| **15:10** | **弱转强-交易记录推GitHub** | **更新本页并 push** |
"""


def main() -> int:
    README_PATH.write_text(build_readme(), encoding="utf-8")
    print(f"updated {README_PATH}")
    try:
        from git_util import git_push_records

        if git_push_records(f"records: mx dashboard {datetime.now().strftime('%Y-%m-%d %H:%M')}"):
            print("pushed to GitHub")
    except subprocess.CalledProcessError as e:
        print(f"git push failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
