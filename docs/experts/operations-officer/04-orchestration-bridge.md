# 运营官编排接入与桥接设计（阶段 3 交付）

- schema: `hackjunction.team-agent-orchestration.handoff.v1`
- 落点：`birthco-local/backend/adapters/orch_bridge.py`（桥接夹具+真实入口）、`backend/workflow/five_agent/`（契约语义闸、投影/节点/生成器对齐、reals 注入钩子）
- 验证：`birthco-local` 397 passed、`tests/five_agent` 74 passed（2026-11-07）；证据分级 **[真实 Adapter 联调]**（桥接真实入口 + 本体校验 + AgentAdapter 契约进出，模型为 mock；[真实模型] 属阶段 6）

## 1. 边界与责任（一卡一 owner）

| 卡 | owner | 文件范围（互斥） | 状态 |
|---|---|---|---|
| 桥接夹具+真实入口 | 运营官 | `birthco-local/backend/adapters/orch_bridge.py`、`tests/adapters/test_orch_bridge.py` | merged（本地） |
| prepare_brief 契约语义闸 | 运营官（契约共管，**待契约 owner 追认**） | `contracts.py`、`resources/agent-interface-seven.json` | merged（本地，见 §5） |
| 投影/节点/生成器对齐 | 运营官 | `projection.py`、`nodes.py`（node_brief）、`adapters.py`（gen_brief + reals 钩子） | merged（本地） |
| 集成锁定 | 运营官 | `tests/five_agent/test_operator_entry.py` | merged（本地） |

## 2. 桥接语义（F-O1~F-O6 落点）

| 审计项 | 落点 | 语义 |
|---|---|---|
| F-O1 | `OperatorTeamAdapter.invoke`（唯一校验入口=本体 run）+ `ContractValidators._check_prepare_brief`（第二道闸，mock/真实同受） | 冻结比对 + 越域引用 + route P0 双层拦截 |
| F-O2 | 本体 `open_questions ⇒ needs_input` 原语义采纳为唯一协议；编排语义闸拒绝 ok+open_questions | mock 生成器不再产出本体不支持的形状 |
| F-O3 | 投影可选 `edit_scope` 字段（契约 opt）；缺 scope 的旧稿流 = needs_input（与本体一致） | 旧稿通道可达；未授权修改不可被模型发明 |
| F-O4 | `resolve_materials` 解引用 + 指纹复算（`sha256(canonical({"text"}))`）；`material_snapshot` ID ↔ 编排 ID 双向映射，Brief.material_ids 回编排命名空间 | 素材溯源不断链；下游 draft 按仓库 ID 解析不破 |
| F-O5 | `input.requirements`（原始 requirement_id+text）结构化传入（node_brief 从 pr_analysis artifact 取）；冻结=集合相等 | 客户硬性要求带原编号进 Brief，可追溯 |
| F-O6 | **确认 CAS 唯一权威 = 编排层 `save_brief` 的 `object_hash(payload)`**（confirm_brief 闸门与 CAS 用它）；本体 `proposal_hash` 仅标识本次建议、绝不可当确认指纹；`hashing.brief_hash(frozen_rules)` 为独立流预留、启用需契约升级 | 三哈希概念收敛为「一权威一标识一预留」 |

**冻结语义（桥接流）**：`input_mode` 恒冻；结构化 `requirements` 冻（集合相等）；`edit_scope` 提供即冻（target/flags 逐字、preserve ⊇ 输入）。`objective/audience/platform/length_rule` 在自由文本流为推断字段——模型整理、用户在 confirm_brief 闸门看到后确认；独立运行（结构化填单）仍是全字段冻结。

**失败映射**：`INTERRUPTED` → `BridgeUnknownOutcome`（sent-but-unknown，显式重发需成本确认，绝不自动重发）；其余 DomainError → 已知 error 结果（issues 带 cause_hint/next_action，无自动重试）；失败调用取不回 usage 时记 `unknown`（不伪造 0）。

## 3. 集成方式（单角色灰度）

`AdapterRouter(..., agent_modes={"operations_officer": "live"}, reals={"operations_officer": TeamEntry(bridge)})`：
- `reals` 注入钩子替换 `RealAdapterStub`；`agent_modes` 单角色路由（live 绝不回退 mock）；
- 桥接 `resolve_material` 由调用方注入（授权范围=本 task 的仓库素材）；
- `TeamEntry` 薄包装负责 `BridgeUnknownOutcome→UnknownResult`、`BridgePreSendFailure→PreSendFailure` 的故障语义翻译。

## 4. 预算与幂等

- prepare_brief 计 content run normal 预算（5+1+2）；补件重入=新 step_key=新调用（既有语义，F-O7 补件轮次限额排 RFC-2）。
- 收据幂等：`input_hash` 绑定投影+prompt_schema_version，回执比对 input_hash 防陈旧重放（既有护栏）；prompt hash 申报后冻结（G-06，03-harness §7 公式）。

## 5. 契约变更记录（待 owner 追认）

1. `input_types.prepare_brief` 增加可选 `requirements`（`opt:Requirement[]`）与 `edit_scope`（`opt:EditScope|null`）；`contracts.py` 输入构造支持 `opt:` 前缀（可选属性）。
2. `validate_result` 新增 `prepare_brief` 动作语义闸（`_check_prepare_brief`）。
3. `AdapterRouter.__init__` 新增 `reals` 注入参数（默认空=行为不变）。
4. `gen_brief` mock 生成器对齐：结构化 requirements 原样透传、旧稿缺 scope → needs_input、edit_scope 透传。

以上均为附加/向后兼容变更（旧输入形状不带新键仍合法）；建议随七角色契约冻结批次正式入册。

## 6. 剩余问题

- F-O7（补件轮次预算策略）、F-09 评测覆盖（阶段 6）。
- 仓库素材行 `kind` 与 MaterialInput 枚举不一致（现由桥接归一：枚举外一律 source_text，旧稿流首素材=existing_draft）——素材 kind 语义上收口需仓储层配合。
- [真实模型] 验收（MiMo live）留待阶段 6 评测集就绪后执行（去敏夹具先行）。
