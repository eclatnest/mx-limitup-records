# 弱转强策略 · 历史 & 实时记录

> 最后更新：2026-06-19 08:54:10（自动化，**不使用妙想**）

## 实时记录（最近交易日）

- **交易日**：2026-06-15
- **候选数量**：2
- **代码**：000967, 002049
- [当日候选 CSV](live/2026-06-15/candidates.csv)
- [实时运行日志](live/run_log.csv)
- [最新候选](live/latest_candidates.csv)

## 历史回测（含成本）

| 指标 | 数值 |
|------|------|
| 回测区间 | 2016-06-22 ~ 2026-06-15 |
| 累计收益 | 1850.64% |
| 最大回撤 | -23.64% |
| 交易天数 | 665 |
| 次日涨停次数 | 8 |

### 历史数据文件

- [全量信号](history/signals_all.csv)
- [每日明细](history/daily_detail.csv)
- [逐笔成交价](history/trades_prices.csv)
- [日度PnL](history/pnl_daily.csv)
- [回测摘要](history/summary.json)
- [当前参数](history/config.json)

## 策略参数（当前）

```json
{
  "pct_min": 4.5,
  "pct_max": 5.5,
  "vol_min": 1.0,
  "ch_min": 1.0,
  "top_n": 2,
  "rank": "pct",
  "max_c": null,
  "min_c": 2,
  "main_board": false
}
```

## 说明

- 数据源：新浪日K（`limitup_backtest.py`），**不调用妙想 skills**
- 买入假设：T 日收盘价；卖出：T+1 收盘价
- 实时扫描：每个交易日收盘后运行，写入 `records/live/`