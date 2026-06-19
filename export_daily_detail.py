#!/usr/bin/env python3
"""导出每日综合明细 CSV（PnL + 持仓 + 回撤）"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

OUTPUT_DIR = Path(__file__).parent / "output"
INITIAL = 1_000_000


def latest(pattern: str) -> Path:
    files = sorted(OUTPUT_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(pattern)
    return files[0]


def fmt_pick(row: pd.Series) -> str:
    lu = "涨停" if row["next_limit_up"] else ""
    code = str(row["code"]).zfill(6)
    return f"{code} {row['name']} {row['ret_t1']:+.2f}%{lu}"


def main() -> Path:
    sig = pd.read_csv(latest("signals_*.csv"), parse_dates=["date"])
    sig["next_limit_up"] = sig["next_limit_up"].map(lambda x: str(x).lower() in ("true", "1", "yes"))
    sig = sig.sort_values(["date", "code"]).reset_index(drop=True)
    sig["weight"] = sig.groupby("date")["code"].transform(lambda x: 1.0 / len(x))
    sig["trade_pnl"] = INITIAL * sig["weight"] * sig["ret_t1"] / 100

    rows = []
    for date, g in sig.groupby("date", sort=True):
        daily_ret = g["ret_t1"].mean()
        rows.append(
            {
                "date": date,
                "n": len(g),
                "limit_up_hits": int(g["next_limit_up"].sum()),
                "win_trades": int((g["ret_t1"] > 0).sum()),
                "loss_trades": int((g["ret_t1"] <= 0).sum()),
                "avg_ret_t1_pct": daily_ret,
                "avg_pct_chg_t": g["pct_chg"].mean(),
                "avg_vol_ratio": g["vol_ratio"].mean(),
                "picks": " | ".join(fmt_pick(r) for _, r in g.iterrows()),
                "codes": ",".join(g["code"].astype(str).str.zfill(6)),
                "names": ",".join(g["name"].astype(str)),
            }
        )

    daily = pd.DataFrame(rows).sort_values("date")
    daily["equity"] = INITIAL * (1 + daily["avg_ret_t1_pct"] / 100).cumprod()
    daily["daily_pnl"] = daily["equity"].diff().fillna(daily["equity"].iloc[0] - INITIAL)
    daily["cum_ret_pct"] = (daily["equity"] / INITIAL - 1) * 100
    daily["cum_pnl"] = daily["equity"] - INITIAL
    peak = daily["equity"].cummax()
    daily["drawdown_pct"] = (daily["equity"] / peak - 1) * 100
    daily["profitable_day"] = daily["daily_pnl"] > 0

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUTPUT_DIR / f"daily_detail_{ts}.csv"
    latest_link = OUTPUT_DIR / "daily_detail_latest.csv"

    out_df = daily[
        [
            "date",
            "n",
            "limit_up_hits",
            "win_trades",
            "loss_trades",
            "avg_ret_t1_pct",
            "avg_pct_chg_t",
            "avg_vol_ratio",
            "daily_pnl",
            "equity",
            "cum_pnl",
            "cum_ret_pct",
            "drawdown_pct",
            "profitable_day",
            "codes",
            "names",
            "picks",
        ]
    ].copy()
    out_df.columns = [
        "日期",
        "信号数",
        "涨停数",
        "盈利笔数",
        "亏损笔数",
        "日收益率%",
        "T日平均涨幅%",
        "T日平均量比",
        "日PnL(元)",
        "权益(元)",
        "累计PnL(元)",
        "累计收益率%",
        "回撤%",
        "是否盈利日",
        "代码",
        "名称",
        "持仓明细",
    ]
    out_df.to_csv(out, index=False, encoding="utf-8-sig", float_format="%.4f")
    out_df.to_csv(latest_link, index=False, encoding="utf-8-sig", float_format="%.4f")

    print(f"rows={len(out_df)}")
    print(f"saved {out}")
    print(f"saved {latest_link}")
    return out


if __name__ == "__main__":
    main()
