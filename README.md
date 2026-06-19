# mx-limitup-records

弱转强次日涨停策略 — **历史回测 + 实时候选**，数据源为新浪日K，**不使用妙想 skills**。

## GitHub 上查看记录

| 类型 | 路径 |
|------|------|
| **总览看板** | [records/README.md](records/README.md) |
| **实时候选** | [records/live/latest_candidates.csv](records/live/latest_candidates.csv) |
| **运行日志** | [records/live/run_log.csv](records/live/run_log.csv) |
| **历史信号** | [records/history/signals_all.csv](records/history/signals_all.csv) |
| **历史每日** | [records/history/daily_detail.csv](records/history/daily_detail.csv) |
| **历史逐笔价** | [records/history/trades_prices.csv](records/history/trades_prices.csv) |

## 本地运行

```powershell
pip install -r requirements.txt
python scan_live.py --full-history   # 刷新历史
python scan_live.py                  # 仅实时
python automation/run_daily.py       # 实时 + git push
```

## Cursor Automation

见 [automation/README.md](automation/README.md)
