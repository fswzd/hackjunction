# 众幕 AI 角色组件

当前包含商单需求分析员、运营官、审稿员、内容导演、Scout、模拟观众、数据分析师七个可独立运行角色。没有前端，尚未接入持久化自动编排。默认 Mock：不访问模型、不产生模型调用费用。

第一次使用请读 [完整使用说明](完整使用说明.md)：包含角色串联、逐个运行、改稿、商单／PR分析、模型配置、费用与报错处理。第七个商单分析角色已独立实现，使用方法见 [PR_ANALYST.md](PR_ANALYST.md)。

需要 Python 3.13。Windows 可在本目录创建隔离环境并安装锁定依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe tools/run_scout.py --input examples/scout-task.json --output scout-result.json
```

这台电脑已安装的 Python 3.13 位于 `%LOCALAPPDATA%\Programs\Python\Python313\python.exe`；若 python 命令打开商店，可用该解释器创建环境。

六角色文件交接演示（输出目录必须是新的）：

```powershell
.\.venv\Scripts\python.exe tools/demo_team.py --input examples/team-demo.json --output-dir demo-first-run --confirm-mock-demo
```

该入口只支持 Mock；保存各角色输入、输出和 manifest。预选题和确认字段是演示占位，Mock 审稿不会给语义通过；继续模拟观众只验证交接。它不是正式业务 Runner。

| 角色 | 命令入口 | 说明 |
| --- | --- | --- |
| 商单需求分析员 | tools/run_pr_analyst.py | [PR_ANALYST.md](PR_ANALYST.md) |
| 运营官 | tools/run_operator.py | [OPERATOR.md](OPERATOR.md) |
| 审稿员 | tools/run_reviewer.py | [REVIEWER.md](REVIEWER.md) |
| 内容导演 | tools/run_director.py | [DIRECTOR.md](DIRECTOR.md) |
| 流量捕捉者 | tools/run_scout.py | [SCOUT.md](SCOUT.md) |
| 模拟观众 | tools/run_audience.py | [AUDIENCE.md](AUDIENCE.md) |
| 数据分析师 | tools/run_analyst.py | [ANALYST.md](ANALYST.md) |

各角色样例位于 examples。真实百炼调用必须配置环境密钥并显式加 --live；本轮未验证真实模型效果。Scout 的 live 只代表模型分析，仍不联网搜索。
