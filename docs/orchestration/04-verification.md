# 交付物 5+6 · Mock 流程验证结果、证据分级与未接入缺口

## 0. 证据分级（全项目统一标记）

| 级别 | 含义 | 本交付状态 |
|---|---|---|
| [接口检查] | 离线 schema/夹具校验，无 Agent/模型/图执行 | ✅ 已发生 |
| [Mock 流程] | 五个 Mock Agent 走通编排（dev 模式，无真实模型） | ✅ 已发生 |
| [真实 Adapter 联调] | 队员真实入口替换后同契约测试 | ❌ 未发生（awaiting_owner_handoff） |
| [真实模型] | live 模型调用与真实用量 | ❌ 未发生 |
| [真实用户] | 真实用户经 UI/API 的确认与反馈 | ❌ 未发生 |

**不虚报**：以下全部验证均为 [接口检查] 或 [Mock 流程]。Mock 成功不代表真实联调成功；
“模拟观众的模型模拟”与“开发用 Mock”是两回事（前者是业务角色行为，后者是队员实现替身）。

## 1. 运行记录（命令 / cwd / 退出码）

cwd = `E:\hackjunction\hackjunction`（本仓根）

| 命令 | 退出码 | 产物 | 级别 |
|---|---|---|---|
| `python docs/.../five-agent/tools/verify_interfaces.py --output evidence/baseline-interface-checks.json` | 0（17 fixtures PASS） | evidence/baseline-interface-checks.json | [接口检查] |
| `python tools/probe_langgraph_interrupt.py` | 0（6 checks PASS，langgraph 1.1.10） | evidence/probe-langgraph-interrupt.json | [接口检查] |
| `python tools/extract_schemas.py --handoff-root <交接包>` | 0（24 DTO） | backend/.../resources/ + provenance.json | [接口检查] |
| `python -m pytest tests/five_agent -q` | 0（**47 passed**） | evidence/test-run.txt、evidence/test-suite-report.json（含实现文件 sha256 清单） | [Mock 流程] |
| `python run_mock_demo.py` | 0 | evidence/mock-flow-evidence.json | [Mock 流程] |

## 2. Mock 全流程实测摘要（run_mock_demo.py）

| 步骤 | 状态 | 闸门 | 调用/用量 |
|---|---|---|---|
| start_content_run | WAITING | confirm_brief | brief ×1（正常） |
| confirm_brief | WAITING | accept_delivery | +draft ×1 +assess ×1 → 正常 3 |
| accept_delivery | READY（V1 accepted） | — | 3 正常 / 0 重试 / 751 tokens（合成） |
| start_preview_run | WAITING | preview_conditions | 0 |
| preview_run（3 persona） | WAITING | select_findings | 7 观众 + 1 分析；1 次 unknown（超时会话 incomplete） |
| select_findings（选 1 finding） | READY | — | 未选则零改稿（另行测试） |
| start_revision_run | WAITING | accept_delivery | revise ×1 +assess ×1 = 2 正常 |
| accept_revision | READY（V2 accepted） | — | V1 hash 不变、仍可下载（evidence 中 v1_preserved=true） |

观众行为实测：p_exit_first 在 cover exit（1 事件、会话 exited）；p_full 读完 4 段（completed）；
p_timeout_mid 第 1 段后 unknown（incomplete，事件保留，无伪造 exit）。
分析 finding 的 observation_refs 全部是真实事件 id（程序校验，非法引用会软降级为缺失分析）。

## 3. 验收项 → 测试锚点对照

