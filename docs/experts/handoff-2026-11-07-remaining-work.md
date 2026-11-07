# 总交接｜剩余工作全清单（2026-11-07）

> 读者：接手本项目剩余开发的队友。你未参与今日会话，本文档自带你需要的全部上下文。
> 状态基线：`main@c2501eb`（含五专家包合并、去 Key 化、CSRF 修复、16 条排查修复——**尚未提交**，见 §2）。

---

## 1. 项目速览

多 Agent 自媒体内容系统（七角色工作流编排 `seven-agent.v0.1`）：

| 层 | 路径 | 职责 |
| --- | --- | --- |
| 编排统筹层 | `backend/workflow/five_agent/` | 契约、LangGraph 状态机、路由、预算、人工闸门、版本/哈希、恢复、收据 |
| 业务角色本体 | `birthco-local/backend/agents/` | 七角色（pr_analyst 运营官前的商单分析 / operations_officer 运营官 / content_creator 内容主创 / editorial_reviewer 审稿员 / traffic_scout 流量捕捉 / data_analyst 分析师 / simulated_audience 模拟观众） |
| 业务服务 | `birthco-local/backend/` | Flask API、SQLite 持久化/台账、试映模拟、平台账号（抖音/小红书） |
| 模型接入 | `birthco-local/backend/adapters/model/` | 统一 MiMo 适配器（mimo-v2.6-pro，Anthropic 兼容）+ 按 agent 解析工厂 |
| 前端工作台 | `frontend/` | Vite + React + zustand；2D 工作台 + 3D 总部 |
| 专家线文档 | `docs/experts/` | 各角色开发链产物（审计/harness/桥接/记忆/RFC/评测/交接） |

**启动**：`python run.py`（推荐；迁移→API 5001→前端 4173）或 `.\start.ps1`；停止：Ctrl+C 或 `.\stop.ps1`。
**验证三件套**：
```powershell
python -m pytest tests/ -q                      # 编排层（当前 136 passed）
cd birthco-local; python -m pytest tests/ -q    # 业务层（当前 499 passed）
cd ..\frontend; npm run typecheck               # 0 错误
```
全链模拟（七角色离线跑一遍创造任务流程）：`python run_mock_demo.py --include-scout --output evidence/demo.json`（应输出 `MOCK FLOW PASS`）。

---

## 2. 当前状态（接手时先核对）

### 2.1 今日已完成（勿重做、勿回退）

- **CSRF 幂等化**：`GET /api/v1/session` 改为会话派生 token（重复 bootstrap 恒等），修复「真实后端创建任务失败：CSRF token invalid」。回归用例：`birthco-local/tests/api/test_session_csrf.py`。
- **16 条排查缺陷全修**（4 高危/8 中危/4 低危，见 §4 勿回退清单）+ 回归用例 `birthco-local/tests/api/test_bugfix_regressions.py`。
- **前端体验四修**：Modal 初始焦点优先输入框+effect 只在开合跑一次；创建任务表单防轮询重置；Settings 表单同型门闩；3D 场景 onReady 稳定化+缩放恢复。
- **去 Key 化**：代码不读任何 `.env`，真实凭据只经运行时进程环境变量注入（`$env:MIMO_API_KEY='…'`）；仓库无任何 Key。
- **内容主创阶段 1 对表审计**：`docs/experts/content-creator/03-p0a-baseline-review.md`。
- **五专家后续包合并**：experiment_ledger / live_adapters / output_contract / material_retrieval / 契约同步（详见 `docs/experts/five-agent-followup.md`）。

### 2.2 在途（接手后第一件事：核对是否已落盘）

一个后台修复流水线（本会话派生）正在实现下列计划。**先跑 `git status` + `git log --oneline -5`**：

- 若 BW-1（队列 worker）相关文件已出现（`birthco-local/backend/worker/`、`manage.py worker`、run.py 集成）→ 进入 §3-T1 的**验收**步骤；
- 若长期无落盘（>1 小时无新文件）→ 按 §3-T1 的规格**自行实现**。

修复计划全文（12+2 项，按此执行与核对）：

