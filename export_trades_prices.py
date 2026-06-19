#!/usr/bin/env python3
"""导出逐笔成交价明细 + 实盘可买性评估"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from limitup_backtest import (
    CACHE_DIR,
    COMMISSION_RATE,
    HISTORY_BARS,
    SLIPPAGE_BUY,
    SLIPPAGE_SELL,
    SLIPPAGE_SELL_LIMIT_UP,
    STAMP_TAX_RATE,
    limit_up_threshold,
)

OUTPUT = Path(__file__).parent / "output"
INITIAL = 1_000_000


def latest(pattern: str) -> Path:
    files = sorted(OUTPUT.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(pattern)
    return files[0]


def load_code_dates(code: str) -> pd.DataFrame | None:
    code = str(code).zfill(6)
    for name in (f"sin_{code}_{HISTORY_BARS}.csv", f"sin_{code}_2000.csv"):
        p = CACHE_DIR / name
        if p.exists():
            df = pd.read_csv(p, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
            return df
    return None


def next_trade_date(cache: dict[str, pd.DataFrame], code: str, buy_date: pd.Timestamp) -> pd.Timestamp | None:
    code = str(code).zfill(6)
    if code not in cache:
        df = load_code_dates(code)
        if df is None:
            return None
        cache[code] = df
    df = cache[code]
    hit = df.index[df["date"] == buy_date]
    if len(hit) == 0:
        return None
    i = int(hit[0])
    if i + 1 >= len(df):
        return None
    return pd.Timestamp(df.iloc[i + 1]["date"])


def assess_fill_risk(row: pd.Series) -> tuple[str, str]:
    """返回 (可买性等级, 说明)"""
    code = str(row["code"]).zfill(6)
    th = limit_up_threshold(code, str(row["name"]))
    pct = float(row["pct_chg"])
    ch = float(row["close_high_ratio"])
    vol = float(row["vol_ratio"])

    if pct >= th - 0.3:
        return "高", "接近涨停价收盘，集合竞价易排队失败或成交价劣于收盘价"
    if pct >= 7.0 and ch >= 0.99:
        return "高", "冲板形态，收盘抢筹竞争激烈"
    if vol >= 3.5:
        return "中", "异常放量，收盘流动性波动大，滑点可能超回测假设"
    if pct >= 6.0:
        return "中", "涨幅偏大，收盘买单多，存在未完全成交风险"
    if ch >= 1.0 and pct >= 5.0:
        return "低", "收在最高价附近且未涨停，一般可挂收盘价附近成交"
    return "低", "常规弱转强区间，正常流动性下大概率可成交"


def main() -> Path:
    sig = pd.read_csv(latest("signals_*.csv"), parse_dates=["date"])
    sig["code"] = sig["code"].astype(str).str.zfill(6)
    sig["next_limit_up"] = sig["next_limit_up"].map(lambda x: str(x).lower() in ("true", "1", "yes"))

    cache: dict[str, pd.DataFrame] = {}
    rows = []
    for _, r in sig.iterrows():
        sell_slip = SLIPPAGE_SELL_LIMIT_UP if r["next_limit_up"] else SLIPPAGE_SELL
        close = float(r["close"])
        gross = float(r["ret_t1_gross"])
        next_close = close * (1 + gross / 100)

        buy_slip_price = close * (1 + SLIPPAGE_BUY)
        buy_all_in = buy_slip_price * (1 + COMMISSION_RATE)
        sell_slip_price = next_close * (1 - sell_slip)
        sell_net_per_share = sell_slip_price * (1 - COMMISSION_RATE - STAMP_TAX_RATE)

        implied_ret = (sell_net_per_share / buy_all_in - 1) * 100
        sell_date = next_trade_date(cache, r["code"], r["date"])
        risk, note = assess_fill_risk(r)

        rows.append(
            {
                "买入日": r["date"].date(),
                "卖出日": sell_date.date() if sell_date is not None else "",
                "买入时段": "T日收盘(约14:57-15:00集合竞价/收盘价)",
                "卖出时段": "T+1日收盘(约14:57-15:00集合竞价/收盘价)",
                "代码": r["code"],
                "名称": r["name"],
                "T日涨幅%": round(r["pct_chg"], 4),
                "T日量比": round(r["vol_ratio"], 4),
                "收盘/最高": round(r["close_high_ratio"], 4),
                "收盘价买入价_元": round(close, 4),
                "含滑点买入价_元": round(buy_slip_price, 4),
                "含滑点佣金买入成本_元": round(buy_all_in, 4),
                "T+1收盘价_元": round(next_close, 4),
                "含滑点卖出价_元": round(sell_slip_price, 4),
                "含滑点佣金印花税卖出净价_元": round(sell_net_per_share, 4),
                "T+1毛收益%": round(gross, 4),
                "T+1净收益%_回测": round(float(r["ret_t1"]), 4),
                "T+1净收益%_由价格推算": round(implied_ret, 4),
                "次日涨停": r["next_limit_up"],
                "实盘可买性": risk,
                "买不到/滑点风险说明": note,
                "回测成交假设": "按收盘价100%成交；未模拟排队失败",
            }
        )

    out_df = pd.DataFrame(rows)
    out_df["仓位权重"] = out_df.groupby("买入日")["代码"].transform(lambda x: round(1.0 / len(x), 4))
    out_df["单笔PnL_元_100万本金"] = (
        INITIAL * out_df["仓位权重"] * out_df["T+1净收益%_回测"] / 100
    ).round(2)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT / f"trades_prices_{ts}.csv"
    latest_path = OUTPUT / "trades_prices_latest.csv"
    out_df.to_csv(path, index=False, encoding="utf-8-sig")
    out_df.to_csv(latest_path, index=False, encoding="utf-8-sig")

    risk_cnt = out_df["实盘可买性"].value_counts()
    print(f"rows={len(out_df)}")
    print(f"可买性分布: {risk_cnt.to_dict()}")
    print(f"saved {path}")
    print(f"saved {latest_path}")
    return path


if __name__ == "__main__":
    main()
