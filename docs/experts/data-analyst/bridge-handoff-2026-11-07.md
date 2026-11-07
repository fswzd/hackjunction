# 数据分析师桥接交接(bridge-handoff-2026-11-07)

- 入口:birthco-local/backend/adapters/analyst_bridge.py 的 AnalystTeamAdapter.invoke(AgentCall) -> dict
- 编排接线:backend/workflow/five_agent/team_entries.py build_reals(agent_id=data_analyst)
- 输入映射:{preview_ref, version_ref, metrics_ref} -> 编排痕迹重建(_rebuild_trace):
  版本 id 回映 ver_+24hex→v_+32hex(content_hash 前 32 位),封面段 cover_v1→cover_<version_id>,
  事件/正文段 id 两命名空间一致原样通过;重建经 validate_report 自洽校验
- 输出映射:业务 Analysis.envelope -> 契约 data;finding 的封面段 id 回映为 cover_v1
- 失败映射:INTERRUPTED/unknown -> UnknownResult(不自动重发);重建失败 -> 确定性 error 结果,
  编排层 node_analysis 软降级为仅指标;usage 取不回 -> unknown
- Schema 指纹:业务 AnalystInput/SimulationReport schema 见 birthco-local/tests/contracts/test_hash_and_drift.py
- 测试:tests/five_agent/test_analyst_entry.py(离线,零模型调用)
- 缺口:内容需恰好 3 标题+非空封面;含 unknown 且后续有事件的痕迹无法重建(业务全局停止规则)
  → 软降级 metrics-only;≥8 正文段不可重建
