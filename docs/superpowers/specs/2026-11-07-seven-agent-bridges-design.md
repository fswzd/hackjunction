# 七角色真实入口桥接设计(P0-A)

日期:2026-11-07｜范围:项目书 v2.0 §11 P0-A 集成基线｜状态:已评审通过

## 1. 目标

把 birthco-local 七个业务 Agent 的真实入口接入编排层 `backend/workflow/five_agent/adapters.py`,替换 7 个 `RealAdapterStub`,使 live 模式可运行真实 MiMo 链路。

完成标准(源自 v2.0 P0-A):各角色声明输入输出、提示词/Schema 指纹、错误和用量;两套测试通过;每角色 1-2 次 live 冒烟留证。

## 2. 现状

- 编排层:`AdapterRouter` 已支持 `agent_modes`(逐角色 mock/live 灰度)与 `reals` 注入;默认 7 个 `RealAdapterStub`,live 模式抛 `AGENT_UNAVAILABLE`,绝不静默回退 Mock(`adapters.py:544-552`)。
- 业务侧:七角色入口同构 `(adapter: ModelAdapter|None, *, mode="mock", model_id=None)`,入口 `run(snapshot: XInput) -> XResult`(观众为 `react(context: AudienceInput) -> AudienceReaction`)。
- 模板:运营官桥接已交付(`birthco-local/backend/adapters/orch_bridge.py` 的 `OperatorTeamAdapter`)与跨层测试(`tests/five_agent/test_operator_entry.py`),本设计复制该模式。
- 模型工厂:birthco-local `adapters/model/factory.py` 已按 agent 解析 .env 单列配置(PR_ANALYST_*/OPERATOR_*/…)。

## 3. 架构与文件布局

```
birthco-local/backend/adapters/          ← 业务侧(与 orch_bridge 并列)
  bridge_common.py       新:共享工具(orchestration_ref_digest/resolve_materials/_usage_dict/
                             _issue/_error_result 从 orch_bridge 抽出,orch_bridge 改 import)
  orch_bridge.py         现有:运营官(行为不变,仅共享工具改 import)
  pr_bridge.py           新:PRAnalystTeamAdapter(analyze_request)
  director_bridge.py     新:DirectorTeamAdapter(draft, revise)
  reviewer_bridge.py     新:ReviewerTeamAdapter(assess_content)
  scout_bridge.py        新:ScoutTeamAdapter(capture_opportunities)
  audience_bridge.py     新:AudienceTeamAdapter(read_segment)
  analyst_bridge.py      新:AnalystTeamAdapter(diagnose_preview)

backend/workflow/five_agent/
  team_entries.py        新:TeamEntry 包装(桥接异常→编排故障语义)+ build_reals(repo, mode, ...)
  adapters.py            改:AdapterRouter.reals 默认保持 7 个 Stub(零依赖);
                            live 经 build_reals() 惰性导入 birthco-local 注册真实桥接
  contracts.py/registry.py/gateway.py/nodes.py/graph.py  不动

tests/five_agent/
  test_pr_entry.py  test_director_entry.py  test_reviewer_entry.py
  test_scout_entry.py  test_audience_entry.py  test_analyst_entry.py   各 1 份
```

关键决策:

1. 桥接模块放业务侧(birthco-local);编排层只经 `team_entries.py` 惰性导入,默认零依赖。
2. 每个桥接构造器同构:`(resolve_material, model_adapter=None, mode="mock", model_id=None)`。
3. live 绝不回退:桥接缺失时 Stub 照旧抛 `AGENT_UNAVAILABLE`。
4. 运营官桥接复用不重写;共享工具抽 `bridge_common.py` 消除重复。

## 4. 逐角色映射

编排侧 input 形状以 nodes.py 构造的 `AgentCall.input` 为准;契约 data 形状以
`resources/agent-interface-seven.json` 与现有 Mock 生成器为参照。

| 角色.action | 编排 input → 业务输入 | 业务输出 → 契约 data |
|---|---|---|
| pr_analyst.analyze_request | `{request_text, material_refs}` → PRAnalysisInput(analysis_requested=True, account_id 取 call.context, client_brief/intake 从 request_text, requirements 透传, materials 解引用) | `{summary, requirements, open_questions, unprovided_business_fields, ready_for_operator, source_refs}` |
| operations_officer.prepare_brief | 现有 orch_bridge(不动) | Brief(不动) |
| content_creator.draft | `{brief_ref}` → DirectorInput(confirmed, brief, brief_hash, frozen_rules=content-rules-v1, style, materials 解引用, reserved_segment_ids 取自 brief edit_scope) | ContentCandidate `{titles, cover_copy, segments}` |
| content_creator.revise | `{base_version_ref, revision_request_ref}` → DirectorInput(base_version_id, base_content_hash, base_content, edit_requests 仅授权段/issue) | Revision `{titles, cover_copy, segments, change_log}` |
| editorial_reviewer.assess_content | `{brief_ref, version_ref}` → ReviewInput(version_id, content_hash, brief, content, materials) | EditorialReview `{issues, requirement_checks, claim_checks, overall}` |
| traffic_scout.capture_opportunities | `{goal, material_refs}` → ScoutInput(research_requested, account 从 context 缺省构造, brief 缺省, materials, max_opportunities) | OpportunitySet `{opportunities[]}` |
| simulated_audience.read_segment | `{persona, current_segment, visible_history}` → AudienceInput;timeout=min(90, 剩余预算换算) | AudienceEvent `{segment_id, action, understanding, question, reaction, interactions, comment_text}`;segment_id 必须等于投影当前段 |
| data_analyst.diagnose_preview | `{preview_ref, metrics_ref}` → AnalystInput(冻结版本+已提交事件+程序指标) | Analysis `{findings[], comparison, next_experiment}`;observation_refs 引用真实事件 id |

