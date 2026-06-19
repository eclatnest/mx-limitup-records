#!/usr/bin/env python3
"""扫描当日/最近交易日弱转强候选（仅用新浪K线，不用妙想）"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from limitup_backtest import (
    BACKTEST_DAYS,
    HISTORY_BARS,
    OUTPUT_DIR,
    StrategyParams,
    download_all_klines,
    fetch_stock_universe,
    load_strategy_params,
    run_backtest,
)

OUTPUT = OUTPUT_DIR
RECORDS = Path(__file__).parent / "records"


def scan_today_candidates(params: StrategyParams | None = None) -> tuple[pd.DataFrame, str]:
    """返回回测引擎中最近一个交易日的已筛选信号（与历史回测一致）"""
    params = params or load_strategy_params()
    universe = fetch_stock_universe(600)
    kline_map = download_all_klines(universe, HISTORY_BARS)
    signals, _, _ = run_backtest(kline_map, universe, params, BACKTEST_DAYS)
    if signals.empty:
        return pd.DataFrame(), datetime.now().strftime("%Y-%m-%d")
    last_date = signals["date"].max()
    sig = signals[signals["date"] == last_date].copy()
    return sig, str(last_date.date())


def refresh_history_records() -> dict:
    """全量回测并写入 records/history"""
    from export_daily_detail import main as export_daily
    from export_trades_prices import main as export_trades
    from pnl_report import run_pnl

    params = load_strategy_params()
    universe = fetch_stock_universe(600)
    kline_map = download_all_klines(universe, HISTORY_BARS)
    signals, daily, summary = run_backtest(kline_map, universe, params, BACKTEST_DAYS)

    hist = RECORDS / "history"
    hist.mkdir(parents=True, exist_ok=True)

    if not signals.empty:
        signals.to_csv(hist / "signals_all.csv", index=False, encoding="utf-8-sig")
        daily.to_csv(hist / "daily_stats.csv", index=False, encoding="utf-8-sig")

    run_pnl(OUTPUT / sorted(OUTPUT.glob("signals_*.csv"), key=lambda p: p.stat().st_mtime)[-1])
    try:
        export_daily()
        export_trades()
    except PermissionError as e:
        print(f"warn: export skipped ({e}), use existing latest files")

    # 复制 latest 到 history（固定文件名便于 GitHub 链接）
    import shutil

    mapping = {
        "daily_detail_latest.csv": "daily_detail.csv",
        "trades_prices_latest.csv": "trades_prices.csv",
    }
    for src_name, dst_name in mapping.items():
        src = OUTPUT / src_name
        if src.exists():
            shutil.copy(src, hist / dst_name)

    pnl_files = sorted(OUTPUT.glob("pnl_daily_*.csv"), key=lambda p: p.stat().st_mtime)
    if pnl_files:
        shutil.copy(pnl_files[-1], hist / "pnl_daily.csv")

    summary_path = hist / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    with open(OUTPUT / "best_10y_config_cost.json", encoding="utf-8") as f:
        cfg = json.load(f)
    (hist / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def publish_live(sig: pd.DataFrame, trade_date: str) -> Path:
    live = RECORDS / "live"
    live.mkdir(parents=True, exist_ok=True)
    day_dir = live / trade_date
    day_dir.mkdir(parents=True, exist_ok=True)

    out = day_dir / "candidates.csv"
    if sig.empty:
        pd.DataFrame(columns=["date", "code", "name", "close", "pct_chg", "vol_ratio"]).to_csv(
            out, index=False, encoding="utf-8-sig"
        )
    else:
        cols = [c for c in ["date", "code", "name", "close", "pct_chg", "vol_ratio", "close_high_ratio"] if c in sig.columns]
        sig[cols].to_csv(out, index=False, encoding="utf-8-sig")

    meta = {
        "trade_date": trade_date,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "count": int(len(sig)),
        "codes": sig["code"].astype(str).str.zfill(6).tolist() if not sig.empty else [],
    }
    (day_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # 追加运行日志
    log_path = live / "run_log.csv"
    row = pd.DataFrame([{**meta, "source": "sina_only"}])
    if log_path.exists():
        pd.concat([pd.read_csv(log_path), row], ignore_index=True).to_csv(
            log_path, index=False, encoding="utf-8-sig"
        )
    else:
        row.to_csv(log_path, index=False, encoding="utf-8-sig")

    # latest 指针
    latest = live / "latest_candidates.csv"
    if out.exists():
        import shutil
        shutil.copy(out, latest)
    return out


def update_records_readme(summary: dict | None, live_meta: dict) -> None:
    cfg_path = OUTPUT / "best_10y_config_cost.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}

    lines = [
        "# 弱转强策略 · 历史 & 实时记录",
        "",
        f"> 最后更新：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}（自动化，**不使用妙想**）",
        "",
        "## 实时记录（最近交易日）",
        "",
        f"- **交易日**：{live_meta.get('trade_date', '-')}",
        f"- **候选数量**：{live_meta.get('count', 0)}",
        f"- **代码**：{', '.join(live_meta.get('codes', [])) or '无'}",
        f"- [当日候选 CSV](live/{live_meta.get('trade_date', '')}/candidates.csv)",
        f"- [实时运行日志](live/run_log.csv)",
        f"- [最新候选](live/latest_candidates.csv)",
        "",
        "## 历史回测（含成本）",
        "",
    ]
    if summary:
        lines += [
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 回测区间 | {summary.get('backtest_period', '-')} |",
            f"| 累计收益 | {summary.get('portfolio_cum_return_pct', '-')}% |",
            f"| 最大回撤 | {summary.get('max_drawdown_pct', '-')}% |",
            f"| 交易天数 | {summary.get('trading_days', '-')} |",
            f"| 次日涨停次数 | {summary.get('next_day_limit_up_count', '-')} |",
            "",
            "### 历史数据文件",
            "",
            "- [全量信号](history/signals_all.csv)",
            "- [每日明细](history/daily_detail.csv)",
            "- [逐笔成交价](history/trades_prices.csv)",
            "- [日度PnL](history/pnl_daily.csv)",
            "- [回测摘要](history/summary.json)",
            "- [当前参数](history/config.json)",
            "",
        ]
    else:
        lines.append("_历史回测尚未刷新，见下方 Automation 每周任务_\n")

    lines += [
        "## 策略参数（当前）",
        "",
        f"```json",
        json.dumps({k: cfg.get(k) for k in ["pct_min", "pct_max", "vol_min", "ch_min", "top_n", "rank", "max_c", "min_c", "main_board"]}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 说明",
        "",
        "- 数据源：新浪日K（`limitup_backtest.py`），**不调用妙想 skills**",
        "- 买入假设：T 日收盘价；卖出：T+1 收盘价",
        "- 实时扫描：每个交易日收盘后运行，写入 `records/live/`",
    ]
    (RECORDS / "README.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--full-history", action="store_true", help="刷新历史回测到 records/history")
    args = parser.parse_args()

    summary = None
    if args.full_history:
        print("refresh history...")
        summary = refresh_history_records()

    sig, td = scan_today_candidates()
    meta_path = publish_live(sig, td)
    meta = json.loads((RECORDS / "live" / td / "meta.json").read_text(encoding="utf-8"))
    if summary is None and (RECORDS / "history" / "summary.json").exists():
        summary = json.loads((RECORDS / "history" / "summary.json").read_text(encoding="utf-8"))
    update_records_readme(summary, meta)
    print(f"live -> {meta_path}")
    print(f"readme -> {RECORDS / 'README.md'}")
