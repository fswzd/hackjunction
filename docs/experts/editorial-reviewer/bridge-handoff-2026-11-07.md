# 审稿员桥接交接(bridge-handoff-2026-11-07)

- 入口:birthco-local/backend/adapters/reviewer_bridge.py 的 ReviewerTeamAdapter.invoke(AgentCall) -> dict
- 编排接线:backend/workflow/five_agent/team_entries.py build_reals(agent_id=editorial_reviewer)
- 输入映射:{brief_ref, version_ref, rule_report_ref, material_refs} -> ReviewInput
  (业务 content_hash 自算并与编排 sha256 双重核对;brief/version 经仓库解析)
- 输出映射:业务 EditorialReview.envelope -> 契约 data(model_dump 原样);段 id 两命名空间一致
- 失败映射:INTERRUPTED/unknown -> UnknownResult(不自动重发);确定性拒单(指纹不符等)-> error 结果;
  其余 DomainError -> error 结果;usage 取不回 -> unknown
- Schema 指纹:业务 ReviewInput/Envelope schema 见 birthco-local/tests/contracts/test_hash_and_drift.py
- 测试:tests/five_agent/test_reviewer_entry.py(离线,零模型调用)
- 缺口:mock 规则通过时返回 needs_input(业务语义),live 待验