统一约束:

1. 素材 id 双向映射:业务内部 id 不泄漏进编排命名空间(orch_bridge 的 id_map 模式)。
2. 引用真实性:审稿 location 必须取自版本真实段 id;finding 必须引用已提交事件。编排层已校验,桥接不伪造。
3. 指纹:桥接记录 input_hash 与提示词/Schema 指纹,入各角色 handoff 文档。
4. usage:业务 usage.total 为 None → `{"status": "unknown", "total_tokens": None}`,绝不记 0。
5. 灰度:agent_modes 逐角色切 mock/live。

## 5. 失败语义(六新桥接统一,循运营官模式)

| 业务侧异常 | 桥接行为 | 编排层语义 |
|---|---|---|
| DomainError(INTERRUPTED) | 抛 BridgeUnknownOutcome | TeamEntry 转 `UnknownResult`(sent=True,不自动重发) |
| 确定性输入拒单(解引用失败/指纹不符/pydantic 失败/越域) | 返回 status=error + issues(cause_hint/next_action),零模型调用 | 已知 error,不重试不烧预算 |
| 其余 DomainError | 同上 error 结果 | 同上 |
| envelope 无 data 无 questions | 防御性 error(不伪造 ok) | 同上 |
| live 模式 adapter/key 缺失 | 构造器 ValueError → 配置错 | 启动时暴露 |

## 6. 注入与模式门控

```
AdapterRouter(repo, mode="mock", agent_modes={...}, reals={...})   # 接口不变
team_entries.build_reals(repo, mode, model_factory=None, resolve_material=None)
    -> dict[agent_id, TeamEntry]
```

- 默认 7 个 Stub,零依赖;mock 测试与 CI 不 import birthco-local。
- live:调用方经 build_reals() 惰性导入 birthco-local,按 agent 从 factory 构造 model_adapter(.env 单列配置),逐角色构造桥接 + TeamEntry。
- mode=live 且某角色桥接未注册 → 该角色 Stub 抛 AGENT_UNAVAILABLE,整链不静默回退。
- 单角色灰度:`agent_modes={"operations_officer": "live"}` 其余 mock。

## 7. 测试(全部 mock 模型、零网络)

每角色 `tests/five_agent/test_<role>_entry.py`:

1. 契约包封:envelope 字段完整(contract_version/request_id/agent_id/action/status/data/questions/issues/usage),schema 校验通过。
2. 输入映射:AgentCall.input → 业务 Input 字段逐一正确;素材 id 双向映射;brief/version ref 解引用。
3. 失败映射:确定性拒单 → error;INTERRUPTED → UnknownResult;PreSend → PreSendFailure。
4. 端到端注入:`AdapterRouter(repo, agent_modes={角色:"live"}, reals={角色:TeamEntry(bridge)})` 跑 OrchestrationDriver 该角色分支。
5. 回归:现有编排 74 + 业务 406 测试全绿。

## 8. 验收清单(逐角色 handoff 文档记录)

| 项 | 证据 |
|---|---|
| 输入输出声明 | 每角色 handoff md:入口函数、输入 schema、输出 envelope、id 映射规则 |
| 提示词/Schema 指纹 | input_hash/prompt hash + 漂移测试 |
| 错误与用量 | 失败映射表 + usage known/unknown 语义 |
| live 冒烟(新 Key) | 每角色 1-2 次真实调用,evidence/ 存结果 JSON(不含 Key);先 pr_analyst + prepare_brief 验证契约,再逐个;总预算 ~10 次内,跑前征得同意 |
| 文档更新 | docs/orchestration/01-contract.md 角色状态 awaiting_owner_handoff → connected |

## 9. 风险

- 六角色业务 Input schema 细节与编排投影可能有出入(尤其 AudienceInput/AnalystInput) — 实现时逐个对齐,差异记入 handoff 缺口清单,不改业务本体。
- live 冒烟烧额度 — 限次、先问。
- birthco-local 与编排层同用 `backend` 命名空间包 — team_entries 惰性导入沿用 test_operator_entry.py 的路径处理,不进模块顶层 import。

## 10. 不在范围

- 业务 agent 本体修改、提示词修改(属角色 owner)
- Flask/SQLite 与编排仓储统一集成(P0-B)
- React 工作台(P0-B)
- 试映改稿产品化 UI(P1-A)
- 契约字段变更;如需变更走契约 owner 冻结流程
