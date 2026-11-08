# hackjunction

hackjunction_26.1106 — 多 Agent 自媒体内容系统 · 七角色工作流编排（契约 `seven-agent.v0.1`）

把七个业务 Agent 经统一接口 `AgentAdapter.invoke(AgentCall) -> AgentResult` 串成可运行的
内容生产工作流：**选题捕捉 → 商单分析 → Brief 确认 → 创作 → 规则/审校 → 试映 → 定向改稿 → 导出**。
默认 Mock（零联网零费用）；五个专家角色可按角色灰度启用真实模型（MiMo），Mock 与 live 同契约，
live 模式绝不回退 Mock。

## 系统构成

| 层 | 路径 | 职责 |
| --- | --- | --- |
| 编排统筹层 | `backend/workflow/five_agent/` | 契约、状态机（LangGraph）、条件路由、预算、人工闸门、版本/哈希、恢复与收据 |
| 业务角色本体 | `birthco-local/backend/agents/` | 七角色实现（输入冻结、范围校验、输出契约），Mock/live 同一 schema |
| 业务服务 | `birthco-local/backend/` | Flask API、SQLite 持久化与台账、试映模拟、平台账号接入（抖音/小红书） |
| 模型接入 | `birthco-local/backend/adapters/model/` | 统一 MiMo 适配器（Anthropic 兼容、TLS 钉扎、无自动重试）+ 按 agent 解析的工厂 |
| 前端工作台 | `frontend/` | Vite 工作台（演示适配器可脱离后端独立体验） |
| 专家线开发文档 | `docs/experts/` | 五专家开发链产物：架构审计 / harness / 桥接 / 记忆检索 / RFC / 评测 / 交接 |
| 契约与证据 | `birthco-local/contracts/`、`evidence/` | 机器可读契约（OpenAPI/schemas）与分级验证证据 |

七角色：商单需求分析员 `pr_analyst` / 运营官 `operations_officer` / 内容主创 `content_creator` /
审稿员 `editorial_reviewer` / 流量捕捉者 `traffic_scout` / 数据分析师 `data_analyst` / 模拟观众 `simulated_audience`。

## 启动（一键）

```powershell
python run.py --detach # 迁移数据库并启动 API、后台任务进程和工作台
.\start.ps1          # PowerShell 版（等价，PID/日志约定相同）
.\stop.ps1           # 停止（run.py 前台模式用 Ctrl+C 连带清理进程树）
```

- 打开 [任务中心](http://127.0.0.1:4173/workspace/tasks)。首次进入可用示例身份完成四步本地设置。
- 默认连接本地 API，并使用离线 Mock 模型。创建任务后等待任务书，确认后查看候选稿。勾选试映可查看模拟观众和分析结果。退回修改会生成下一版，验收后可到「素材库」下载 Markdown。
- 要演示七角色，创建时勾选商单和试映，提供已授权的参考资料。简报中分行填写 `品牌：城市脚步` 和 `产品：周末步行指南`，再填写正文需求。
- 后端 API `http://127.0.0.1:5001`（`/api/v1/session` 等；数据目录 `birthco-local\data`）
- run.py 参数：`--skip-api` / `--skip-worker` / `--skip-frontend` / `--data-dir X:\data` / `--detach`
- 前置为 Python 3.13 和 Node.js。启动器会补装 Python 和前端依赖。
- 后台日志位于 `.run/worker.err.log`。排查时先看任务事件，再核对数据库里的 `runs`、`model_calls` 和 `checkpoints`。结果未知的调用会中断并保留记录，需先对账。

## 快速开始（验证）

```powershell
python -m pytest tests/ -q                                    # 编排层
cd birthco-local; python -m pytest tests/ -q                  # 业务层
cd ..; python run_mock_demo.py --include-scout --output evidence/mock-flow-with-scout.json
python tools/check_review_prompt_hash.py                      # 审稿提示词指纹
cd birthco-local; python tools/export_contracts.py --check    # 契约导出一致性
```

## Mock 与 live

- 工作台默认使用 Mock，验收链路无需模型密钥。Mock 稿件和诊断只用于验证流程。
- 工作台的百炼模式使用运行环境里的 `BIRTHCO_MODEL_MODE=live`、`DASHSCOPE_API_KEY` 和可选 `QWEN_MODEL_ID`（默认 `qwen3.8-flash`）。模型调用按服务商账户计费。
- 独立的编排验证工具仍支持按角色启用真实模式：

```python
from backend.workflow.five_agent.adapters import AdapterRouter
repo = Repository("workflow.sqlite")
router = AdapterRouter(repo, agent_modes={"traffic_scout": "live"})   # 仅该角色走真实适配器
```

- 可选 live 角色：`operations_officer`、`traffic_scout`、`content_creator`、`editorial_reviewer`、`data_analyst`。
- **凭据口径（去 Key 化）**：代码不读取任何 `.env` 文件；真实凭据只经运行时进程环境变量注入
  （`$env:MIMO_API_KEY='…'`），用完即弃，不落盘、不入库；`.env.example` 仅是变量名参考，禁止写入真实值。
- 预算与收据：调用受预算上限约束，收据绑定输入指纹（同输入重放、异输入不重放），用量进台账。

## 目录

| 路径 | 内容 |
| --- | --- |
| `backend/workflow/five_agent/` | 契约、Repository、Gateway、投影隔离、规则/指标、Adapter、StateGraph、Driver |
| `birthco-local/` | 七角色本体、Flask API、存储/台账、试映模拟、契约导出、CLI 工具（`tools/run_*.py`） |
| `tests/`、`birthco-local/tests/` | 编排、恢复、预算、专家入口离线联调与业务测试（双套件） |
| `docs/orchestration/` | 编排交付文档：00 流程图与边表 · 01 契约 · 02 编排 · 03 确认/版本/预算/恢复 · 04 验证与缺口 · 05 使用 |
| `docs/experts/` | 五专家开发链：审计、harness、桥接、记忆检索、RFC、评测与交接（含 `five-agent-followup.md` 总交接） |
| `evidence/` | 分级验证证据（命令/退出码/调用计数/哈希） |
| `frontend/`、`prototypes/` | 工作台前端与沉浸式原型 |
| `run.py`、`start.ps1`、`stop.ps1` | 本地一键启动/停止 |
| `run_mock_demo.py` | 端到端 Mock 演示（主链→试映→局部改稿→导出） |

## 证据分级

已验证：[接口检查]、[Mock 流程]、[业务适配器离线联调]、[真实模型]（MiMo 单次连通与运营官评测）。
待验收：真实内容质量、真实用户试用。五专家本轮优化与验收范围见
[五专家后续开发交接](docs/experts/five-agent-followup.md)。

## 安全提示

- 本仓库**不使用、不保存任何 Key**：代码不读配置文件，真实调用凭据只经运行时进程环境注入。
- 历史模型密钥曾暴露且仍留在 git 历史中：请在 MiMo 控制台**作废旧 Key**（作废后历史明文即失效）。
- 禁止把真实凭据写入需求材料、聊天、源码、备份包或任何会入库的文件。