| 验收项 | 锚点（tests/five_agent/） | 级别 |
|---|---|---|
| 仅五 role 注册、七 action 绑定、第六角色/越权 action 拒绝 | test_contract.py::test_roles_and_actions_cardinality 等 | [接口检查] |
| 未确认零主创 | test_main_chain.py::test_happy_path…（确认前 creator 调用为 0）、test_unconfirmed_brief_guard… | [Mock 流程] |
| 确认绑定具体版本/hash | test_main_chain.py::test_confirm_bound_to_exact_version_and_hash | [Mock 流程] |
| 缺信息暂停（prepare_brief 补料 / 审校缺事实） | test_brief_needs_input…、test_review_needs_input… | [Mock 流程] |
| 一次修订上限、已修过仍阻断转人工 | test_rule_failure_triggers_one_repair…、test_second_blocking_issue… | [Mock 流程] |
| 跳过可选分支（明确目标跳过流量；未选建议零改稿） | test_branches.py::test_clear_goal_skips_traffic…、test_preview…::未选建议断言 | [Mock 流程] |
| 运营审校无主创聊天（结构隔离）+ 观众四字段/未来哨兵/跨会话 | test_contract.py::test_audience_future_field…、test_branches.py::test_preview…（逐调用断言）、test_audience_projection_rejects… | [接口检查]+[Mock 流程] |
| 逐段退出、exit/unknown 分开、超时 incomplete | test_preview_segments_exit_incomplete…、test_preview_unknown_audience… | [Mock 流程] |
| finding 归属（引用真实观察、选中范围） | test_preview…（observation_refs ⊆ 事件）、test_scope_violating… | [Mock 流程] |
| 局部修改范围、未选片段不变、旧版本保留 | test_selected_findings_scoped_revision…、test_scope_violating… | [Mock 流程] |
| 幂等（双击闸门、回执重放零调用） | test_double_click_gate…、test_restart_replays… | [Mock 流程] |
| 取消/迟到结果不覆盖版本 | test_cancel_mid_call… | [Mock 流程] |
| INTERRUPTED 不自动重发、费用风险确认后重发 | test_sent_unknown… | [Mock 流程] |
| usage unknown 不填零、协议失败零领域提交 | test_contract.py::test_unknown_usage…、test_protocol_garbage… | [接口检查]+[Mock 流程] |
| 预算硬闸门（正常/重试/总量） | test_budget_gate_counts…（第 6 次正常调用 BUDGET_EXCEEDED） | [Mock 流程] |
| Mock/真实同契约、live 不静默回退 | test_live_mode_never_falls_back… | [Mock 流程] |
| 七角色/八 action 绑定、审校归属审稿员 | test_seven_roles.py::test_seven_roles_eight_actions_binding | [接口检查] |
| 商单链：pr_analyst 先于运营官、要求并入 Brief、子 run 独立预算 | test_seven_roles.py::test_commercial_chain_runs_pr_analyst_before_operator | [Mock 流程] |
| 商单缺要求暂停补料、重规划计原预算 | test_seven_roles.py::test_pr_gap_pauses_then_replans_until_ready | [Mock 流程] |
| 商单分析失败转人工、非商单零调用、独立商单 run | test_seven_roles.py::test_pr_analysis_error… / test_non_commercial… / test_standalone… | [Mock 流程] |
| 模型文本/true/1 不构成授权 | test_main_chain.py::test_gate_resume_must_be_committed… | [Mock 流程] |
| revision base 必须 head（CAS） | test_branches.py::test_revision_base_must_be_head | [Mock 流程] |

## 4. 尚未接入能力、owner 与具体缺口

| # | 能力 | owner | 具体缺口 | 影响 |
|---|---|---|---|---|
| G-01 | 五位队员真实实现 | 各能力队员 | 真实入口/输入输出样例/调用次数/重试/usage/凭据/依赖锁/失败分类未提交；当前只有 Mock + AGENT_UNAVAILABLE 占位 | [真实 Adapter 联调] 无法开始；接入顺序按 01-contract.md §4 |
| G-02 | langgraph-checkpoint-sqlite | LG02/checkpoint owner | 本机未安装该插件；现用 MemorySaver，跨进程断点仅靠领域回执 + 显式 reinvoke | 重启恢复的框架侧持久化未验证 |
| G-03 | Flask API + React 工作台 | A02a/A05c owner | 无 HTTP 层/幂等键端点/闸门 UI；本交付是驱动层 API（OrchestrationDriver） | [真实用户] 证据缺失 |
| G-04 | 双库事务对账（app.sqlite/graph.sqlite） | A02b/LG03 | Repository 单库内事务已实现；两库崩溃窗口/备份恢复/SqliteSaver 对账未实现 | 生产级恢复未验收 |
| G-05 | live 模型接入 | A03a 模型接口 owner | 无真实模型请求；usage 为 Mock 合成值 | [真实模型] 证据缺失；同条件比较禁放行 |
| G-06 | prompt/schema hash 冻结 | 各能力 owner | registry 中 REVIEW_PROMPT_SCHEMA_HASH 等为占位；真实 prompt hash 待 owner 申报后冻结 | step_key 的 review 前缀暂用占位值 |
| G-07 | 真实反馈导入与复盘 | 后续任务（需显式授权） | 未实现；不得借 diagnose_preview 偷偷新增请求 | P1 复盘闭环未开 |
| G-08 | 六角色旧 run 兼容 | 集成负责人 | 旧 lg-0.1 checkpoint 不可直接套新图；默认旧 run 保留旧 runtime | 旧任务迁移需显式映射，本版不做自动迁移 |

## 5. 复现方式

```text
python -m pip install langgraph==1.1.10 jsonschema pytest   # 依赖（本机已装）
python tools/extract_schemas.py --handoff-root <交接包>/creator-agent-team
python -m pytest tests/five_agent -q
python run_mock_demo.py
```

测试均使用 `:memory:` SQLite 与 Mock；不需要 API Key、不联网、不依赖队员机器。
`an.py`（仓库根）内含明文模型 API Key，属于历史调试脚本——建议移出仓库并轮换该 Key（G-09）。
