#!/usr/bin/env python3
"""
妙想模拟盘自动化（日复利全仓）：
  14:45  --phase select   mx-xuangu 选股
  14:57  --phase execute  次日持仓卖出 → 全仓买入 Top N

首次 execute：先清空妙想虚拟仓全部持仓，再按策略买入。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "automation"))

from mx_client import (  # noqa: E402
    MXError,
    clear_all_positions,
    get_balance,
    get_positions,
    market_buy,
    market_sell,
    parse_float,
    pick_field,
    xuangu_select,
)

STATE_PATH = ROOT / "records" / "live" / "trade_state.json"
CONFIG_PATH = ROOT / "records" / "live" / "strategy_config.json"
FALLBACK_CONFIG = ROOT / "output" / "best_mx_timeline_config.json"
INITIAL_EQUITY = 1_000_000


def load_config() -> dict:
    for p in (CONFIG_PATH, FALLBACK_CONFIG):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {
        "pct_min": 4.5,
        "pct_max": 5.3,
        "vol_min": 0.8,
        "ch_min": 1.0,
        "top_n": 3,
        "rank": "pct",
        "max_c": 5,
        "min_c": 1,
        "main_board": True,
    }


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "initialized": False,
        "equity_start": INITIAL_EQUITY,
        "equity_last": INITIAL_EQUITY,
        "pending_sells": [],
        "last_select": None,
        "trade_log": [],
    }


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def build_xuangu_query(cfg: dict) -> str:
    board = "A股主板非ST" if cfg.get("main_board") else "A股非ST"
    return (
        f"{board} 今日涨幅{cfg['pct_min']}%到{cfg['pct_max']}% "
        f"今日量比大于{cfg['vol_min']} 收盘价接近最高价 弱转强候选"
    )


def normalize_candidates(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        code = pick_field(row, "代码", "SECURITY_CODE")
        if not code or len(code) < 6:
            continue
        code = code.zfill(6)
        out.append(
            {
                "code": code,
                "name": pick_field(row, "名称", "SECURITY_SHORT_NAME"),
                "pct": parse_float(pick_field(row, "涨跌幅(%)", "涨跌幅 (%)")),
                "vol_ratio": parse_float(pick_field(row, "量比", "换手率(%)", "换手率 (%)")),
                "price": parse_float(pick_field(row, "最新价(元)", "最新价 (元)")),
            }
        )
    return out


def rank_and_pick(candidates: list[dict], cfg: dict) -> list[dict]:
    if cfg.get("min_c") and len(candidates) < cfg["min_c"]:
        return []
    if cfg.get("max_c") and len(candidates) > cfg["max_c"]:
        return []
    rank = cfg.get("rank", "pct")
    key = {"vol_ratio": "vol_ratio", "score": "pct", "pct": "pct"}.get(rank, "pct")
    if key == "score":
        for c in candidates:
            c["score"] = c["pct"] * c.get("vol_ratio", 1)
        key = "score"
    candidates = sorted(candidates, key=lambda x: x.get(key, 0), reverse=True)
    return candidates[: int(cfg.get("top_n", 3))]


def calc_buy_qty(avail: float, n: int, price: float) -> int:
    if price <= 0 or n <= 0:
        return 0
    per = avail / n
    lots = int(per / price / 100)
    return max(lots, 0) * 100


def write_daily_record(state: dict, action: str, extra: dict) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    day_dir = ROOT / "records" / "live" / today
    day_dir.mkdir(parents=True, exist_ok=True)
    log = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "equity_last": state.get("equity_last"),
        **extra,
    }
    log_path = day_dir / "mx_trade_log.json"
    logs = []
    if log_path.exists():
        logs = json.loads(log_path.read_text(encoding="utf-8"))
    logs.append(log)
    log_path.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")

    eq_csv = ROOT / "records" / "live" / "equity_daily.csv"
    header = "date,time,action,equity,avail_balance,daily_ret_pct\n"
    if not eq_csv.exists():
        eq_csv.write_text(header, encoding="utf-8")
    prev = state.get("equity_last", INITIAL_EQUITY)
    cur = extra.get("total_assets", prev)
    daily_ret = (cur / prev - 1) * 100 if prev else 0
    with eq_csv.open("a", encoding="utf-8") as f:
        f.write(
            f"{today},{log['time']},{action},{cur:.2f},"
            f"{extra.get('avail_balance', 0):.2f},{daily_ret:.4f}\n"
        )
    state["equity_last"] = cur


def phase_select(state: dict, cfg: dict) -> dict:
    query = build_xuangu_query(cfg)
    print(f"[select] 妙想选股: {query}")
    rows, _ = xuangu_select(query)
    candidates = normalize_candidates(rows)
    picks = rank_and_pick(candidates, cfg)
    state["last_select"] = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "query": query,
        "raw_count": len(candidates),
        "picks": picks,
    }
    today = datetime.now().strftime("%Y-%m-%d")
    out = ROOT / "records" / "live" / today / "candidates_mx.csv"
    if picks:
        import pandas as pd

        pd.DataFrame(picks).to_csv(out, index=False, encoding="utf-8-sig")
    write_daily_record(state, "select", {"query": query, "picks": picks, "raw_count": len(candidates)})
    print(f"[select] 候选 {len(candidates)} 只，入选 {len(picks)} 只")
    for p in picks:
        print(f"  {p['code']} {p['name']} pct={p['pct']:.2f}% price={p['price']}")
    return state


def sell_pending(state: dict) -> list[dict]:
    results = []
    for item in state.get("pending_sells", []):
        code = item["code"]
        qty = int(item["qty"])
        print(f"[sell] 市价卖出 {code} {qty}股 (买入日 {item.get('buy_date')})")
        try:
            r = market_sell(code, qty)
            results.append({"code": code, "qty": qty, "ok": True, "raw": r})
        except MXError as e:
            results.append({"code": code, "qty": qty, "ok": False, "error": str(e)})
    state["pending_sells"] = []
    return results


def phase_execute(state: dict, cfg: dict) -> dict:
    bal_before = get_balance()
    print(f"[balance] 总资产 {bal_before['total_assets']:.2f} 可用 {bal_before['avail_balance']:.2f}")

    sell_results = sell_pending(state)

    if not state.get("initialized"):
        print("[init] 首次交易：清空妙想虚拟仓全部持仓")
        cleared = clear_all_positions()
        state["initialized"] = True
        state["trade_log"].append(
            {"time": datetime.now().isoformat(), "action": "clear_all", "detail": cleared}
        )
        bal_before = get_balance()

    picks = []
    if state.get("last_select") and state["last_select"].get("picks"):
        sel_date = state["last_select"]["time"][:10]
        today = datetime.now().strftime("%Y-%m-%d")
        if sel_date == today:
            picks = state["last_select"]["picks"]
    if not picks:
        print("[execute] 无今日14:45候选，现场重新选股")
        state = phase_select(state, cfg)
        picks = state["last_select"]["picks"]

    if not picks:
        print("[execute] 今日无符合条件的标的，跳过买入")
        write_daily_record(
            state,
            "execute_skip",
            {**bal_before, "sells": sell_results, "buys": []},
        )
        save_state(state)
        return state

    avail = get_balance()["avail_balance"]
    n = len(picks)
    buy_results = []
    pending = []
    for p in picks:
        qty = calc_buy_qty(avail, n, p.get("price") or 0)
        if qty < 100:
            print(f"[buy] 跳过 {p['code']} 资金不足")
            continue
        print(f"[buy] 市价买入 {p['code']} {p['name']} {qty}股 (全仓1/{n})")
        try:
            r = market_buy(p["code"], qty)
            buy_results.append({"code": p["code"], "qty": qty, "ok": True, "raw": r})
            pending.append(
                {
                    "code": p["code"],
                    "name": p["name"],
                    "qty": qty,
                    "buy_date": datetime.now().strftime("%Y-%m-%d"),
                    "buy_price": p.get("price"),
                }
            )
        except MXError as e:
            buy_results.append({"code": p["code"], "qty": qty, "ok": False, "error": str(e)})

    state["pending_sells"] = pending
    bal_after = get_balance()
    write_daily_record(
        state,
        "execute",
        {
            **bal_after,
            "sells": sell_results,
            "buys": buy_results,
            "picks": picks,
        },
    )
    state["trade_log"].append(
        {
            "time": datetime.now().isoformat(),
            "action": "execute",
            "sells": sell_results,
            "buys": buy_results,
        }
    )
    print(f"[done] 总资产 {bal_after['total_assets']:.2f} 待次日卖出 {len(pending)} 只")
    return state


def git_push_records() -> None:
    publish = ROOT / "automation" / "run_mx_publish.py"
    if publish.exists():
        subprocess.run([sys.executable, str(publish)], cwd=ROOT, check=False)
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["select", "execute"], required=True)
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    state = load_state()

    try:
        if args.phase == "select":
            state = phase_select(state, cfg)
        else:
            state = phase_execute(state, cfg)
    except MXError as e:
        print(f"ERROR: {e}")
        return 1

    save_state(state)
    if not args.no_push:
        git_push_records()
    return 0


if __name__ == "__main__":
    sys.exit(main())
