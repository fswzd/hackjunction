# 交付物 2 · 五个 Agent 的统一契约和接入清单

契约版本 **seven-agent.v0.1**（由 five-agent.v0.2 演进：新增商单需求分析员，运营官拆回运营官+审稿员；上游快照保留为 agent-interface.json）。边界协议唯一入口
`AgentAdapter.invoke(AgentCall) -> AgentResult`；五个 Agent 不得互调，编排层统一调度。

- 机器契约：[agent-interface-seven.json](../../backend/workflow/five_agent/resources/agent-interface-seven.json)（运行时契约 seven-agent.v0.1；上游 five-agent.v0.2 快照保留为 agent-interface.json）
- 领域 DTO：[domain_schemas.json](../../backend/workflow/five_agent/resources/domain_schemas.json)（自 contracts/schemas.json 提取 24 个 DTO）
- 运行时校验：[contracts.py](../../backend/workflow/five_agent/contracts.py)（`ContractValidators`，与交接包 verify_interfaces.py 同源语义）

## 1. AgentCall（编排 → Agent）

| 字段 | 说明 |
|---|---|
| contract_version | 恒为 `five-agent.v0.2` |
| request_id / agent_id / action | 关联键；action 与 agent_id 强绑定（下表） |
| context | `{account_id, task_id, run_id, step_key, attempt, input_hash}`，服务端生成；**不进入模型 prompt** |
| input | action 所需投影（下表）；额外字段禁止 |
| attempt | 整数 ≥1；布尔拒绝 |
| input_hash | sha256(canonical JSON(冻结可见输入 + prompt/schema 版本))，Gateway 重算核对 |

## 2. AgentResult（Agent → 编排）

| 字段 | 说明 |
|---|---|
| correlation | request_id / agent_id / action / contract_version 必须与待处理调用完全一致 |
| status | `ok`：data 非空且通过输出 DTO 校验、questions 空（**不等于内容合格**）；`needs_input`：≥1 Question，暂停下游；`error`：≥1 Issue、data 为 null、零领域提交 |
| data | action 输出 DTO（下表） |
| usage | `{status: known\|unknown, total_tokens}`；unknown 时 total_tokens=null，**禁止填 0** |

## 3. 八种 action 与七角色绑定

| action | agent_id | 输入（input） | 输出 DTO | 备注 |
|---|---|---|---|---|
| analyze_request | pr_analyst | `{request_text, material_refs}` | RequestAnalysis | 商单/PR 需求整理，运营官之前；缺要求则 needs_input 不交接 |
| draft | content_creator | `{brief_ref, material_refs}` | ContentCandidate | Brief 未确认时编排拒绝进入（零主创） |
| revise | content_creator | `{brief_ref, base_version_ref, revision_request_ref}` | Revision | 限定范围；change_log 须引用已选 finding/issue |
| prepare_brief | operations_officer | `{user_input, input_mode, material_refs, selected_opportunity_ref}` | Brief | 需求整理上下文 |
| assess_content | editorial_reviewer | `{brief_ref, version_ref, rule_report_ref, material_refs}` | EditorialReview | **全新上下文**；看不到主创聊天/自评 |
| capture_opportunities | traffic_scout | `{goal, material_refs}` | OpportunitySet | 记账在独立 scout run；不得虚构实时热点 |
| diagnose_preview | data_analyst | `{preview_ref, version_ref, metrics_ref}` | Analysis | finding 必须引用真实观察事件 |
| read_segment | simulated_audience | `AudienceInput`（domain 整包） | AudienceEvent | 仅四字段，见 §5 |

引用类型：`Ref={id, sha256}`；`BriefRef={task_id, brief_version≥1, brief_hash}`（无独立 brief id）。
Repository 对每个引用重新校验归属与冻结 hash；语法合法不授予权限。

## 4. 接入清单（integration-handoff）

各队员按下表提交；编排侧已备 Mock 与契约测试，收到真实入口后只需替换 Adapter。

