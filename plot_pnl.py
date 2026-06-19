#!/usr/bin/env python3
"""生成 PnL 可视化图表"""

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

OUTPUT = Path(__file__).parent / "output"
INITIAL = 1_000_000

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def latest(pattern: str) -> Path:
    files = sorted(OUTPUT.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def main():
    daily = pd.read_csv(latest("pnl_daily_*.csv"), parse_dates=["日期"])
    monthly = pd.read_csv(latest("pnl_monthly_*.csv"))

    daily = daily.sort_values("日期")
    daily["peak"] = daily["权益(元)"].cummax()
    daily["drawdown_pct"] = (daily["权益(元)"] / daily["peak"] - 1) * 100

    fig = plt.figure(figsize=(14, 10), facecolor="#0f1117")
    gs = fig.add_gridspec(3, 1, height_ratios=[2.2, 1, 1.2], hspace=0.28)

    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax3 = fig.add_subplot(gs[2])

    for ax in (ax1, ax2, ax3):
        ax.set_facecolor("#161b22")
        ax.tick_params(colors="#c9d1d9")
        for spine in ax.spines.values():
            spine.set_color("#30363d")

    # 权益曲线
    ax1.plot(daily["日期"], daily["权益(元)"], color="#58a6ff", linewidth=1.8, label="权益")
    ax1.axhline(INITIAL, color="#8b949e", linestyle="--", linewidth=1, alpha=0.7, label="初始 100万")
    ax1.fill_between(daily["日期"], INITIAL, daily["权益(元)"], where=daily["权益(元)"] >= INITIAL, alpha=0.15, color="#3fb950")
    ax1.fill_between(daily["日期"], INITIAL, daily["权益(元)"], where=daily["权益(元)"] < INITIAL, alpha=0.15, color="#f85149")
    final = daily["权益(元)"].iloc[-1]
    ret = daily["累计收益率%"].iloc[-1]
    ax1.set_title(
        f"弱转强策略 · 10年 PnL（含成本）  |  期末 {final/1e4:.1f}万  |  累计 {ret:+.1f}%",
        color="#f0f6fc", fontsize=14, pad=12,
    )
    ax1.set_ylabel("权益 (元)", color="#c9d1d9")
    ax1.legend(loc="upper left", framealpha=0.2, facecolor="#161b22", edgecolor="#30363d", labelcolor="#c9d1d9")
    ax1.grid(True, alpha=0.15, color="#484f58")

    # 回撤
    ax2.fill_between(daily["日期"], daily["drawdown_pct"], 0, color="#f85149", alpha=0.5)
    ax2.plot(daily["日期"], daily["drawdown_pct"], color="#f85149", linewidth=1)
    mdd = daily["drawdown_pct"].min()
    ax2.set_ylabel("回撤 (%)", color="#c9d1d9")
    ax2.set_title(f"最大回撤 {mdd:.1f}%", color="#f0f6fc", fontsize=11, loc="left")
    ax2.grid(True, alpha=0.15, color="#484f58")

    # 月度 PnL
    colors = ["#3fb950" if x >= 0 else "#f85149" for x in monthly["月PnL(元)"]]
    ax3.bar(range(len(monthly)), monthly["月PnL(元)"] / 10000, color=colors, width=0.85)
    ax3.axhline(0, color="#8b949e", linewidth=0.8)
    step = max(len(monthly) // 12, 1)
    ticks = list(range(0, len(monthly), step))
    ax3.set_xticks(ticks)
    ax3.set_xticklabels([monthly["月份"].iloc[i] for i in ticks], rotation=45, ha="right", fontsize=8, color="#c9d1d9")
    ax3.set_ylabel("月 PnL (万元)", color="#c9d1d9")
    ax3.set_title("月度 PnL", color="#f0f6fc", fontsize=11, loc="left")
    ax3.grid(True, axis="y", alpha=0.15, color="#484f58")

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax2.xaxis.set_major_locator(mdates.YearLocator())
    plt.setp(ax2.get_xticklabels(), rotation=30, ha="right", color="#c9d1d9")

    out = OUTPUT / "pnl_chart_10y_cost.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(out)
    plt.close()


if __name__ == "__main__":
    main()