| ID | 内容 | 关键文件 |
| --- | --- | --- |
| **BW-1** | 【核心】F-01 队列 worker：任务创建即自动推进、七角色亮起 | `birthco-local/backend/worker/{__init__,executor,transitions,bridges}.py`、repository.py、manage.py |
| BW-2 | 任务动作面：退回修改→修订运行闭环、WAITING_INPUT 补给、resume 端点、动作幂等键 | task_actions.py、revisions.py |
| FO-1 | 真实模式资产管线：artifacts 读取/下载端点 + Assets 页真实下载 | artifacts.py、app.py、api.ts、Assets.tsx |
| FO-2 | live 七角色生产路径接通 build_reals（消除 RealAdapterStub/AGENT_UNAVAILABLE 占位） | adapters.py、driver.py、run_mock_demo.py |
| FO-3 | 分析师 ORCH 口径收口（指标单点/step_key 入 prompt hash/校验单点） | program.py、registry.py、analysis_data.py、analyst.py |
| FO-4 | 六角色 CLI 配置失败保产物 | tools/run_*.py |
| FO-5 | 规则双轨收口 + 审稿员桥接夹具 + code-enforced/prompt-only 两栏声明 | program.py、reviewer_bridge.py、REVIEWER.md |
| FO-6 | traffic_scout 余项：桥接夹具/契约分层/失败分支夹具 | scout_bridge.py、SCOUT.md |
| FO-7 | benchmark/证据基线重建（traffic_enabled=true + 接口基线指纹绑定） | run_mock_demo.py、rebuild_interface_baseline.py |
| FO-8 | 编排基建：G-02 checkpoint 持久化（SqliteSaver）、G-04 双库对账、G-08 旧 run 映射 | graph.py、reconcile*.py |
| FO-9 | 前端占位收口：修订意见接 POST /revisions、advanceTask 守卫改刷新、验收只读明示 | api.ts、workspace.ts、TaskDetail.tsx |
| FO-10 | 日历分组口径文案修正 | Calendar.tsx |
| FO-11 | 分析师 S4/S5/S6：记忆台账（盲测隔离）+评测集+契约导出 | analyst_memory.py、eval_analyst.py |
| FO-12 | **内容主创线阶段 2/4/5/6**：harness/记忆+检索/RFC-WP/评测集 | `docs/experts/content-creator/03~09`、creator_memory.py |

并行规则（计划原文）：Lane 之间文件集两两不相交可并行；Lane 内部按序（共享文件防互相覆盖）。
顺序：BW-1 最先 → BW-2 → FO-9；FO-1 ∥ FO-4 ∥ FO-8 ∥ FO-10 可随时；FO-2→FO-6→FO-7 顺序；FO-3→FO-5→FO-11 顺序；FO-12 收尾。

### 2.3 未提交改动（重要）

工作树当前**未提交**（`git status` 可见）：CSRF 修复 3 文件、16 条排查修复约 12 文件、回归测试 2 文件、内容主创 03 审计、以及在途实现的落盘。**全部完成 §3-T1 验收后一次性提交**（规范见 §5）。

### 2.4 测试基线

根 `tests/` 136 passed · `birthco-local/tests/` 499 passed · `npm run typecheck` 0 错误。低于此基线 = 你改动引入回退。

---

## 3. 任务清单（按序执行）

### T1【最高优先】队列 worker（F-01）——「agent 不工作」的根治

**现象**：任务创建后永远停在 `DRAFT`/队列，七个 agent 全 idle。前端 agent 状态由任务状态推导（`deriveAgents`），任务不动则全不亮。真实模式前端禁止手动推进（设计留给 worker）。

**验收硬标准（端到端，逐条过）**：
1. `python run.py --detach` 起服务；用前端或脚本创建一个真实任务；
2. worker 自动领取（`storage/queue.py` 的 worker_slot 租约：**防双跑、崩溃后租约过期可接管**）；
3. 任务状态按序推进：`QUEUED → GENERATING → VALIDATING → … → WAITING_CONFIRMATION`（Brief 闸门停下）→ 用户 `POST /confirm` → 续推 → `READY`（内容验收闸门）→ `POST accept` → 终态；
4. 前端工作台七个 agent 随状态亮起（queued→waiting / running→working / waiting_approval→review）；
5. 失败路径：模型/桥接失败落库 `error` 并停在可解释状态，不吞错、不无限重试；
6. 预算：内容 run 总调用 ≤7（registry BUDGETS），收据按 input_hash 幂等；
7. 双套件 + typecheck 全绿，新增 worker 测试入 `birthco-local/tests/`。

