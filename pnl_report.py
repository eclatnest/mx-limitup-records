#!/usr/bin/env python3
"""从回测信号生成 PnL 报告"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

OUTPUT_DIR = Path(__file__).parent / "output"
INITIAL_CAPITAL = 1_000_000  # 初始资金 100万
COST_NOTE = "含佣金万2.5双向+印花税万5(卖)+滑点买0.10%/卖0.10%(涨停卖0.03%)"


def latest_file(pattern: str) -> Path:
    files = sorted(OUTPUT_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"未找到 {pattern}")
    return files[0]


def max_drawdown(equity: pd.Series, dates: pd.Series) -> tuple[float, str, str]:
    peak = equity.cummax()
    dd = (equity - peak) / peak
    idx = dd.idxmin()
    peak_idx = equity.loc[:idx].idxmax() if idx is not None else idx
    return (
        float(dd.min() * 100),
        str(dates.loc[idx].date()) if idx is not None else "",
        str(dates.loc[peak_idx].date()) if peak_idx is not None else "",
    )


def run_pnl(signals_path: Path | None = None) -> Path:
    sig_path = signals_path or latest_file("signals_*.csv")
    signals = pd.read_csv(sig_path, parse_dates=["date"])
    signals["next_limit_up"] = signals["next_limit_up"].map(
        lambda x: str(x).lower() in ("true", "1", "yes")
    )

    daily = (
        signals.groupby("date")
        .agg(
            n=("code", "count"),
            daily_ret_pct=("ret_t1", "mean"),
            limit_up_hits=("next_limit_up", "sum"),
        )
        .reset_index()
        .sort_values("date")
    )

    daily["daily_pnl"] = INITIAL_CAPITAL * daily["daily_ret_pct"] / 100
    # 复利权益曲线（每日等权全仓滚动）
    daily["equity"] = INITIAL_CAPITAL * (1 + daily["daily_ret_pct"] / 100).cumprod()
    daily["cum_pnl"] = daily["equity"] - INITIAL_CAPITAL
    daily["cum_ret_pct"] = (daily["equity"] / INITIAL_CAPITAL - 1) * 100

    # 按自然月
    daily["month"] = daily["date"].dt.to_period("M").astype(str)
    monthly = (
        daily.groupby("month")
        .agg(
            trading_days=("date", "count"),
            signals=("n", "sum"),
            month_ret_pct=("daily_ret_pct", lambda s: ((1 + s / 100).prod() - 1) * 100),
            limit_up_hits=("limit_up_hits", "sum"),
        )
        .reset_index()
    )
    monthly["month_pnl"] = INITIAL_CAPITAL * monthly["month_ret_pct"] / 100

    # 单笔交易 PnL（假设每笔均分当日仓位）
    signals = signals.sort_values(["date", "code"]).reset_index(drop=True)
    signals["weight"] = signals.groupby("date")["code"].transform(lambda x: 1.0 / len(x))
    signals["trade_pnl"] = INITIAL_CAPITAL * signals["weight"] * signals["ret_t1"] / 100

    gross_profit = signals.loc[signals["trade_pnl"] > 0, "trade_pnl"].sum()
    gross_loss = abs(signals.loc[signals["trade_pnl"] < 0, "trade_pnl"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    mdd_pct, mdd_date, mdd_peak_date = max_drawdown(daily["equity"], daily["date"])

    best_day = daily.loc[daily["daily_pnl"].idxmax()]
    worst_day = daily.loc[daily["daily_pnl"].idxmin()]
    best_trade = signals.loc[signals["trade_pnl"].idxmax()]
    worst_trade = signals.loc[signals["trade_pnl"].idxmin()]

    final_equity = float(daily["equity"].iloc[-1])
    total_pnl = final_equity - INITIAL_CAPITAL
    total_ret = total_pnl / INITIAL_CAPITAL * 100

    # 涨停 vs 非涨停 单笔贡献
    lu_pnl = signals.loc[signals["next_limit_up"], "trade_pnl"].sum()
    non_lu_pnl = signals.loc[~signals["next_limit_up"], "trade_pnl"].sum()

    summary = {
        "initial_capital": INITIAL_CAPITAL,
        "final_equity": round(final_equity, 2),
        "total_pnl": round(total_pnl, 2),
        "total_return_pct": round(total_ret, 2),
        "max_drawdown_pct": round(mdd_pct, 2),
        "max_drawdown_date": mdd_date,
        "profit_factor": round(profit_factor, 3),
        "total_trades": len(signals),
        "win_trades": int((signals["trade_pnl"] > 0).sum()),
        "loss_trades": int((signals["trade_pnl"] < 0).sum()),
        "limit_up_pnl": round(float(lu_pnl), 2),
        "non_limit_up_pnl": round(float(non_lu_pnl), 2),
        "avg_trade_pnl": round(float(signals["trade_pnl"].mean()), 2),
        "best_trade": {
            "date": str(best_trade["date"].date()),
            "code": str(best_trade["code"]),
            "name": str(best_trade["name"]),
            "pnl": round(float(best_trade["trade_pnl"]), 2),
            "ret_pct": round(float(best_trade["ret_t1"]), 2),
        },
        "worst_trade": {
            "date": str(worst_trade["date"].date()),
            "code": str(worst_trade["code"]),
            "name": str(worst_trade["name"]),
            "pnl": round(float(worst_trade["trade_pnl"]), 2),
            "ret_pct": round(float(worst_trade["ret_t1"]), 2),
        },
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    daily_path = OUTPUT_DIR / f"pnl_daily_{ts}.csv"
    monthly_path = OUTPUT_DIR / f"pnl_monthly_{ts}.csv"
    trades_path = OUTPUT_DIR / f"pnl_trades_{ts}.csv"
    summary_path = OUTPUT_DIR / f"pnl_summary_{ts}.json"
    report_path = OUTPUT_DIR / f"pnl_report_{ts}.md"

    daily_out = daily[
        ["date", "n", "limit_up_hits", "daily_ret_pct", "daily_pnl", "equity", "cum_pnl", "cum_ret_pct"]
    ].copy()
    daily_out.columns = [
        "日期", "信号数", "涨停数", "日收益率%", "日PnL(元)", "权益(元)", "累计PnL(元)", "累计收益率%",
    ]
    daily_out.to_csv(daily_path, index=False, encoding="utf-8-sig")

    monthly_out = monthly.copy()
    monthly_out.columns = ["月份", "交易日", "信号数", "月收益率%", "涨停数", "月PnL(元)"]
    monthly_out.to_csv(monthly_path, index=False, encoding="utf-8-sig")

    trades_out = signals[
        ["date", "code", "name", "ret_t1_gross", "ret_t1", "next_limit_up", "weight", "trade_pnl"]
    ].copy() if "ret_t1_gross" in signals.columns else signals[
        ["date", "code", "name", "ret_t1", "next_limit_up", "weight", "trade_pnl"]
    ].copy()
    if "ret_t1_gross" in trades_out.columns:
        trades_out.columns = ["买入日", "代码", "名称", "T+1毛收益%", "T+1净收益%", "次日涨停", "仓位权重", "单笔PnL(元)"]
    else:
        trades_out.columns = ["买入日", "代码", "名称", "T+1收益率%", "次日涨停", "仓位权重", "单笔PnL(元)"]
    trades_out.to_csv(trades_path, index=False, encoding="utf-8-sig")

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # ASCII 权益曲线（20 格）
    eq = daily["cum_ret_pct"].values
    mn, mx = eq.min(), eq.max()
    span = mx - mn if mx != mn else 1
    spark = []
    step = max(len(eq) // 20, 1)
    for v in eq[::step][:20]:
        bar = int((v - mn) / span * 15)
        spark.append("█" * max(bar, 0) + "░" * (15 - max(bar, 0)) + f" {v:+.1f}%")

    lines = [
        "# PnL 报告 · 弱转强次日涨停策略（含手续费/滑点）",
        "",
        f"**假设**：初始资金 {INITIAL_CAPITAL:,} 元，T 日收盘等权买入当日全部信号，T+1 收盘卖出，复利滚动。",
        f"**成本**：{COST_NOTE}。",
        "",
        "## 总览",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 初始资金 | {INITIAL_CAPITAL:,} 元 |",
        f"| 期末权益 | **{summary['final_equity']:,.2f} 元** |",
        f"| **总 PnL** | **{summary['total_pnl']:+,.2f} 元** |",
        f"| **总收益率** | **{summary['total_return_pct']:+.2f}%** |",
        f"| 最大回撤 | {summary['max_drawdown_pct']:.2f}%（谷底 {summary['max_drawdown_date']}） |",
        f"| 盈亏比 (Profit Factor) | {summary['profit_factor']:.3f} |",
        f"| 交易笔数 | {summary['total_trades']}（胜 {summary['win_trades']} / 负 {summary['loss_trades']}） |",
        f"| 单笔均 PnL | {summary['avg_trade_pnl']:+,.2f} 元 |",
        "",
        "## PnL 分解",
        "",
        "| 来源 | 贡献 PnL |",
        "|------|----------|",
        f"| 次日涨停成交 | **{summary['limit_up_pnl']:+,.2f} 元** |",
        f"| 未涨停成交 | {summary['non_limit_up_pnl']:+,.2f} 元 |",
        "",
        "## 月度 PnL",
        "",
        "| 月份 | 交易日 | 信号 | 涨停 | 月收益率 | 月 PnL |",
        "|------|--------|------|------|----------|--------|",
    ]
    for _, r in monthly.iterrows():
        lines.append(
            f"| {r['month']} | {int(r['trading_days'])} | {int(r['signals'])} | {int(r['limit_up_hits'])} | {r['month_ret_pct']:+.2f}% | {r['month_pnl']:+,.0f} 元 |"
        )

    lines.extend(
        [
            "",
            "## 极值",
            "",
            f"- **最佳交易日** {best_day['date'].date()}：{best_day['daily_pnl']:+,.0f} 元（{best_day['daily_ret_pct']:+.2f}%）",
            f"- **最差交易日** {worst_day['date'].date()}：{worst_day['daily_pnl']:+,.0f} 元（{worst_day['daily_ret_pct']:+.2f}%）",
            f"- **最佳单笔** {summary['best_trade']['date']} {summary['best_trade']['code']} {summary['best_trade']['name']}：{summary['best_trade']['pnl']:+,.0f} 元",
            f"- **最差单笔** {summary['worst_trade']['date']} {summary['worst_trade']['code']} {summary['worst_trade']['name']}：{summary['worst_trade']['pnl']:+,.0f} 元",
            "",
            "## 累计收益曲线（ASCII）",
            "",
            "```",
            *spark,
            "```",
            "",
            f"- 日度 PnL: `{daily_path.name}`",
            f"- 月度 PnL: `{monthly_path.name}`",
            f"- 逐笔 PnL: `{trades_path.name}`",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"总 PnL: {summary['total_pnl']:+,.2f} 元 ({summary['total_return_pct']:+.2f}%)")
    print(f"最大回撤: {summary['max_drawdown_pct']:.2f}%")
    print(f"报告: {report_path}")
    return report_path


if __name__ == "__main__":
    run_pnl()