| 能力 owner | agent_id / action | 交付内容（每 action ≥1 例 + needs_input/error） | 状态 | 缺口 |
|---|---|---|---|---|
| 商单需求分析队员 | pr_analyst / analyze_request | 同上；引文/来源映射规则 | **bridge_connected** | mock 联调 ✅(113 编排测试);live 冒烟见 evidence/live-smoke.json;真实主链全链路验收属 P0-C |
| 内容主创队员 | content_creator / draft, revise | 入口（Python 符号或受控 HTTP）、版本、prompt/schema hash、调用次数/重试、usage、凭据来源、失败分类、依赖锁、Mock | **bridge_connected** | mock 联调 ✅(113 编排测试);live 冒烟见 evidence/live-smoke.json;真实主链全链路验收属 P0-C |
| 运营官队员 | operations_officer / prepare_brief | 同上 | **bridge_connected** | mock 联调 ✅(113 编排测试);live 冒烟见 evidence/live-smoke.json;真实主链全链路验收属 P0-C |
| 审稿员队员 | editorial_reviewer / assess_content | 同上；须申报内部调用次数（禁止隐藏第二次模型调用） | **bridge_connected** | mock 联调 ✅(113 编排测试);live 冒烟见 evidence/live-smoke.json;真实主链全链路验收属 P0-C |
| 流量捕捉队员 | traffic_scout / capture_opportunities | 同上；联网能力须显式配置授权 | **bridge_connected** | mock 联调 ✅(113 编排测试);live 冒烟见 evidence/live-smoke.json;真实主链全链路验收属 P0-C |
| 数据分析队员 | data_analyst / diagnose_preview | 同上；finding/观察引用规则 | **bridge_connected** | mock 联调 ✅(113 编排测试);live 冒烟见 evidence/live-smoke.json;真实主链全链路验收属 P0-C |
| 观众模拟队员 | simulated_audience / read_segment | 同上；单段单会话步进 | **bridge_connected** | mock 联调 ✅(113 编排测试);live 冒烟见 evidence/live-smoke.json;真实主链全链路验收属 P0-C |
| 编排队员（本交付） | 统一 Adapter / StateGraph / Gateway / Repository / 预算 / 恢复 | 本仓库 `backend/workflow/five_agent/` + 测试 + 证据 | **mock_connected**（接口+Mock 联调完成） | 真实 Adapter 联调待 owner 交接 |
| 工程基础（A02a owner） | Flask API / worker / 依赖锁 | create_app、队列、幂等键、worker 租约 | 待接入 | 本包只有驱动层，无 HTTP 层 |
| 存储（A02b owner） | 迁移 002（binding/gate/command/step_outputs 表） | 与本 Repository DDL 对齐 | 待接入 | 当前 SQLite DDL 内嵌于 repository.py |
| checkpoint（LG02 owner） | langgraph-checkpoint-sqlite 集成 | graph.sqlite 持久 checkpoint | 待接入 | 本机未安装该插件，现用 MemorySaver |
| 前端（A05c/A08b） | 闸门/版本/费用展示 | 不暴露 thread_id/内部 Command | 待接入 | 未开工 |

接入顺序（沿用交接单判定）：协议接入(mock_connected) → 主链接入(p0_connected) →
可选分支 → 真实 Adapter 逐个替换（同契约测试，标 live）→ 独立集成验收(integrated)。

## 5. 上下文隔离（每角色可见范围）

| 角色 | 可见 | 禁止 |
|---|---|---|
| content_creator | 已确认 Brief、允许材料、scope、指定 findings/issue | 确认权、版本指针、调用他人 |
| pr_analyst | 客户简报、授权材料 | 编造事实、自动批准、写正文 |
| operations_officer（prepare_brief） | 用户需求、材料、选中机会 | 其他任务聊天、订单/支付 |
| editorial_reviewer（assess_content） | Brief、原材料、当前稿、规则报告 | **主创聊天/自评**（结构上不存在于 state） |
| traffic_scout | 授权材料、账号定位、目标 | 未授权联网、虚构热点 |
| simulated_audience | persona、当前段、已读前缀、自身既往反应（四字段） | 未来段、其他观众、创作者目标/评分、GraphState |
| data_analyst | 冻结版本、逐段事件、程序指标、条件差异 | 自算指标覆盖代码值、把模拟称真实流量 |

实现：[projection.py](../../backend/workflow/five_agent/projection.py)（构建投影 + 未来文本/跨会话泄漏断言）；
Mock 记录 `model_visible_input`（仅 call.input）与 `context_seen_by_model=False`，供测试断言。
