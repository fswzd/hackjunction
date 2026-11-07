# 运营官桥接交接(bridge-handoff-2026-11-07)

- 入口:birthco-local/backend/adapters/orch_bridge.py 的 OperatorTeamAdapter.invoke(AgentCall) -> dict
- 编排接线:backend/workflow/five_agent/team_entries.py build_reals(agent_id=operations_officer)
- 输入映射:{user_input, input_mode, material_refs, selected_opportunity_ref} -> 业务输入
  (六阶段交付链:prepare_brief→draft→review→export 全链路桥接;memory/memory_aspects 可选注入)
- 输出映射:业务 Result.envelope -> 契约 data;id 回映规则按各阶段契约
- 失败映射:INTERRUPTED/unknown -> UnknownResult(不自动重发);确定性拒单 -> error 结果;
  其余 DomainError -> error 结果;usage 取不回 -> unknown
- Schema 指纹:业务 OperatorInput/Envelope schema 见 birthco-local/tests/contracts/test_hash_and_drift.py
- 测试:tests/five_agent/test_operator_entry.py(离线,零模型调用)
- 缺口:无(orch_bridge 已有,本文件登记桥接复用状态)
