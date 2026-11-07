# 模拟观众桥接交接(bridge-handoff-2026-11-07)

- 入口:birthco-local/backend/adapters/audience_bridge.py 的 AudienceTeamAdapter.invoke(AgentCall) -> dict
- 编排接线:backend/workflow/five_agent/team_entries.py build_reals(agent_id=simulated_audience)
- 输入映射:输入即业务 AudienceInput(同 schema,无需派生字段)
- 输出映射:业务 AudienceEvent -> 契约 data(model_dump 原样);段/事件 id 两命名空间一致,无需回映
- 失败映射:unknown(已发送结果未知)-> UnknownResult(不自动重发);failed -> 已知 error 结果
  (error 详情取自 reaction.error);INTERRUPTED -> UnknownResult;usage 取不回 -> unknown
- Schema 指纹:业务 AudienceInput/Event schema 见 birthco-local/tests/contracts/test_hash_and_drift.py
- 测试:tests/five_agent/test_audience_entry.py(离线,零模型调用)
- 缺口:mock 机械 continue(无退出/提问语义,真实逐段退出靠 live 模型);timeout 上限 90(业务约束)
