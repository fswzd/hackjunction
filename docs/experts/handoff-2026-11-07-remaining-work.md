# 总交接｜让 agent 工作链路跑通（2026-11-07）

> 读者：接手本项目剩余开发的队友。你未参与今日会话，本文档自带你需要的全部上下文。
> **头号任务只有一个（§3-T1）：让「创建任务 → 七个 agent 自动工作 → 人工闸门 → 验收」这条链路真正跑通，
> 并且做到任何停摆都能 5 分钟内定位到具体环节**——当前症状是任务停在 DRAFT、七个 agent 全 idle、
> 无从判断卡在哪一环。§4 是为此专门写的排查手册（逐环观测口 + 状态机卡点表 + 症状速查）。
> 状态基线：`main@fd8e51d`（16 条修复+CSRF+FO-1 已入库；BW-1 队列 worker **在途/未落盘**）。

---

## 1. 项目速览

多 Agent 自媒体内容系统（七角色工作流编排 `seven-agent.v0.1`）：

| 层 | 路径 | 职责 |
| --- | --- | --- |
| 编排统筹层 | `backend/workflow/five_agent/` | 契约、LangGraph 状态机、路由、预算、人工闸门、版本/哈希、恢复、收据 |
| 业务角色本体 | `birthco-local/backend/agents/` | 七角色（pr_analyst 商单分析 / operations_officer 运营官 / content_creator 内容主创 / editorial_reviewer 审稿员 / traffic_scout 流量捕捉 / data_analyst 分析师 / simulated_audience 模拟观众） |
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
离线全链参照（七角色本体健康度的黄金对照）：`python run_mock_demo.py --include-scout --output evidence/demo.json` → 应输出 `MOCK FLOW PASS`，trace 为 9 步闸门序列（§4.1 有对照表）。

---

## 2. 当前状态

### 2.1 为什么现在「agent 不工作」——一句话根因

**没有东西消费任务队列**（F-01：队列自动执行 worker 未接入）。链路各环节实测健康：
七角色本体与桥接全通（MOCK FLOW PASS、13 次模型调用全 received、隔离审计 0 违规）、
前端显示链映射完备、人工闸门端点齐全、API/DB 正常——**唯一断点是 worker**。
任务创建后落 `DRAFT`→排队，永无推进者，前端 agent 状态由任务状态推导故全部 idle。
（详见 §4 排查手册的链路拓扑与逐环证据。）

### 2.2 今日已完成（勿重做、勿回退）

- **CSRF 幂等化**（修「真实后端创建任务失败：CSRF token invalid」）：会话派生 token，重复 bootstrap 恒等。回归：`tests/api/test_session_csrf.py`。
- **16 条排查缺陷全修**（4 高危/8 中危/4 低危）+ 回归 `tests/api/test_bugfix_regressions.py`，清单见 §5。
- **前端体验四修**：Modal 焦点、创建任务/Settings 表单防轮询重置、3D 场景稳定+缩放恢复。
- **去 Key 化**：代码不读 `.env`，凭据只经运行时环境注入；仓库无任何 Key。
- **FO-1 资产管线首批落盘**（artifacts 端点 + Assets 页）；五专家后续包合并完成。
- **文档**：内容主创阶段 1 对表审计（`docs/experts/content-creator/03-p0a-baseline-review.md`）、本文档。

### 2.3 在途（接手第一动作：`git status` + `git log --oneline -5` 核对）

修复计划 14 项（BW-1~2 + FO-1~12）由本会话派生的后台流水线在实现。**FO-1 已落盘；BW-1 队列 worker 尚未落盘。**

- 若 `birthco-local/backend/worker/`、`manage.py` 的 worker 子命令、run.py worker 集成已出现 → 直接进 §3-T1 的 runbook 步骤 2；
- 若无落盘且停滞（>1 小时无新文件）→ 按 §3-T1 的规格自行实现。

完整计划（逐项含文件清单与并行顺序，用于核对完整性）：

