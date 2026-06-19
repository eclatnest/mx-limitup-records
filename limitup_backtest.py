#!/usr/bin/env python3
"""
前一日买入、次日涨停策略回测
- 选股：T日「弱转强」形态（与妙想 mx-xuangu 条件对齐）
- 验证：T+1 是否涨停
- 行情：腾讯财经日K（东方财富 push 接口不稳定时的可靠替代）
- 今日候选：mx-xuangu 妙想选股
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import akshare as ak
import pandas as pd
import requests

OUTPUT_DIR = Path(__file__).parent / "output"
CACHE_DIR = OUTPUT_DIR / "cache"
MX_XUANGU_DIR = Path(r"C:\Users\25739\.claude\skills\mx-xuangu")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.qq.com/",
}

BACKTEST_DAYS = 0          # 0 = 不截断交易日
BACKTEST_YEARS = 10        # 近 N 年回测
HISTORY_BARS = 2500        # 覆盖 10+ 年

# 近10年优化参数（见 output/best_10y_config.json）
PCT_MIN, PCT_MAX = 4.5, 5.5
VOL_RATIO_MIN = 1.2
CLOSE_HIGH_RATIO_MIN = 0.99
TOP_N_PER_DAY = 5
RANK_BY = "pct"            # vol_ratio | score | pct
MAX_CANDIDATES: Optional[int] = None
MIN_CANDIDATES: Optional[int] = 2
MAIN_BOARD_ONLY = False


@dataclass
class StrategyParams:
    pct_min: float = PCT_MIN
    pct_max: float = PCT_MAX
    vol_ratio_min: float = VOL_RATIO_MIN
    close_high_ratio_min: float = CLOSE_HIGH_RATIO_MIN
    top_n_per_day: int = TOP_N_PER_DAY
    rank_by: str = RANK_BY
    max_candidates: Optional[int] = MAX_CANDIDATES
    min_candidates: Optional[int] = MIN_CANDIDATES
    main_board_only: bool = MAIN_BOARD_ONLY


def load_strategy_params() -> StrategyParams:
    for name in ("best_10y_config_cost.json", "best_10y_config.json"):
        cfg_path = OUTPUT_DIR / name
        if not cfg_path.exists():
            continue
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        return StrategyParams(
            pct_min=cfg.get("pct_min", PCT_MIN),
            pct_max=cfg.get("pct_max", PCT_MAX),
            vol_ratio_min=cfg.get("vol_min", VOL_RATIO_MIN),
            close_high_ratio_min=cfg.get("ch_min", CLOSE_HIGH_RATIO_MIN),
            top_n_per_day=cfg.get("top_n", TOP_N_PER_DAY),
            rank_by=cfg.get("rank", RANK_BY),
            max_candidates=cfg.get("max_c"),
            min_candidates=cfg.get("min_c"),
            main_board_only=cfg.get("main_board", MAIN_BOARD_ONLY),
        )
    return StrategyParams()


MAX_STOCKS = 600
MIN_HISTORY_DAYS = 30
WORKERS = 6

# ---------- 交易成本（A股典型值）----------
COMMISSION_RATE = 0.00025   # 佣金 万2.5（买卖双向）
STAMP_TAX_RATE = 0.0005     # 印花税 万5（仅卖出，2023-08-28 起）
SLIPPAGE_BUY = 0.0010       # 买入滑点 0.10%（相对收盘价）
SLIPPAGE_SELL = 0.0010      # 卖出滑点 0.10%
SLIPPAGE_SELL_LIMIT_UP = 0.0003  # 次日涨停卖出滑点更低（流动性好/封板）

COST_ASSUMPTION = (
    f"佣金万2.5双向 + 印花税万5(卖) + 滑点买{SLIPPAGE_BUY*100:.2f}%/卖{SLIPPAGE_SELL*100:.2f}%"
)


def apply_trade_costs(ret_gross_pct: float, next_limit_up: bool) -> float:
    """T收盘买/T+1收盘卖，扣除佣金+印花税+滑点后的净收益率(%)"""
    buy_cost = COMMISSION_RATE + SLIPPAGE_BUY
    sell_slip = SLIPPAGE_SELL_LIMIT_UP if next_limit_up else SLIPPAGE_SELL
    sell_cost = COMMISSION_RATE + STAMP_TAX_RATE + sell_slip
    round_trip = (buy_cost + sell_cost) * 100
    return ret_gross_pct - round_trip


def round_trip_cost_pct(next_limit_up: bool = False) -> float:
    buy_cost = COMMISSION_RATE + SLIPPAGE_BUY
    sell_slip = SLIPPAGE_SELL_LIMIT_UP if next_limit_up else SLIPPAGE_SELL
    sell_cost = COMMISSION_RATE + STAMP_TAX_RATE + sell_slip
    return (buy_cost + sell_cost) * 100


def limit_up_threshold(code: str, name: str) -> float:
    if "ST" in name.upper():
        return 4.8
    if code.startswith(("300", "301", "688")):
        return 19.5
    if code.startswith(("8", "4")):
        return 29.5
    return 9.8


def is_limit_up(pct: float, code: str, name: str) -> bool:
    return pct >= limit_up_threshold(code, name) - 0.05


def to_tencent_symbol(code: str) -> str:
    if code.startswith("6"):
        return f"sh{code}"
    return f"sz{code}"


def fetch_stock_universe(limit: int = MAX_STOCKS) -> pd.DataFrame:
    try:
        df = ak.stock_info_a_code_name()
        df = df.rename(columns={"code": "code", "name": "name"})
        df["code"] = df["code"].astype(str).str.zfill(6)
        df = df[~df["name"].str.contains("ST", case=False, na=False)]
        df = df[~df["code"].str.startswith(("8", "4"))]
        try:
            spot = ak.stock_zh_a_spot_em()
            spot["代码"] = spot["代码"].astype(str).str.zfill(6)
            spot = spot.sort_values("成交额", ascending=False)
            top_codes = set(spot["代码"].head(limit * 2))
            df = df[df["code"].isin(top_codes)].copy()
            amt_map = dict(zip(spot["代码"], spot["成交额"]))
            df["amount"] = df["code"].map(amt_map).fillna(0)
            df = df.sort_values("amount", ascending=False).head(limit)
        except Exception:
            df = df.head(limit)
        return df.reset_index(drop=True)
    except Exception:
        # API 不可用时从本地 K 线缓存恢复股票池
        codes = sorted({f.name.split("_")[1] for f in CACHE_DIR.glob("sin_*_*.csv")})
        rows = [{"code": c, "name": c, "amount": 0} for c in codes[:limit]]
        print(f"  [fallback] 从缓存加载股票池 {len(rows)} 只")
        return pd.DataFrame(rows)


def fetch_kline_sina(code: str, datalen: int = HISTORY_BARS, retries: int = 4) -> Optional[pd.DataFrame]:
    """新浪日K：datalen=2000 约 8 年，6000 约 25 年（取决于上市时间）"""
    cache_file = CACHE_DIR / f"sin_{code}_{datalen}.csv"
    if cache_file.exists():
        try:
            return pd.read_csv(cache_file, parse_dates=["date"])
        except Exception:
            pass

    sym = to_tencent_symbol(code)
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": sym, "scale": 240, "ma": "no", "datalen": datalen}
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=25)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                return None
            records = []
            for row in rows:
                records.append(
                    {
                        "date": row["day"],
                        "open": float(row["open"]),
                        "close": float(row["close"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "volume": float(row["volume"]),
                    }
                )
            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"])
            df["pct_chg"] = df["close"].pct_change() * 100
            df.to_csv(cache_file, index=False)
            time.sleep(0.08)
            return df
        except Exception:
            time.sleep(0.8 * (attempt + 1))
    return None


def fetch_kline_tencent(code: str, beg: str, end: str, retries: int = 4) -> Optional[pd.DataFrame]:
    cache_file = CACHE_DIR / f"tx_{code}_{beg}_{end}.csv"
    if cache_file.exists():
        try:
            return pd.read_csv(cache_file, parse_dates=["date"])
        except Exception:
            pass

    sym = to_tencent_symbol(code)
    param = f"{sym},day,{beg},{end},640,qfq"
    url = "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    for attempt in range(retries):
        try:
            r = requests.get(url, params={"param": param}, headers=HEADERS, timeout=20)
            r.raise_for_status()
            payload = r.json().get("data", {}).get(sym, {})
            rows = payload.get("qfqday") or payload.get("day") or []
            if not rows:
                return None
            records = []
            for row in rows:
                if len(row) < 6:
                    continue
                records.append(
                    {
                        "date": row[0],
                        "open": float(row[1]),
                        "close": float(row[2]),
                        "high": float(row[3]),
                        "low": float(row[4]),
                        "volume": float(row[5]),
                    }
                )
            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"])
            df["pct_chg"] = df["close"].pct_change() * 100
            df.to_csv(cache_file, index=False)
            time.sleep(0.05)
            return df
        except Exception:
            time.sleep(0.8 * (attempt + 1))
    return None


def fetch_kline(code: str, datalen: int = HISTORY_BARS) -> Optional[pd.DataFrame]:
    """优先新浪（稳定、历史长），失败回退腾讯"""
    df = fetch_kline_sina(code, datalen)
    if df is not None and len(df) >= MIN_HISTORY_DAYS:
        return df
    end_dt = datetime.now().strftime("%Y-%m-%d")
    beg_dt = (datetime.now() - timedelta(days=int(datalen * 1.6))).strftime("%Y-%m-%d")
    return fetch_kline_tencent(code, beg_dt, end_dt)


def download_all_klines(universe: pd.DataFrame, datalen: int = HISTORY_BARS) -> Dict[str, pd.DataFrame]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    result: Dict[str, pd.DataFrame] = {}

    def _one(row: pd.Series) -> Tuple[str, Optional[pd.DataFrame]]:
        return row["code"], fetch_kline(row["code"], datalen)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = [ex.submit(_one, row) for _, row in universe.iterrows()]
        done = 0
        total = len(futures)
        for fut in as_completed(futures):
            code, df = fut.result()
            done += 1
            if df is not None and len(df) >= MIN_HISTORY_DAYS:
                result[code] = df
            if done % 50 == 0 or done == total:
                print(f"  下载进度: {done}/{total}, 有效: {len(result)}")

    return result


def enrich_signals(df: pd.DataFrame, code: str, name: str, params: StrategyParams) -> pd.DataFrame:
    df = df.sort_values("date").copy()
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma5"]
    df["close_high_ratio"] = df["close"] / df["high"]
    df["code"] = code
    df["name"] = name
    df["main_board"] = not code.startswith(("300", "301", "688"))
    df["score"] = df["vol_ratio"] * df["close_high_ratio"] * df["pct_chg"]
    df["limit_up"] = df.apply(lambda r: is_limit_up(r["pct_chg"], code, name), axis=1)

    buy = (
        (df["pct_chg"] >= params.pct_min)
        & (df["pct_chg"] <= params.pct_max)
        & (df["vol_ratio"] >= params.vol_ratio_min)
        & (df["close_high_ratio"] >= params.close_high_ratio_min)
        & (~df["limit_up"])
    )
    if params.main_board_only:
        buy &= df["main_board"]
    df["buy_signal"] = buy
    df["next_pct"] = df["pct_chg"].shift(-1)
    df["next_close"] = df["close"].shift(-1)
    df["next_limit_up"] = df["limit_up"].shift(-1)
    df["ret_t1_gross"] = (df["next_close"] / df["close"] - 1) * 100
    df["ret_t1"] = df.apply(
        lambda r: apply_trade_costs(r["ret_t1_gross"], bool(r["next_limit_up"]) if pd.notna(r["next_limit_up"]) else False),
        axis=1,
    )
    return df


def run_backtest(
    kline_map: Dict[str, pd.DataFrame],
    universe: pd.DataFrame,
    params: StrategyParams,
    backtest_days: int = BACKTEST_DAYS,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
    name_map = dict(zip(universe["code"], universe["name"]))
    chunks: List[pd.DataFrame] = []

    for code, raw in kline_map.items():
        name = name_map.get(code, "")
        sig = enrich_signals(raw, code, name, params)
        part = sig[sig["buy_signal"]]
        if not part.empty:
            chunks.append(part)

    if not chunks:
        return pd.DataFrame(), pd.DataFrame(), {}

    signals = pd.concat(chunks, ignore_index=True).dropna(subset=["next_pct", "ret_t1"])

    cutoff = signals["date"].max() - pd.DateOffset(years=BACKTEST_YEARS)
    signals = signals[signals["date"] >= cutoff]

    if backtest_days and backtest_days > 0:
        trade_dates = sorted(signals["date"].unique())
        if len(trade_dates) > backtest_days:
            signals = signals[signals["date"] >= trade_dates[-backtest_days]]

    day_cnt = signals.groupby("date")["code"].transform("count")
    if params.max_candidates:
        signals = signals[day_cnt <= params.max_candidates]
    if params.min_candidates:
        signals = signals[signals.groupby("date")["code"].transform("count") >= params.min_candidates]

    rank_col = {"vol_ratio": "vol_ratio", "score": "score", "pct": "pct_chg"}.get(params.rank_by, "vol_ratio")
    if params.top_n_per_day and params.top_n_per_day > 0:
        signals = (
            signals.sort_values(["date", rank_col], ascending=[True, False])
            .groupby("date", group_keys=False)
            .head(params.top_n_per_day)
        )

    signals = signals.sort_values(["date", "code"]).reset_index(drop=True)
    signals["next_limit_up"] = signals["next_limit_up"].fillna(False).astype(bool)
    total = len(signals)
    hit = int(signals["next_limit_up"].sum())
    win = int((signals["ret_t1"] > 0).sum())
    not_hit = signals.loc[~signals["next_limit_up"], "ret_t1"]

    daily = (
        signals.groupby("date")
        .agg(signals=("code", "count"), limit_up_hits=("next_limit_up", "sum"), avg_ret_t1=("ret_t1", "mean"))
        .reset_index()
    )
    daily["hit_rate"] = daily["limit_up_hits"] / daily["signals"] * 100
    daily["portfolio_ret"] = daily["avg_ret_t1"]
    daily["cum_ret"] = (1 + daily["portfolio_ret"] / 100).cumprod() - 1
    equity = 1 + daily["cum_ret"]
    peak = equity.cummax()
    max_dd = float(((equity / peak - 1) * 100).min())
    start = signals["date"].min()
    y3 = start + pd.DateOffset(years=3)
    sig_y3 = signals[signals["date"] <= y3]
    if len(sig_y3) >= 5:
        d3 = sig_y3.groupby("date")["ret_t1"].mean() / 100
        cum_y3 = float(((1 + d3).prod() - 1) * 100)
    else:
        cum_y3 = 0.0

    summary = {
        "strategy": "弱转强次日涨停",
        "backtest_period": f"{signals['date'].min().date()} ~ {signals['date'].max().date()}",
        "trading_days": int(signals["date"].nunique()),
        "universe_size": len(kline_map),
        "total_signals": total,
        "avg_signals_per_day": round(total / max(signals["date"].nunique(), 1), 2),
        "next_day_limit_up_count": hit,
        "next_day_limit_up_rate_pct": round(hit / total * 100, 2) if total else 0,
        "avg_return_t1_pct": round(float(signals["ret_t1"].mean()), 3),
        "median_return_t1_pct": round(float(signals["ret_t1"].median()), 3),
        "win_rate_pct": round(win / total * 100, 2) if total else 0,
        "avg_return_when_limit_up_pct": round(float(signals.loc[signals["next_limit_up"], "ret_t1"].mean()), 3) if hit else 0,
        "avg_return_when_not_limit_up_pct": round(float(not_hit.mean()), 3) if len(not_hit) else 0,
        "portfolio_cum_return_pct": round(float(daily["cum_ret"].iloc[-1] * 100), 2) if len(daily) else 0,
        "max_drawdown_pct": round(max_dd, 2),
        "cum_return_first_3y_pct": round(cum_y3, 2),
        "avg_return_t1_gross_pct": round(float(signals["ret_t1_gross"].mean()), 3),
        "avg_round_trip_cost_pct": round(float(signals.apply(
            lambda r: round_trip_cost_pct(bool(r["next_limit_up"])), axis=1
        ).mean()), 3),
        "cost_assumption": COST_ASSUMPTION,
        "params": asdict(params),
    }
    return signals, daily, summary


def _pick_field(row: dict, *prefixes: str) -> str:
    for k, v in row.items():
        for p in prefixes:
            if k == p or k.startswith(p):
                return str(v)
    return ""


def fetch_mx_today_picks() -> Tuple[List[Dict[str, str]], str]:
    if not os.getenv("MX_APIKEY"):
        return [], ""
    sys.path.insert(0, str(MX_XUANGU_DIR))
    try:
        from mx_xuangu import MXSelectStock

        query = "A股非ST 今日涨幅3.5%到5.5% 今日量比大于1.5 收盘价接近最高价 当日弱转强候选至少2只"
        mx = MXSelectStock()
        result = mx.search(query)
        rows, _, err = mx.extract_data(result)
        if err or not rows:
            return [], query
        picks = []
        for row in rows[:25]:
            picks.append(
                {
                    "code": _pick_field(row, "代码", "SECURITY_CODE"),
                    "name": _pick_field(row, "名称", "SECURITY_SHORT_NAME"),
                    "pct": _pick_field(row, "涨跌幅(%)", "涨跌幅 (%)"),
                    "turnover": _pick_field(row, "换手率(%)", "换手率 (%)", "量比"),
                    "price": _pick_field(row, "最新价(元)", "最新价 (元)"),
                }
            )
        return picks, query
    except Exception as e:
        return [], str(e)


def write_report(signals, daily, summary, picks, mx_query) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sig_path = OUTPUT_DIR / f"signals_{ts}.csv"
    daily_path = OUTPUT_DIR / f"daily_stats_{ts}.csv"
    summary_path = OUTPUT_DIR / f"summary_{ts}.json"
    report_path = OUTPUT_DIR / f"report_{ts}.md"

    if not signals.empty:
        signals[
            [
                "date", "code", "name", "close", "pct_chg", "vol_ratio", "close_high_ratio",
                "next_pct", "next_limit_up", "ret_t1_gross", "ret_t1",
            ]
        ].to_csv(sig_path, index=False, encoding="utf-8-sig")
    daily.to_csv(daily_path, index=False, encoding="utf-8-sig")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    top_hits = signals[signals["next_limit_up"]].sort_values("date", ascending=False).head(15)
    hit_lines = []
    for _, r in top_hits.iterrows():
        hit_lines.append(
            f"| {r['date'].date()} | {r['code']} | {r['name']} | {r['pct_chg']:.2f}% | {r['next_pct']:.2f}% | {r['ret_t1']:.2f}% |"
        )

    lines = [
        "# 前一日买入 · 次日涨停 策略回测报告",
        "",
        "## 策略逻辑",
        "",
        "| 条件 | 说明 |",
        "|------|------|",
        "| T日涨幅 4.5%–5.5% | 近10年优化蓄势区间 |",
        "| 量比 ≥ 1.2 | 温和放量 |",
        "| 收盘/最高 ≥ 99% | 几乎收在最高价 |",
        "| 候选日 | **恰好 2 只**（max=2, min=2） |",
        "| 每日出手 | **Top N**（按 score / vol_ratio / pct 排序） |",
        "| 排除 ST、当日涨停 | 降低噪声 |",
        "",
        "**交易假设**：T 日收盘价买入 → T+1 日收盘价卖出（统计 T+1 是否涨停）",
        f"**含成本**：{COST_ASSUMPTION}；涨停卖出滑点 {SLIPPAGE_SELL_LIMIT_UP*100:.2f}%",
        "",
        "## 回测结果",
        "",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 回测区间 | {summary.get('backtest_period')} |",
        f"| 股票池 | {summary.get('universe_size')} 只（成交额Top） |",
        f"| 信号总数 | {summary.get('total_signals')} |",
        f"| 日均信号 | {summary.get('avg_signals_per_day')} |",
        f"| **次日涨停率** | **{summary.get('next_day_limit_up_rate_pct')}%** |",
        f"| 次日平均收益(毛) | {summary.get('avg_return_t1_gross_pct', 0)}% |",
        f"| 往返成本约 | {summary.get('avg_round_trip_cost_pct', 0)}%/笔 |",
        f"| 次日平均收益(净) | {summary.get('avg_return_t1_pct', 0)}% |",
        f"| 次日胜率 | {summary.get('win_rate_pct')}% |",
        f"| 涨停样本均收益 | {summary.get('avg_return_when_limit_up_pct')}% |",
        f"| 未涨停样本均收益 | {summary.get('avg_return_when_not_limit_up_pct')}% |",
        f"| 等权组合累计 | {summary.get('portfolio_cum_return_pct')}% |",
        "",
        "## 次日涨停成功案例（最近15条）",
        "",
        "| 买入日 | 代码 | 名称 | T日涨幅 | T+1涨幅 | T+1收益 |",
        "|--------|------|------|---------|---------|---------|",
        *hit_lines,
        "",
        f"## 妙想选股今日候选",
        "",
        f"查询语句: `{mx_query}`",
        "",
    ]
    if picks:
        lines += ["| 代码 | 名称 | 涨跌幅% | 换手率% | 最新价 |", "|------|------|---------|---------|--------|"]
        for p in picks:
            lines.append(f"| {p.get('code','')} | {p.get('name','')} | {p.get('pct','')} | {p.get('turnover','')} | {p.get('price','')} |")
    else:
        lines.append("_未获取到实时选股结果_")

    lines += ["", f"详细信号: `{sig_path.name}`", f"每日统计: `{daily_path.name}`"]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main():
    print("=" * 60)
    print("前一日买入 · 次日涨停 策略回测")
    print("=" * 60)

    end_dt = datetime.now()
    print("\n[1/4] 构建股票池（成交额Top + 排除ST）...")
    universe = fetch_stock_universe(MAX_STOCKS)
    print(f"  股票池: {len(universe)} 只")

    print(f"\n[2/4] 下载日K（新浪 datalen={HISTORY_BARS}，约 {HISTORY_BARS // 250} 年）...")
    kline_map = download_all_klines(universe, HISTORY_BARS)
    if kline_map:
        all_dates = pd.concat([df[["date"]] for df in kline_map.values()])
        dmin, dmax = all_dates["date"].min().date(), all_dates["date"].max().date()
        months = (dmax.year - dmin.year) * 12 + (dmax.month - dmin.month)
        print(f"  有效K线: {len(kline_map)} 只 | 区间 {dmin} ~ {dmax}（约 {months} 个月）")
    else:
        print("  有效K线: 0 只")

    print("\n[3/4] 回测...")
    params = load_strategy_params()
    signals, daily, summary = run_backtest(kline_map, universe, params, BACKTEST_DAYS)
    if not summary:
        print("  无信号，请放宽参数")
        return

    print("\n[4/4] 妙想今日选股...")
    picks, mx_query = fetch_mx_today_picks()
    report = write_report(signals, daily, summary, picks, mx_query)

    print("\n" + "=" * 60)
    for k, v in summary.items():
        if k != "params":
            print(f"  {k}: {v}")
    print(f"\n报告: {report}")


if __name__ == "__main__":
    main()
