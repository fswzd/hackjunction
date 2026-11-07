# 交接｜traffic_scout 审计修复包 + MiMo 统一接入（2026-11-07）

工作包：架构审计（阶段 1）产出的缺陷修复 F-01..F-05、F-08，外加 live 模型后端统一 MiMo 验证。
验证基线：`evidence/source-snapshot.json`（修复前快照，git_head `809af8a085`）。

## 改动文件

| 文件 | 改动 |
|---|---|
| `backend/workflow/five_agent/repository.py` | 收据查找支持 input_hash 门（同 step_key 不同输入不重放）；新增 `reconcile_orphan_calls`（崩溃遗留 reserved/sent 调用结算补账）；`workflow_step_outputs` 唯一键加入 input_hash |
| `backend/workflow/five_agent/gateway.py` | 重放先算 input_hash 并按 input_hash 查收据；per-run 串行锁（invoke/resend）；invoke 入口结算孤儿调用；删除死代码 `record_reservation` |
| `backend/workflow/five_agent/adapters.py` | `AdapterRouter` 支持 `agent_modes` 按 agent 灰度 mock/live（替换全有或全无） |
| `backend/workflow/five_agent/nodes.py` | `SUB_RUN_TERMINAL` 显式终态映射 + `_finish_sub_run`（scout/pr 子 run 全出口终结）；scout/pr/brief 指纹纳入素材内容 sha256（`_materials_fp`）；诊断落库 `_save_diagnostics`（错误码/issue 编号/字段路径），`error_ref` 指向真实产物；取消/中断上抛不吞入分流 |
| `birthco-local/backend/agents/scout.py` | schema 校验失败携带 `field_errors`（字段路径，不含原文） |
| `birthco-local/backend/adapters/model/mimo.py` | `finish_reason` 归一化：`end_turn`→`stop`（传输边界，全 agent 判定口径） |
| `birthco-local/tests/adapters/model/test_mimo.py` | 补归一化断言 |
| `tests/five_agent/test_audit_fixes.py` | 新增 11 个复现用例（F-01×3、F-02×4、F-03×2、F-04×2、F-05×2） |
| `an.py` | 明文 Key 改为环境变量读取（`MIMO_API_KEY`/`MIMO_BASE_URL`/`MIMO_MODEL_ID`） |
| `.env.example` / `.env` | 凭据环境配置（`.env` 已被 .gitignore 覆盖，不入库） |
| `docs/agent-system/implementation-design/fixtures/contract-cases.json` | 恢复缺失的契约夹具（`tests/contracts/test_schemas.py` 依赖） |

## 需求映射

| 需求 | 落点 |
|---|---|
| F-01 陈旧收据重放 | repository input_hash 门 + nodes 内容hash指纹 + 3 个复现用例 |
| F-02 子 run 泄漏 | `_finish_sub_run` 全出口 + 4 个复现用例 |
| F-03 路由全有或全无 | `agent_modes` 灰度 + 2 个复现用例 |
| F-04 预算崩溃丢账 | `reconcile_orphan_calls` + per-run 锁 + 2 个复现用例 |
| F-05 诊断丢失 | `_save_diagnostics` + scout field_errors + 2 个复现用例 |
| F-08 明文 Key | an.py env 化 + `.env` 环境配置 |
| live 后端统一 MiMo | factory/mimo 已就位；修复 `end_turn` 归一化断层（7 个 agent 只认 `stop`，原实现会让 live 全量 SCHEMA_INVALID） |

## 验证命令及结果

- `python -m pytest tests/ -q`（编排层）→ **68 passed**（含 11 个新增复现用例）
- `cd birthco-local && python -m pytest tests/ -q` → **384 passed**
- MiMo 真实冒烟（MiMoAdapter，mimo-v2.6-pro）→ `status: received, finish: stop, text: 正常`，真实计费 usage 记录（input 14 / output 18）
- Mock 输出（确定性）与真实调用（MiMo）分别如上标记；模型生成产物未用于本轮交付

## 设计偏差（相对修复前行为）

1. **缺料语义**：独立 scout run 的 `needs_input` 终态由 NEEDS_REVIEW 改为 WAITING_INPUT（缺料是等待补充，不是人工复核），问题清单落 `pending_questions_{run}_scout` 产物。
2. **收据唯一键**：`(run_id, step_key, attempt)` → `(run_id, step_key, input_hash, attempt)`；**既有持久化库需迁移**（重建或等效 ALTER），仅新建库自动生效。
3. **中断/取消语义**：traffic 节点不再把 InterruptedUnknown/CancelledError 吞进失败分流，改为上抛；子 run 中断由 gateway 记 INTERRUPTED，父 run 由 driver 记 FAILED(code=INTERRUPTED)——父 run 语义拟在 RFC-2 细化。
4. **finish_reason 线格式**：`end_turn`→`stop` 归一化在适配器边界完成，上游判定口径不变。

## 剩余问题

- F-06（双实现桥接夹具）、F-07（重建 benchmark）、F-09/F-10（契约分层声明）、F-11（失败分支夹具）→ 阶段 2/6 工作包
- Key 已在聊天与 git 历史暴露，建议轮换后仅更新 `.env`
- mock-flow 证据重建（traffic_enabled=true）与 seven-agent.v0.1 接口基线 → 阶段 6
- `check_qwen.py` 为旧后端诊断工具，保留未动