实现规格要点（若需自行实现）：消费循环 = claim 租约 → 取 FIFO 最早 QUEUED run → 经 P0-A 桥接（`live_adapters.py`/orch_bridge）推进编排 → 状态落库 → 释放/续约；`manage.py worker` 为入口，run.py 一键带上（参考 `storage/queue.py` 既有 `claim()` 语义）。

### T2 提交入库

全部验收后一次性提交推送（`origin/main`）。规范见 §5。

### T3 提醒 owner（不可代做）

- **MiMo 控制台作废旧 Key**（`sk-cwpb…`）：该 Key 曾在 git 历史（commit 615464d）与聊天明文暴露。新 Key 只经运行时环境注入。
- 生成新 Key 备用（T6 需要）。

### T4 修复计划余项核对

按 §2.2 表逐项核对落盘与验收（每项有 tests 文件名可对照）。任何「计划声称做但没做」的项补上。

### T5 内容主创线阶段 2/4/5/6（= FO-12）

参照运营官线现成模板（`docs/experts/operations-officer/03-harness.md / 05-memory-retrieval.md / 06-rfc-1.md / 07-rfc-2.md / 09-eval.md`）产出 `docs/experts/content-creator/` 同名阶段文档 + `creator_memory.py`（落 `memories` 表、起草前 ≤3 轮检索、supersede 链、盲测隔离）。阶段 3（编排桥接）残余需与 owner 对表后另立——**不要擅自扩**。

### T6 真实验收（需 T3 新 Key）

1. 新 Key 运行时注入：`$env:MIMO_API_KEY='<新Key>'`；
2. 真实 MiMo 内容质量验收：单角色 `cd birthco-local; python tools/run_director.py --input examples/director-task.json --output out.json --live`（单次、不重试），人工评文案质量；
3. 真实用户试用（[真实用户] 级证据）：经 UI 走一遍创建→确认→验收；
4. 证据按分级归档：[接口检查]/[Mock 流程]/[业务适配器离线联调]/[真实模型]/[真实用户]，`evidence/` 落 JSON（命令/退出码/哈希/用量）。

### T7 明确不做（需 owner/产品拍板，见 §7）

---

## 4. 勿回退清单（今日修复，有回归用例的以用例为准）

| 修复 | 文件 | 回归锚 |
| --- | --- | --- |
| CSRF 会话派生幂等 | `birthco-local/backend/security/session.py` | `tests/api/test_session_csrf.py` |
| 「401」整词边界 | `integrations/intake.py` | `test_bugfix_regressions.py::test_auth_error_...` |
| 手动导入先验账号 | `integrations/intake.py` | `...::test_import_manual_...` |
| 情绪词去重 | `simulation/audience_feedback.py` | `...::test_negative_keywords_...` |
| assess_risk 真实 event_id | `simulation/audience_risk.py` | `...::test_assess_risk_...` |
| 登录失败只回滚新建账号 | `frontend/.../AccountConnect.tsx` | 人工验证 |
| 轮询世代号守卫 | `frontend/src/store/workspace.ts`（snapshotEpoch，10 落点） | 人工验证 |
| sessionPromise 失败可重试 | `frontend/src/adapters/api.ts` | 人工验证 |
| 3D 场景不重建+缩放恢复 | `headquarters/Headquarters3D.tsx`+`CourtyardCanvas.tsx` | 人工验证 |
| 表单防轮询重置 | `pages/Settings.tsx`+`tasks/NewTaskDialog.tsx` | 人工验证 |
| previews 用量口径 | `api/previews.py` | 与 task_reads.summary 同口径 |
| discard_call 入账 | `backend/workflow/five_agent/repository.py` | 与 fail_call 同口径 |
| 导入畸形载荷不降级会话 | `api/external_accounts.py` | 400 且不动 session_status |
| DELETE 取消登录线程+兜底清理 | `api/external_accounts.py` | 取消事件 |

---

## 5. 工程红线与约定