| ID | 内容 | 关键文件 |
| --- | --- | --- |
| **BW-1** | 【核心】F-01 队列 worker：任务创建即自动推进、七角色亮起 | `birthco-local/backend/worker/{__init__,executor,transitions,bridges}.py`、repository.py、manage.py |
| BW-2 | 任务动作面：退回修改→修订运行闭环、WAITING_INPUT 补给、resume 端点、动作幂等键 | task_actions.py、revisions.py |
| FO-1 | 资产管线：artifacts 读取/下载 + Assets 页真实下载（**已落盘**） | artifacts.py、app.py、api.ts、Assets.tsx |
| FO-2 | live 七角色生产路径接通 build_reals（消除 RealAdapterStub/AGENT_UNAVAILABLE） | adapters.py、driver.py、run_mock_demo.py |
| FO-3 | 分析师 ORCH 口径收口（指标单点/step_key 入 prompt hash/校验单点） | program.py、registry.py、analysis_data.py |
| FO-4 | 六角色 CLI 配置失败保产物 | tools/run_*.py |
| FO-5 | 规则双轨收口 + 审稿员桥接夹具 + code-enforced/prompt-only 两栏声明 | program.py、reviewer_bridge.py |
| FO-6 | traffic_scout 余项：桥接夹具/契约分层/失败分支夹具 | scout_bridge.py、SCOUT.md |
| FO-7 | benchmark/证据基线重建（traffic_enabled=true + 指纹绑定） | run_mock_demo.py、rebuild_interface_baseline.py |
| FO-8 | 编排基建：checkpoint 持久化、双库对账、旧 run 映射 | graph.py、reconcile*.py |
| FO-9 | 前端占位收口：修订意见接 POST /revisions、advanceTask 改刷新、验收只读明示 | api.ts、workspace.ts、TaskDetail.tsx |
| FO-10 | 日历分组口径文案修正 | Calendar.tsx |
| FO-11 | 分析师 S4/S5/S6：记忆台账（盲测隔离）+评测集+契约导出 | analyst_memory.py、eval_analyst.py |
| FO-12 | **内容主创线阶段 2/4/5/6**：harness/记忆+检索/RFC-WP/评测集 | `docs/experts/content-creator/`、creator_memory.py |

顺序：BW-1 最先 → BW-2 → FO-9；FO-2→FO-6→FO-7 与 FO-3→FO-5→FO-11 各自顺序；FO-4/FO-8/FO-10 随时；FO-12 收尾。Lane 间文件集不相交可并行。

### 2.4 测试基线

根 `tests/` 136 passed · `birthco-local/tests/` 499 passed · `npm run typecheck` PASS。低于此基线 = 你引入了回退。

---

## 3. 任务清单

### T1【唯一主任务】让 agent 工作链路跑通（runbook，逐步有验收）

**目标**：创建任务后，agent 链路自动推进、七个角色在工作台真实亮起、人工闸门停得住/续得上、
任何停摆可按 §4 在 5 分钟内定位到环节。

**规格要点**（实现 BW-1 用）：消费循环 = claim 租约（`storage/queue.py` 的 `claim()`，worker_slot 防双跑、
`lease_until` 过期可接管）→ 取 FIFO 最早 QUEUED run（queue_seq）→ 经 P0-A 桥接推进编排（`live_adapters.py`）→
状态落库 → 续约/释放；失败落 `error` 可解释、不吞错、不无限重试；预算内容 run ≤7、收据按 input_hash 幂等；
`manage.py worker` 为入口，`run.py` 一键带上（`--worker` 或默认并起）。

**Runbook（照做，每步写明「你应该看到什么」）**：

| 步骤 | 动作 | 你应该看到（验收点） |
| --- | --- | --- |
| 0 体检 | 跑验证三件套 + `run_mock_demo.py --include-scout` | 全绿 + `MOCK FLOW PASS`（证明七角色本体无恙——把「agent 坏了」和「没人驱动」分开） |
| 1 worker 落地 | 实现/接收 BW-1 + 单测（claim 防双跑、租约接管、失败落库、FIFO） | 新测试入 `birthco-local/tests/`，三件套仍绿 |
| 2 起服务建任务 | `python run.py --detach`；经前端（或 `POST /api/v1/tasks`）建一个真实任务 | 任务落库 `state=DRAFT`→数秒内被领取；`runs.state` 离开 QUEUED |
| 3 观察推进 | 轮询 `GET /api/v1/tasks`；查 `task_events` | 状态按 §4.2 序列推进；每个 agent 调用在 `model_calls` 有 reserved→received 行、usage 计数 |
| 4 前端验证 | 打开工作台看任务详情 | 七个 agent 随状态亮起（queued→waiting、running→working、waiting_approval→review）；Brief 闸门停在「等待确认」 |
| 5 闸门闭环 | `POST /api/v1/tasks/<id>/confirm`（或前端 approve） | 续推到 `READY`；`POST accept` → 终态；revise/cancel 分支各试一次 |
| 6 故障注入 | ①杀 worker 进程→重启（租约过期接管）②同端口再起一个（防双跑应拒/接替）③改坏模型配置→推进 | ①不双跑不丢任务 ②run.py 端口守卫提示 ③落 `error` 可解释、其余任务不受污染 |
| 7 收尾 | 三件套 + typecheck + 全链证据落 `evidence/` | 全绿；证据分级标注（[Mock 流程]/[真实模型]…）→ 提交 |

