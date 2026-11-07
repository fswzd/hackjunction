# hackjunction

hackjunction_26.1106 — 多 Agent 自媒体内容系统 · 七角色工作流编排（seven-agent.v0.1）

本仓库是**编排统筹层**：基于 LangGraph 把七个业务 Agent（商单需求分析员 / 运营官 / 内容主创 / 审稿员 /
流量捕捉者 / 数据分析师 / 模拟观众）经统一 `AgentAdapter.invoke(AgentCall) -> AgentResult`
串成可运行 workflow。七角色业务实现由各队员开发，本层只做接口、状态、路由、
预算、闸门、版本与恢复；队员真实入口尚未交接，当前以 Mock 接通全流程。

## 启动（一键）

```powershell
.\start.ps1        # .env 加载 → 数据库迁移 → Flask API(5001) → 前端 Vite(4173)
.\stop.ps1         # 停止
```

- 前端工作台 `http://127.0.0.1:4173`（默认演示适配器，不依赖后端也可体验）
- 后端 API `http://127.0.0.1:5001`（`/api/v1/session` 等；数据目录 `birthco-local\data`）
- 可选参数：`-SkipFrontend` / `-SkipApi` / `-DataDir X:\data`
- 已知边界（评审 F-01）：队列→工作流自动执行 worker 未接入，业务推进用 CLI 与 Mock 演示驱动

## 快速开始（验证）

```text
python -m pip install langgraph==1.1.10 jsonschema pytest
python tools/extract_schemas.py --handoff-root <交接包>/creator-agent-team   # 生成契约资源（已生成）
python -m pytest tests/five_agent -q          # 86 tests（含 F-03 素材指纹回归）
python run_mock_demo.py                       # Mock 全流程 + evidence/
```

默认 Mock 零联网零费用；真实 MiMo（mimo-v2.6-pro）已通过单次连通性验证（凭据见 .env）；
Mock 与真实实现同契约，live 模式绝不回退 Mock。

## 目录

| 路径 | 内容 |
|---|---|
| `backend/workflow/five_agent/` | 契约、Repository、Gateway、投影隔离、规则/指标、Adapter、StateGraph、Driver |
| `tests/five_agent/` | 契约/主链/分支试映改稿/恢复预算/七角色/素材指纹测试（86 项）；birthco-local 组件另有 464 项 |
| `docs/orchestration/` | 交付文档：00 流程图与边表 · 01 契约与接入清单 · 02 编排与 Adapter · 03 确认/版本/预算/恢复 · 04 验证与缺口 · 05 使用说明 |
| `evidence/` | 接口检查、Mock 流程证据（命令/退出码/调用计数/哈希） |
| `tools/` | 契约资源提取、langgraph 探针、冒烟 |
| `run_mock_demo.py` | 端到端 Mock 演示（主链→试映→局部改稿→导出） |

使用方法见 [docs/orchestration/05-usage.md](docs/orchestration/05-usage.md)。

## 证据分级

[接口检查] ✅ · [Mock 流程] ✅ · [真实 Adapter 联调] ❌（运营官桥接已有，装配进 worker 待集成）·
[真实模型] ◐（MiMo 连通性已验证，内容质量未验收）· [真实用户] ❌ —— 详见 [docs/orchestration/04-verification.md](docs/orchestration/04-verification.md)。

## 安全提示

`an.py` 为历史调试脚本，内含明文模型 API Key：请移出仓库并轮换该 Key。
