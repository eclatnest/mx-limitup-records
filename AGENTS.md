# AGENTS.md

## Cursor Cloud specific instructions

弱转强次日涨停策略项目（纯 Python 脚本，无构建步骤、无测试套件、无 lint 配置）。两个产品：

| 产品 | 入口 | 数据源 | 需要密钥 |
|------|------|--------|----------|
| 历史回测 + 实时候选扫描 | `python scan_live.py` | 新浪/腾讯日K + akshare 股票池 | 否 |
| 妙想模拟盘自动化 | `automation/run_mx_trade.py --phase select\|execute` | dfcfs.com 妙想 API | 是（`MX_APIKEY`） |

### 运行环境
- 依赖装在 `.venv` 中（系统 Python 为 PEP 668 externally-managed，必须用 venv）。用 `.venv/bin/python ...` 运行脚本。
- 系统包 `python3-venv` 已预装（venv 创建所需）；它不在 update 脚本里，靠 VM 快照保留。
- `MX_APIKEY` 通过 Secrets 注入，已可用；妙想 API（dfcfs.com）在本环境可达。

### 网络注意事项（非显然）
- 新浪/腾讯日K 接口稳定可达。
- akshare 的股票池接口对**深交所 `www.szse.cn` 偶发 SSL 阻断**，会导致 `ak.stock_info_a_code_name()` 间歇失败。失败时 `fetch_stock_universe` 会**自动回退到本地 K 线缓存** `output/cache/sin_*.csv` 构建股票池——所以首次跑前缓存为空会得到空股票池。缓存非空后回退路径可用。连通正常时使用完整 600 只股票池。
- 因此实时扫描的结果可能因当时网络在「完整池」与「缓存池」之间变化，属正常现象。

### 运行/验证
- 实时扫描（核心 hello-world，会写 `records/live/`）：`.venv/bin/python scan_live.py`
- 妙想选股（只读查询 + 写本地状态文件）：`.venv/bin/python automation/run_mx_trade.py --phase select --no-push`
- **慎用** `--phase execute`：会对妙想模拟仓真正下买卖单。
- `scan_live.py --full-history` 需要 `output/best_10y_config_cost.json`（被 gitignore，仓库中不存在），缺失会在末尾报错；常规验证用不带 `--full-history` 的形式。
- 无 lint 配置；基本语法检查可用 `.venv/bin/python -m py_compile *.py automation/*.py`。

### 记录文件
- `scan_live.py` / mx 脚本会改写 `records/` 下的数据文件（候选、run_log、trade_state 等）。这些是运行产物——做环境验证后若不想提交，用 `git checkout -- records/` 还原并删除新建的当日目录。