**验收硬标准（7 条，一条不过就不算跑通）**：
1. 任务创建后**无人工干预**自动离开队列；
2. 状态序列含 `QUEUED→GENERATING→VALIDATING→WAITING_CONFIRMATION`（Brief 闸门）→确认→`READY`；
3. 七个 agent 在前端真实亮起（不是演示模式的假推进）；
4. 闸门停/续正确（confirm/accept/revise/cancel 四分支）；
5. 失败落库可解释（error 字段 + task_events 有轨迹），无静默、无无限重试；
6. 并发安全：租约防双跑、崩溃后可接管、收据幂等；
7. 预算硬闸门生效（内容 run ≤7 次调用，usage_ledger 数字与 model_calls 对得上）。

### T2 提交入库（验收后；规范见 §6-5）

### T3 提醒 owner（不可代做）：MiMo 控制台作废旧 Key（git 历史 615464d 曾明文）；生成新 Key 备用（T5 需要）

### T4 修复计划余项核对（§2.3 表逐项验收；「声称做了没做」的补上）

### T5 真实验收（需 T3 新 Key）：真实 MiMo 内容质量（`run_director.py --live` 单次人工评）→ 真实用户过 UI 走一遍 → 证据按分级归档

---

## 4. 链路排查手册（「为什么不工作」→ 5 分钟定位）

### 4.1 链路拓扑与逐环观测口

任何停摆，**从上往下逐环问「这一环的证据在哪」**，第一个没有证据的环节就是断点：

```
前端显示 ① → API 任务态 ② → 队列/worker ③ → 编排/桥接 ④ → 模型调用 ⑤ → 落库/闸门 ⑥ → 前端闸门动作 ⑦
```

| 环 | 观测口（怎么查） | 健康证据 |
| --- | --- | --- |
| ① 前端显示 | 工作台 agent 卡/任务卡（F12 看 Network 的 /api/v1/tasks 响应） | agent 状态 = `deriveAgents`←任务 status 映射（§4.3 表）；显示 idle ⇔ 任务没动 |
| ② API 任务态 | `GET /api/v1/tasks?account_id=…&limit=10`（带 session cookie） | `state`、`pending_action`、`queue_position`、`usage`、`error` 五个字段是总控台 |
| ③ 队列/worker | DB：`worker_slot(owner,lease_until,epoch)`；进程表：`python -m backend.manage worker`（待建） | `worker_slot.owner` 非空且租约新鲜 = 有 worker 活着；空 = 没人消费队列（当前根因） |
| ④ 编排/桥接 | `task_events` 表（事件流：谁在何时写了什么）；`.run/api.log` / `api.err.log` | 每次推进有 task_created/状态迁移事件；桥接 DomainError 会落 error 不吞 |
| ⑤ 模型调用 | DB：`model_calls`（status: reserved→sent→received/interrupted/…）、`usage_ledger` 计数 | 每个 attempt 恰好一行、恰好入账一次；tokens 与前端 usage 对得上 |
| ⑥ 落库/闸门 | DB：`tasks.state`、`runs.state/phase`、`briefs.confirmed_at`、`content_versions` | 闸门态（WAITING_CONFIRMATION/READY）出现且停住；产物版本/哈希链完整 |
| ⑦ 前端闸门动作 | F12 Network：`POST /confirm`、`POST accept`、`POST /revisions`、`DELETE`（cancel） | 点击后有请求发出且 2xx；任务 state 随之迁移 |

