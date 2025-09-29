五、运行效果

每天 北京时间 10:00，GitHub Actions 会自动运行你的 market_report.py。

程序会：

获取 SPY / QQQ / BTC / VIX 最新价格和历史最高价比例

保存提醒状态 alerts.json

追加每天的数据到 market_log.csv

如果触发阈值（价格比最高价下降超过 5%），会单独发微信提醒

每天都会发完整市场数据到 Server酱

运行后，会自动把 market_log.csv 和 alerts.json 提交回仓库保存。

六、你要做的步骤（小白版操作指南）

在 GitHub 上新建一个仓库（或者用你现有的）。

上传以下文件：

market_report.py（你的主程序）

requirements.txt（依赖说明）

.github/workflows/market.yml（工作流配置）

在仓库 Settings → Secrets → Actions 新建 Secret：

名字：SERVER_CHAN_KEY

值：填你的 Server酱 Key

提交后，Actions 会在 第二天 10 点自动运行。
你也可以到仓库的 Actions 标签页手动点“Run workflow”来测试。
