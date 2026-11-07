# 内容主创 · P0-A 基线对表（阶段 1 补审）

对照 02-architecture-audit（fa48ea5 基线）在 **P0-A 七角色桥接（e95bfa0）之后**的当前实态复核。
代码基线：2026-11-07 晚（含五专家后续包合并与去 Key 化）。审计方式：沿 `draft → rules → review → revise`
逐面核对编排桥接（`backend/workflow/five_agent/live_adapters.py`）与本体（`birthco-local/backend/agents/director.py`）。

| 检查面 | 当前实态（文件级证据） | 裁定 |
| --- | --- | --- |
| 段落 ID 预留 | 桥接确定性预分配 `s_+hash(input_hash,ordinal)`，revise 排除基线已用 ID（live_adapters.py 桥接 `_director` 组装处） | ✅ 02 的「编排预留」承诺已兑现 |
| 输入冻结 | DirectorInput 自校验 brief_hash（含 frozen_rules）、素材全集匹配、base 内容哈希比对 | ✅ |
| 修订范围 | `_revise`：base id+hash 双冻结（CONDITIONS_MISMATCH）、analysis sha256 冻结、findings↔locations 一致、EditScope 程序化构造、保留段落入 preserve | ✅ 越权路径全拒 |
| change_log | finding 模式自动归一 finding_id/issue_id 归属；issue 模式走 issue_locations | ✅ |
| 规则单一来源 | `program.run_rules`→`validate_content_rules`、`validate_revision`→`validate_scoped_revision`（与审稿共用） | ✅（02 的头号风险已闭） |
| 输出契约 | `output_contract.prompt_schema_fingerprint`：收据绑定提示词/schema 指纹，提示词变更使旧收据失效 | ✅ |
| needs_input 边界 | `_draft` 对非 idea 模式返回明确补件问题（要求先入库旧稿版本），不越权代写 | ✅ |
| 调用纪律 | 单次尝试、envelope 全链校验、ScopeError→SCOPE_DENIED、预算经 Gateway（内容 run ≤7 次上限） | ✅ |
| 测试 | test_specialist_handoffs：五真实入口联调、draft→revise（finding_id=f1）盲测重测、契约一致性、试映上限、补件三轮内完成 | ✅ 覆盖良好 |
| 内容质量 | 结构/引用/范围由程序保证；事实与文案质量仅提示词约束 | ⚠ 属阶段 6 评测集范围 |
| live 内容质量 | 未验收（依赖新 Key 运行时注入后的真实 MiMo 质量验收） | ⚠ 用户侧动作 |
| API 模式任务推进 | 依赖队列 worker（F-01，另一条修复流水线实现中）；worker 落地后 revision run 与 wait_accept 需在 API 路径复验 | ⚠ 跨工作包依赖 |

## 与 02 审计的差异

- 02 的重点风险「rules 与审稿员同名规则不同判」已由规则单一来源闭合。
- 02 的「编排仅靠 change_log 的 ID 集合核对修改」已由 `validate_scoped_revision` 共享校验闭合。
- 新增兑现：预留段落 ID、提示词指纹收据、analysis 冻结校验——均为 02 之后落地。

## 进入阶段 2-6 的输入

1. **阶段 2（harness）**：SYSTEM 提示词与输出 schema 的分层声明（code-enforced vs prompt-only 清单）可直接从 `_draft/_revise` 的校验面反推。
2. **阶段 3（编排桥接）**：P0-A 已完成大半——余项为 API 模式下 worker 驱动的端到端复验（等 worker 落地）。
3. **阶段 4（记忆+检索）**：`material_retrieval`（素材内三轮检索、保留来源）已具备检索骨架；账号级风格/审校记忆待接入 `memories` 表。
4. **阶段 5（RFC/WP）**：以上余项打包冻结。
5. **阶段 6（评测集）**：结构合格率/scope 遵从/needs_input 正确性为 capability 项；内容质量 rubric 另立（需人工标注）。