**离线黄金对照**：`run_mock_demo.py --include-scout` 的 trace 是预期序列——
`start_content_run→(select_opportunity)→confirm_brief→accept_delivery→start_preview_run→preview_run→select_findings→start_revision_run→accept_revision`，
每步带 usage 计数（样例证据 `evidence/agent-work-check.json`）。真实链路的推进应与之同构。

### 4.2 状态机卡点表（谁写入 / 正常停留 / 卡住先查什么）

| 状态 | 谁写入 | 正常停留 | 卡住 → 先查 |
| --- | --- | --- | --- |
| DRAFT | task_create（创建即此态） | 秒级 | worker 是否在跑（③）；没有 worker = F-01 根因 |
| QUEUED | 领取前的排队态 | 短 | `queue_seq` 是否被更早任务堵着；租约被僵尸持有（`worker_slot.lease_until`） |
| GENERATING | worker（创作中） | 分钟级 | ⑤ model_calls 有无 reserved 行迟迟不到 received；桥接报错查 ④ |
| VALIDATING | worker（规则/审校） | 分钟级 | 规则失败会走修订；连续失败落 NEEDS_REVIEW |
| WAITING_CONFIRMATION | worker（Brief 闸门） | **等用户**（正常！） | 前端是否显示「等待确认 Brief」；`POST /confirm` 是否发出（⑦） |
| READY | worker（内容验收闸门） | **等用户**（正常！） | 同上；accept/revise/cancel 分支 |
| WAITING_INPUT / NEEDS_REVIEW | 编排（缺料/人工） | 人工 | `pending_action`、pending_questions 产物 |
| 终态（accepted/cancelled/…） | 闸门动作后 | — | — |

> 关键认知：`WAITING_CONFIRMATION`/`READY` 是**设计上的等待**，不是卡死。真正要警惕的是
> 「DRAFT/QUEUED 不动」（没 worker）和「GENERATING 超时不动」（⑤ 无终态行）。

### 4.3 前端显示映射（对照用）

| 任务 status | 前端状态 | agent 卡显示 |
| --- | --- | --- |
| pending（DRAFT） | — | idle（不计入选中） |
| queued | queued | waiting |
| running（GENERATING/VALIDATING） | running | working |
| waiting_approval（WAITING_CONFIRMATION/READY） | waiting_approval | review（pendingAction=confirm_brief/accept_content → 运营官） |
| failed | failed | error |
| completed | completed | completed |

### 4.4 症状速查

| 症状 | 结论 | 处置 |
| --- | --- | --- |
| 七个 agent 全 idle、任务 DRAFT | worker 未接入/未运行 | T1 步骤 1-2；查 worker_slot |
| 任务 QUEUED 长期不动 | worker 死/租约被僵尸占 | 查 worker_slot.lease_until；重启 worker；注意 Windows 端口双绑（§7 坑表） |
| GENERATING 长期不动 | 桥接/模型调用悬挂 | ⑤ model_calls 找 reserved/sent 行；④ 日志找 DomainError |
| 前端闸门不亮 | 状态名不匹配 | 前端只认 `WAITING_CONFIRMATION`/`READY`（⑦/§4.3）；worker 必须产出这套名字 |
| 前端数据与 DB 不一致 | 快照竞态 | 已修 snapshotEpoch 世代号守卫（§5）；若再现查是否有新 set({snapshot}) 点漏接 |
| 创建任务报「CSRF token invalid」 | 会话缓存互踩 | 已修为派生幂等（`test_session_csrf.py` 锁定）；若再现=回退 |
| 一切突然全坏 | 服务没起/双绑冲突 | `netstat -ano \| findstr :5001`；`python run.py`（带端口守卫）；stop.ps1 会连前端一起停 |

---

## 5. 勿回退清单（今日修复；有回归用例的以用例为准）

