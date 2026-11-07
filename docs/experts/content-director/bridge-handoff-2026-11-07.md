# 内容主创桥接交接(bridge-handoff-2026-11-07)

- 入口:birthco-local/backend/adapters/director_bridge.py 的 DirectorTeamAdapter.invoke(AgentCall) -> dict
- 编排接线:backend/workflow/five_agent/team_entries.py build_reals(agent_id=content_creator)
- 输入映射:draft/revise 双 action。draft:{brief_ref, material_refs} -> DirectorInput
  (业务 brief_hash 自算,reserved_segment_ids 桥接生成,style 派生);revise:业务本体只接受
  existing_draft 修订流,桥接合成业务 brief(input_mode=existing_draft + edit_scope 取
  revision_request 授权范围)与 draft 素材(段落空行连接,逐字等于 base 段落)
- 输出映射:业务 ContentCandidate/Revision envelope -> 契约 data(model_dump 原样);
  素材/段 id 两命名空间一致,无需回映
- 失败映射:INTERRUPTED/unknown -> UnknownResult(不自动重发);确定性拒单 -> error 结果;
  其余 DomainError -> error 结果;usage 取不回 -> unknown
- Schema 指纹:业务 DirectorInput/Envelope schema 见 birthco-local/tests/contracts/test_hash_and_drift.py
- 测试:tests/five_agent/test_director_entry.py(离线,零模型调用)
- 缺口:业务 mock 只产 body 段,编排规则需 hook+closing → mock 主链 NEEDS_REVIEW
  (需业务 mock 或规则对齐);node_draft 素材指纹已修为正文指纹(F-O4)
