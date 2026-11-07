# 流量捕捉队员桥接交接(bridge-handoff-2026-11-07)

- 入口:birthco-local/backend/adapters/scout_bridge.py 的 ScoutTeamAdapter.invoke(AgentCall) -> dict
- 编排接线:backend/workflow/five_agent/team_entries.py build_reals(agent_id=traffic_scout)
- 输入映射:{goal, material_refs} -> ScoutInput(account/brief 派生缺省:positioning/audience/style
  由目标文本派生并明确标注为派生,不进真实素材;max_opportunities=3)
- 输出映射:业务 OpportunitySet.envelope -> 契约 data(model_dump 原样);素材 id 与编排命名空间
  一致,输出无需回映
- 失败映射:INTERRUPTED/unknown -> UnknownResult(不自动重发);确定性拒单 -> error 结果;
  其余 DomainError -> error 结果;usage 取不回 -> unknown
- Schema 指纹:业务 ScoutInput/Envelope schema 见 birthco-local/tests/contracts/test_hash_and_drift.py
- 测试:tests/five_agent/test_scout_entry.py(离线,零模型调用)
- 缺口:evidence_date 恒 null(材料内分析,无实时检索)