| 修复 | 文件 | 回归锚 |
| --- | --- | --- |
| CSRF 会话派生幂等 | `birthco-local/backend/security/session.py` | `tests/api/test_session_csrf.py` |
| 「401」整词边界 | `integrations/intake.py` | `test_bugfix_regressions.py` |
| 手动导入先验账号 | `integrations/intake.py` | 同上 |
| 情绪词去重 / coverage clamp | `simulation/audience_feedback.py` | 同上 |
| assess_risk 真实 event_id | `simulation/audience_risk.py` | 同上 |
| 登录失败只回滚新建账号 | `frontend/.../AccountConnect.tsx` | 人工验证 |
| 快照世代号守卫（10 落点） | `frontend/src/store/workspace.ts` | 人工验证 |
| sessionPromise 失败可重试 | `frontend/src/adapters/api.ts` | 人工验证 |
| 3D 场景稳定+缩放恢复 | `headquarters/CourtyardCanvas.tsx`（与并行线平滑缩放方案已合并） | 人工验证 |
| 表单防轮询重置 | `pages/Settings.tsx` + `tasks/NewTaskDialog.tsx` | 人工验证 |
| previews 用量口径 | `api/previews.py` | 与 task_reads 同口径 |
| discard_call 补记账 | `backend/workflow/five_agent/repository.py` | 与 fail_call 同口径 |
| 畸形导入不降级会话 | `api/external_accounts.py` | 400 不动 session_status |
| DELETE 取消登录线程+兜底清理 | `api/external_accounts.py` | 取消事件 |

## 6. 工程红线与约定

1. **去 Key 化**：代码不读 `.env`/不写密钥；live 凭据只经运行时进程环境注入（`$env:MIMO_API_KEY='…'`），用完即弃。
2. **接口保留**：改契约/路由先保兼容；冲突时优化合并而非覆盖（今天发生过 3 次同文件双修，都以合并收场）。
3. **测试门**：提交前双套件 + typecheck 全绿；修缺陷必留复现用例。
4. **证据分级**：[接口检查]/[Mock 流程]/[业务适配器离线联调]/[真实模型]/[真实用户]，未测标 not_measured。
5. **提交规范**：中文标题+分组正文，文末 `Co-Authored-By: Claude Code <noreply@anthropic.com>`；运行产物（analyst-result-*.json 等）不入库。
6. **多会话协调**：同树并行是常态——动共享文件前 `git status` 避让；push 被拒就 `pull --rebase`（今天实际发生：3D 同题双修已合并）。
7. Mock 与 live 同契约；live 失败**绝不回退 Mock**。

## 7. 今日踩过的坑（避免重蹈）

- **useEffect 依赖陷阱**（修三处）：依赖放进随轮询变化的对象/函数身份 → 每轮重跑（抢焦点/清表单/重建 3D）。模式：依赖收窄 + ref 转发 + 一次性门闩。
- **快照竞态**（修）：任何 `set({snapshot})` 前校验 `snapshotEpoch`。
- **CSRF 轮换互踩**（修）：会话 token 必须确定性派生，禁止 bootstrap 随机轮换（前端有多份 session 缓存）。
- **Windows 端口双绑**：werkzeug 允许两实例同监听 5001、请求随机分发（改代码不生效的幽灵现象）。排障先 `netstat -ano | findstr :5001`；run.py 已带 `ensure_port_free` 守卫。
- **stop.ps1 停全部服务**（含前端）；只重启后端用 taskkill 单 PID 后 `python run.py --skip-frontend --detach`。
- **Pydantic Optional 无默认即必填**；**register 幂等**（同 handle 返回既有行）——回滚删除必须先区分新建/既有。

## 8. 明确不做 / 需拍板后另立（防擅自扩权）

MiMo Key 轮换与 git 历史清洗（用户动作）；qwen.py 删除需契约 owner 点名；G-06 prompt hash 冻结申报；G-07 真实反馈导入；G-01/G-05 真实实现证据包归档（代码已通、缺外部验收）；NEEDS_REVIEW 出边语义、未知结果重发通道、WAITING_INPUT 前端表单、日历真实排期、accept-with-edits 语义（产品拍板）；内容主创阶段 3 残余对表（FO-12 只做 2/4/5/6）。

## 9. 上下文索引

编排总文档 `docs/orchestration/00~05` · 五专家总交接 `docs/experts/five-agent-followup.md` · 各角色线 `docs/experts/<role>/`
· 今日交接历史 `docs/experts/content-creator/handoff-2026-11-07-merge-and-keyless.md` · 内容主创阶段 1 `03-p0a-baseline-review.md`
· 七角色验活证据 `evidence/agent-work-check.json` · 本文档配套的状态名硬标准与排查手册即 §3-T1 与 §4。
