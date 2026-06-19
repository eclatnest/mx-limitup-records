#!/usr/bin/env python3
"""妙想模拟盘 API 封装（mx-moni / mx-xuangu）"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

_ROOT = Path(__file__).resolve().parent.parent


def _load_env_file() -> None:
    env_path = _ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


_load_env_file()

MX_APIKEY = os.environ.get("MX_APIKEY")
MX_API_URL = os.environ.get("MX_API_URL", "https://mkapi2.dfcfs.com/finskillshub")


class MXError(Exception):
    pass


def _check_key() -> None:
    if not MX_APIKEY:
        raise MXError("未配置 MX_APIKEY 环境变量")


def _post(endpoint: str, body: Dict[str, Any]) -> Dict[str, Any]:
    _check_key()
    url = f"{MX_API_URL}{endpoint}"
    headers = {"apikey": MX_APIKEY, "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()
    data = r.json()
    ok = data.get("success") or str(data.get("code")) in ("200", "0")
    if not ok:
        raise MXError(f"API失败 code={data.get('code')} msg={data.get('message')}")
    return data


def get_balance() -> Dict[str, float]:
    data = _post("/api/claw/mockTrading/balance", {"moneyUnit": 1})
    d = data.get("data") or {}
    return {
        "total_assets": float(d.get("totalAssets") or 0),
        "avail_balance": float(d.get("availBalance") or 0),
    }


def get_positions() -> List[Dict[str, Any]]:
    data = _post("/api/claw/mockTrading/positions", {"moneyUnit": 1})
    raw = data.get("data")
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("positions") or raw.get("positionList") or raw.get("list") or []
    else:
        items = []
    out = []
    for p in items:
        if not isinstance(p, dict):
            continue
        code = str(p.get("stockCode") or p.get("code") or "").zfill(6)
        qty = int(p.get("availQty") or p.get("quantity") or p.get("qty") or 0)
        if code and qty > 0:
            out.append({"code": code, "qty": qty, "raw": p})
    return out


def market_buy(code: str, qty: int) -> Dict[str, Any]:
    if qty % 100 != 0 or qty <= 0:
        raise MXError(f"买入数量须为100整数倍: {qty}")
    return _post(
        "/api/claw/mockTrading/trade",
        {"type": "buy", "stockCode": code, "quantity": qty, "useMarketPrice": True},
    )


def market_sell(code: str, qty: int) -> Dict[str, Any]:
    if qty % 100 != 0 or qty <= 0:
        raise MXError(f"卖出数量须为100整数倍: {qty}")
    return _post(
        "/api/claw/mockTrading/trade",
        {"type": "sell", "stockCode": code, "quantity": qty, "useMarketPrice": True},
    )


def cancel_all_orders() -> Dict[str, Any]:
    return _post("/api/claw/mockTrading/cancel", {"type": "all"})


def clear_all_positions() -> List[Dict[str, Any]]:
    """清仓：市价卖出全部持仓。"""
    results = []
    for p in get_positions():
        try:
            results.append({"code": p["code"], "qty": p["qty"], "result": market_sell(p["code"], p["qty"])})
        except MXError as e:
            results.append({"code": p["code"], "qty": p["qty"], "error": str(e)})
    return results


def pick_field(row: dict, *prefixes: str) -> str:
    for k, v in row.items():
        for p in prefixes:
            if k == p or str(k).startswith(p):
                return str(v)
    return ""


def parse_float(s: str) -> float:
    try:
        return float(re.sub(r"[^\d.\-]", "", str(s)) or "0")
    except ValueError:
        return 0.0


def xuangu_select(query: str) -> Tuple[List[Dict[str, str]], str]:
    import sys
    from pathlib import Path

    skill_dir = Path(r"C:\Users\25739\.claude\skills\mx-xuangu")
    if skill_dir.exists():
        sys.path.insert(0, str(skill_dir))
    from mx_xuangu import MXSelectStock

    mx = MXSelectStock()
    result = mx.search(query)
    rows, _, err = mx.extract_data(result)
    if err:
        raise MXError(err)
    return rows, query
