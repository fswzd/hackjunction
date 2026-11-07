# 商单需求分析员桥接交接(bridge-handoff-2026-11-07)

- 入口:birthco-local/backend/adapters/pr_bridge.py 的 PRAnalystTeamAdapter.invoke(AgentCall) -> dict
- 编排接线:backend/workflow/five_agent/team_entries.py build_reals(agent_id=pr_analyst)
- 输入映射:{request_text, material_refs} -> PRAnalysisInput(intake.objective=request_text,
  requirements=PLACEHOLDER_REQUIREMENT;account_id 取 context,length_rule 派生 20000 上限,
  其余 8 个 intake 字段为 null——mock 下因此触发缺必填字段追问)
- 输出映射:PRAnalysisResult.envelope -> 契约 RequestAnalysis data(summary/requirements/
  open_questions/unprovided_business_fields/ready_for_operator/source_refs);
  业务 source 引用(material_N)不回传,source_refs=全部已解析素材的编排层 id(均已被提供)
- 失败映射:INTERRUPTED/unknown -> UnknownResult(不自动重发);确定性拒单(指纹不符/无法解析/
  构造失败)-> error 结果;其余 DomainError -> error 结果;usage 取不回 -> unknown
- Schema 指纹:业务 PRAnalysisInput/Envelope schema 见 birthco-local/tests/contracts/test_hash_and_drift.py
- 测试:tests/five_agent/test_pr_entry.py(离线,零模型调用)
- 缺口:业务把 INTERRUPTED 折叠为 error envelope,桥接无法区分 sent-but-unknown;
  ok 分支在 mock 模式不可达(缺 intake 字段),live 冒烟待验
