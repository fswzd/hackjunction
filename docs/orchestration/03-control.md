# 交付物 4 · 用户确认、版本、预算和恢复机制

程序负责状态/权限/指标/版本/预算；用户负责确认需求、选择建议、接受交付；
模型只提交建议，不能移动指针、确认收款或公开发布。

## 1. 用户确认（闸门）

七类闸门全部绑定**冻结 subject hash**，决策写入领域表后才可被图消费：

| 闸门 | 绑定 subject | 批准效果 | 拒绝效果 |
|---|---|---|---|
| select_opportunity | 机会集 hash + 选项 id | 选择归一化为 repo-backed Ref 进 Brief | 终态 CANCELLED |
| supply_input | 问题清单 hash | 补料入任务，同 run 重规划（预算继续） | 终态 WAITING_INPUT |
| confirm_brief | task_id + brief_version + brief_hash + 预算摘要 | CAS 置 confirmed，进入 draft | 终态 CANCELLED |
| accept_delivery | version_id + content_hash + batch_id | 版本 candidate/ready→accepted | 版本保持 ready（可下载） |
| preview_conditions | version_id + content_hash + 预算摘要 | 冻结 scenario，建会话 | 终态 CANCELLED（零观众调用） |
| select_findings | analysis_id + version_id + 预算 | 冻结 RevisionRequest → revision run | 零改稿 |
| accept_revision | 新版本 + 导出批 | 新版本 accepted | 新版本保持 ready |

实现：`workflow_gates`（同 run/kind/subject_hash 唯一，不可原地换 subject）+
`workflow_commands`（UNIQUE(run_id, idempotency_key)）；`Command(resume={gate_id, decision_key})`
只由 driver 从**已提交命令**组装。resume 值必须命中已批准/已拒绝的决策键——
`true`、`1`、`"已获批准"`、模型文本一律 `ORIGIN_DENIED`（测试覆盖）。

双击幂等：同 idempotency_key + 同 payload → 返回原响应形状，零重复调用；
同 key 异 payload / 异 key 重复决策 → `IDEMPOTENCY_CONFLICT` / `VERSION_CONFLICT`。

## 2. 版本

- Brief 无独立 id：`(task_id, brief_version)` + `brief_hash` 复合引用；确认用
  `expected_row_version` CAS；open_questions 非空禁止确认。
- 内容版本链：`base_version_id` 指向基稿；状态机
  `candidate →（导出）ready →（接受）accepted`；导出前不改 ready、接受前不改 accepted；
  **生成合格 ≠ 用户接受**。
- 局部修订：独立 revision run，base 必须是当前 head（CAS）；scope 内外用
  `validate_revision` 强校验：未选片段字节级不变、标题/封面仅 allow_* 时可动、
  每处正文改动必须引用已选 finding/issue。失败新稿不落版本，旧 ready/accepted
  原样可下载（测试覆盖）。
- 导出批：`export_batch` artifact 含 MD/TXT 文件内容与 exporter 版本；0 模型调用。

## 3. 预算（中央硬闸门，含 Agent 内部调用）

| run.kind | 正常调用 | 业务修订 | 共享技术重试 | 总调用 | tokens |
|---|---|---|---|---|---|
| content | 5（3=brief+draft+assess，修订对 +2） | 1 | 2 | 7 | 60k |
| revision | 4（2=revise+assess，自动纠错对 +2） | 1 | 2 | 7（沿用 7/1/2 上限） | 60k |
| preview | 49（≤48 观众 + 1 分析） | 0 | 4 | 53 | 200k |
| scout | 3 | 0 | 2 | 5 | 20k |
| export | 0 | 0 | 0 | 0 | 0 |

规则：
- 每次 Adapter 调用（含队员内部重试）逐次过 `BudgetGate`；attempt=1 计正常，
  attempt>1 计共享重试；超限 `BUDGET_EXCEEDED`。
- 规则失败跳过首次审校（省一次 assess）；展示建议为模板渲染 0 模型。
- usage 未知保留 unknown（null），不填零；账本含 `unknown_usage_calls`。
- 重放（回执命中）0 调用、不改账本；换 thread/换图不重置预算。
- 流量捕捉记账在 scout 子 run，不占内容 3 次。

## 4. 取消、中断与恢复

| 情况 | 动作 | 证据锚点 |
|---|---|---|
| 用户取消 | epoch+1、状态 CANCELLED、pending 命令 obsolete | `cancel_run` |
| 取消后迟到结果 | epoch fence 拒绝提交；call=discarded（usage 记录）；版本不动 | `test_cancel_mid_call_discards_late_result_and_keeps_versions` |
| 发送后结果未知 | run=INTERRUPTED，usage 未知；不自动重发 | `test_sent_unknown_is_interrupted_not_auto_resent` |
| 显式重发 | 用户确认费用风险后按中断 step 重入（新 attempt） | `confirm_interrupted_resend` |
| 观众步 unknown | 会话=incomplete，事件保留，其他会话继续，不伪造 exit | `test_preview_unknown_audience_keeps_incomplete_without_fake_exit` |
| 步骤重放/重启 | resume_step 重入 + 回执重放，零新增调用 | `test_restart_replays_committed_receipts_zero_new_calls` |
| 缺队员实现 | AGENT_UNAVAILABLE，禁止 Mock 回退 | `test_live_mode_never_falls_back_to_mock` |

崩溃语义沿用设计 §6 对账表：已发送未落库→INTERRUPTED；已落 typed output 未提交领域
→ 从回执零网络补提交；仅有 response_hash 无 typed output → 不承诺重放，等用户显式新 run。
当前实现覆盖“进程内崩溃重入”；跨进程两库（app.sqlite/graph.sqlite）原子窗口、
SqliteSaver 恢复、备份混合拒绝等属于 LG02/LG03 owner 的集成验收项。
