# 妙想模拟盘 Automation（日复利全仓）

## 三条 Automation

| 名称 | 触发 | 脚本 |
|------|------|------|
| **弱转强-妙想14:45选股** | 工作日 14:45 | `run_mx_trade.py --phase select` |
| **弱转强-妙想14:57买卖** | 工作日 14:57 | `run_mx_trade.py --phase execute` |
| **弱转强-交易记录推GitHub** | 工作日 **15:10** | `run_mx_publish.py` |

预填 JSON：
- `cursor_workflow_prefill_mx_1445.json`
- `cursor_workflow_prefill_mx_1457.json`
- `cursor_workflow_prefill_mx_github.json` ← **GitHub 看板推送**

## 时间线

```
14:45  mx-xuangu 选股 → 写入 trade_state.last_select
14:57  市价卖出昨日 pending_sells
       首次：清空虚拟仓全部持仓
       可用资金等分 → 市价买入 Top 3（日复利全仓）
次日14:57  卖出今日仓位（下一轮 execute）
```

## 日复利全仓

- 每天用妙想账户**全部可用资金**买入
- 盈利留在账户，次日自动作为更大本金继续买
- `records/live/equity_daily.csv` 记录 `total_assets` 权益曲线

## 前置条件

1. [妙想Skills](https://dl.dfcfs.com/m/itc4) 获取 `MX_APIKEY`
2. 创建并绑定**模拟组合**账户
3. 本地：项目根目录 `.env` 已配置（勿提交 Git）；或 Windows 用户环境变量 `MX_APIKEY`
4. **Cursor Automation**：在 Automation 设置 → Environment variables 添加 `MX_APIKEY`（Cloud 运行必需）
5. 将 `automation/`、`records/live/` 推送到 GitHub

## 状态文件

| 文件 | 说明 |
|------|------|
| `records/live/trade_state.json` | 持仓待卖、是否已清仓、选股缓存 |
| `records/live/strategy_config.json` | 策略参数 |
| `records/live/equity_daily.csv` | 日复利权益 |

## 手动测试

```powershell
# 需先设置 MX_APIKEY
$env:MX_APIKEY="your_key"

python automation/run_mx_trade.py --phase select --no-push
python automation/run_mx_trade.py --phase execute --no-push
```

## 旧版（仅 GitHub 记录，不用妙想）

`run_daily.py` + `cursor_workflow_prefill.json` — 16:30 新浪扫描写 GitHub。
