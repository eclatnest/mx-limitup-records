# Cursor Automation 配置说明

## 自动化做什么

每个 **A 股交易日收盘后**（建议 16:30）：

1. 用新浪 K 线扫描当日弱转强候选（**不用妙想**）
2. 写入 `records/live/YYYY-MM-DD/`
3. 更新 `records/README.md`（GitHub 首页看板）
4. `git commit` + `push` 到本仓库

每周日额外执行 `--full-history`，刷新 `records/history/` 全量回测。

## 在 Cursor 里创建 Automation

| 项目 | 建议值 |
|------|--------|
| 名称 | 弱转强策略-每日记录上GitHub |
| 触发 | 定时：工作日 16:30（`30 16 * * 1-5`） |
| 仓库 | 本仓库 `mx-limitup-records` |
| 分支 | `main` |
| 工具 | 无需 Slack / 妙想 MCP |

### Agent 指令（粘贴到 Automation Prompt）

```
在本仓库根目录执行（不使用任何妙想 mx skills）：

1. python automation/run_daily.py
2. 若失败，读取报错并修复后重试一次
3. 完成后简要汇报：今日候选几只、代码列表、是否已 push 到 GitHub

数据源仅限 limitup_backtest.py 的新浪 K 线逻辑。
只提交 records/ 目录变更。
```

预填 JSON 见 `cursor_workflow_prefill.json`。

## 手动一次性初始化历史

```powershell
python scan_live.py --full-history
git add records/
git commit -m "init history records"
git push
```