1. **去 Key 化**：代码不读 `.env`/不写密钥；live 凭据只经运行时进程环境注入，用完即弃；`.env.example` 仅变量名参考。任何 PR 不得引入密钥或文件读取凭据。
2. **接口保留**：改公共契约/接口（`contracts/`、`resources/*.json`、openapi、API 路由）先保兼容；冲突时优先优化合并而非覆盖（历史多次并行覆盖事故）。
3. **测试门**：提交前双套件 + typecheck 全绿；修缺陷必须留复现用例（对齐 `test_bugfix_regressions.py` 模式）。
4. **证据分级**：报告/归档必须区分 [接口检查]/[Mock 流程]/[业务适配器离线联调]/[真实模型]/[真实用户]；未测数字标 not_measured。
5. **提交规范**：中文标题+分组正文，文末 `Co-Authored-By: Claude Code <noreply@anthropic.com>`；运行产物（`analyst-result-*.json`、`probe-raw-output.json`）不入库。
6. **多会话协调**：多人/多会话同树是常态——动共享文件前 `git status` 避让在途改动；一卡一 owner。
7. Mock 与 live 同契约；live 失败**绝不回退 Mock**。

---

## 6. 今日踩过的坑（避免重蹈）

- **useEffect 依赖陷阱**（已修三处）：依赖放进会随轮询变化的对象/函数身份 → 每次轮询重跑 effect（抢焦点/清表单/重建 3D）。模式：依赖收窄 `[open]` + ref 转发 + 一次性门闩。
- **快照竞态**（已修）：`set({snapshot})` 前必须校验世代号（`snapshotEpoch`），否则轮询旧数据覆盖刚写入的结果。
- **CSRF 轮换互踩**（已修）：会话 token 必须确定性派生（同会话恒等），禁止每次 bootstrap 随机轮换——前端有多份 session 缓存。
- **Windows 端口双绑**：werkzeug SO_REUSEADDR 允许两个实例同监听 5001、请求随机分发（改代码不生效的幽灵现象）。run.py 已带 `ensure_port_free` 守卫；排障先 `netstat -ano | findstr :5001`。
- **stop.ps1 会停全部服务**（含前端）；只想重启后端用 `taskkill /T /F /PID <api pid>` 后 `python run.py --skip-frontend --detach`。
- **Pydantic `Optional` 无默认值即必填**（`question=None` 要显式传）。
- **register 幂等**：同 handle 返回既有行——任何「失败回滚删除」必须先区分新建/既有。

---

## 7. 明确不做 / 需拍板后另立工作包

（摘自修复计划 out_of_scope，完整语义以计划原文为准）

- MiMo Key 轮换与 git 历史清洗（用户动作，见 T3）；`qwen.py/check_qwen.py` 删除需契约 owner 点名确认（现 deprecated 保留）。
- G-06 prompt/schema hash 冻结申报；G-07 真实反馈导入与复盘（需显式授权）。
- G-01/G-05 真实实现证据包与 live 用量证据：代码侧已通（P0-A+FO-2），缺的是**外部验收归档**。
- NEEDS_REVIEW 出边语义（重派/改派/归档）：产品拍板前该态仅可 cancel。
- 未知结果显式重发通道（confirm_interrupted_resend 的成本风险语义）：产品定义后另立。
- WAITING_INPUT 补给/恢复的**前端闸门 UI**：API 端点 BW-2 提供，表单属产品交互设计。
- 日历真实排期（planned_at 契约）、「小改后验收」（accept-with-edits 语义）：产品契约拍板。
- 内容主创阶段 3 残余对表：与 owner 确认后另立（FO-12 只做 2/4/5/6）。

---

## 8. 联系与上下文索引

- 编排总文档：`docs/orchestration/00~05`；五专家总交接：`docs/experts/five-agent-followup.md`；各角色线：`docs/experts/<role>/`。
- 今日会话遗留：`docs/experts/content-creator/handoff-2026-11-07-merge-and-keyless.md`（合并+去 Key 阶段交接）、`03-p0a-baseline-review.md`（内容主创阶段 1）。
- 全链模拟证据范例：`evidence/agent-work-check.json`（七角色逐个验活、隔离审计 0 违规）。
