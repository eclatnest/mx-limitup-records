#!/usr/bin/env python3
"""妙想模拟盘 API 封装（自包含，不依赖本机 skills 目录）"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

_ROOT = Path(__file__).resolve().parent.parent
XUANGU_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/stock-screen"


def _load_env_file() -> None:
    env_path = _ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_env_file()

MX_APIKEY = os.environ.get("MX_APIKEY")
MX_API_URL = os.environ.get("MX_API_URL", "https://mkapi2.dfcfs.com/finskillshub")


class MXError(Exception):
    pass


def _check_key() -> None:
    if not MX_APIKEY:
        raise MXError(
            "未配置 MX_APIKEY。请在 Cursor Automation → Environment variables 添加 MX_APIKEY，"
            "或在仓库根目录 .env 中配置。"
        )


def _post(endpoint: str, body: Dict[str, Any]) -> Dict[str, Any]:
    _check_key()
    url = f"{MX_API_URL}{endpoint}"
    headers = {"apikey": MX_APIKEY, "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=body, timeout=45)
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


def clear_all_positions() -> List[Dict[str, Any]]:
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


def _build_column_map(columns: List[Dict[str, Any]]) -> Dict[str, str]:
    name_map: Dict[str, str] = {}
    for col in columns or []:
        if not isinstance(col, dict):
            continue
        en_key = col.get("field", "") or col.get("name", "") or col.get("key", "")
        cn_name = col.get("displayName", "") or col.get("title", "") or col.get("label", "")
        date_msg = col.get("dateMsg", "")
        if date_msg:
            cn_name = f"{cn_name} {date_msg}"
        if en_key is not None and cn_name is not None:
            name_map[str(en_key)] = str(cn_name)
    return name_map


def _columns_order(columns: List[Dict[str, Any]]) -> List[str]:
    order: List[str] = []
    for col in columns or []:
        if not isinstance(col, dict):
            continue
        en_key = col.get("field") or col.get("name") or col.get("key")
        if en_key is not None:
            order.append(str(en_key))
    return order


def _datalist_to_rows(
    datalist: List[Dict[str, Any]],
    column_map: Dict[str, str],
    column_order: List[str],
) -> List[Dict[str, str]]:
    if not datalist:
        return []
    first = datalist[0]
    extra_keys = [k for k in first if k not in column_order]
    header_order = column_order + extra_keys
    rows: List[Dict[str, str]] = []
    for row in datalist:
        if not isinstance(row, dict):
            continue
        cn_row: Dict[str, str] = {}
        for en_key in header_order:
            if en_key not in row:
                continue
            cn_name = column_map.get(en_key, en_key)
            val = row[en_key]
            if val is None:
                cn_row[cn_name] = ""
            elif isinstance(val, (dict, list)):
                cn_row[cn_name] = json.dumps(val, ensure_ascii=False)
            else:
                cn_row[cn_name] = str(val)
        rows.append(cn_row)
    return rows


def _extract_xuangu(result: Dict[str, Any]) -> Tuple[List[Dict[str, str]], Optional[str]]:
    status = result.get("status")
    if status != 0:
        return [], f"顶层错误: 状态码 {status} - {result.get('message', '')}"
    inner = result.get("data", {}).get("data", {})
    data_list = inner.get("allResults", {}).get("result", {}).get("dataList", [])
    columns = inner.get("allResults", {}).get("result", {}).get("columns", [])
    if isinstance(data_list, list) and data_list:
        column_map = _build_column_map(columns)
        order = _columns_order(columns)
        return _datalist_to_rows(data_list, column_map, order), None
    return [], "返回中无有效 dataList"


def xuangu_select(query: str) -> Tuple[List[Dict[str, str]], str]:
    _check_key()
    headers = {"Content-Type": "application/json", "apikey": MX_APIKEY}
    r = requests.post(XUANGU_URL, headers=headers, json={"keyword": query}, timeout=45)
    r.raise_for_status()
    rows, err = _extract_xuangu(r.json())
    if err:
        raise MXError(err)
    return rows, query
