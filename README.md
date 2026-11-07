# hackjunction

hackjunction_26.1106 — 多 Agent 自媒体内容系统 · 七角色工作流编排（seven-agent.v0.1）

本仓库是**编排统筹层**：基于 LangGraph 把七个业务 Agent（商单需求分析员 / 运营官 / 内容主创 / 审稿员 /
流量捕捉者 / 数据分析师 / 模拟观众）经统一 `AgentAdapter.invoke(AgentCall) -> AgentResult`
串成可运行 workflow。七角色业务实现由各队员开发，本层只做接口、状态、路由、
预算、闸门、版本与恢复。默认 Mock，运营官、流量捕捉者、内容主创、审稿员和数据分析师支持按角色启用业务适配器。

## 启动（一键）

```powershell
.\start.ps1        # 数据库迁移 → Flask API(5001) → 前端 Vite(4173)
.\stop.ps1         # 停止
```

- 前端工作台 `http://127.0.0.1:4173`（默认演示适配器，不依赖后端也可体验）
- 后端 API `http://127.0.0.1:5001`（`/api/v1/session` 等；数据目录 `birthco-local\data`）
- 可选参数：`-SkipFrontend` / `-SkipApi` / `-DataDir X:\data`
- 已知边界（评审 F-01）：队列→工作流自动执行 worker 未接入，业务推进用 CLI 与 Mock 演示驱动

## 快速开始（验证）

```text
python -m pip install -r birthco-local/requirements-dev.lock langgraph==1.1.10
python -m pytest tests/five_agent -q
python run_mock_demo.py --include-scout --output evidence/mock-flow-with-scout.json
```

默认 Mock 零联网零费用；真实 MiMo（mimo-v2.6-pro）已通过单次连通性验证；
Mock 与真实实现同契约，live 模式绝不回退 Mock。真实调用所需的凭据只经运行时
进程环境变量注入（如 `$env:MIMO_API_KEY`），仓库与磁盘不保存任何 Key。

## 目录

| 路径 | 内容 |
|---|---|
| `backend/workflow/five_agent/` | 契约、Repository、Gateway、投影隔离、规则/指标、Adapter、StateGraph、Driver |
| `tests/five_agent/` | 编排、恢复、预算与五专家业务入口的离线联调 |
| `docs/orchestration/` | 交付文档：00 流程图与边表 · 01 契约与接入清单 · 02 编排与 Adapter · 03 确认/版本/预算/恢复 · 04 验证与缺口 · 05 使用说明 |
| `evidence/` | 接口检查、Mock 流程证据（命令/退出码/调用计数/哈希） |
| `tools/` | 契约资源提取、langgraph 探针、冒烟 |
| `run_mock_demo.py` | 端到端 Mock 演示（主链→试映→局部改稿→导出） |

使用方法见 [docs/orchestration/05-usage.md](docs/orchestration/05-usage.md)。

## 证据分级

[接口检查]、[Mock 流程]、[业务适配器离线联调]已验证。五专家优化和本轮验收范围见 [五专家后续开发交接](docs/experts/five-agent-followup.md)。

## 安全提示

历史模型密钥已报告暴露且仍留在 git 历史中：请在 MiMo 控制台**作废旧 Key**（一步止血）。
本仓库不使用、不保存任何 Key：代码不读取配置文件，真实调用的凭据只经运行时进程
环境变量注入，用完即弃；`.env.example` 仅记录变量名，禁止写入真实值。
