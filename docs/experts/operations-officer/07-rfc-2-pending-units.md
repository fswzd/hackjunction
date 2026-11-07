# RFC-2｜运营官已知缺陷批次与待派发工作单元

- schema: `hackjunction.rfc.v1`　状态：draft（供派发；依赖图见 §2）
- 来源：02-architecture-audit 修复序 5-7、04 §6 剩余问题、G-06/G-09 缺口

## 1. 工作单元规格（Unit Spec）

### U-1 补件轮次预算策略（F-O7）　Tier 2
- id: `op-u1-supply-rounds`　depends_on: 无
- scope: `backend/workflow/five_agent/nodes.py`（wait_input→brief 重入计数）、`registry.py`（配置项）；**不含** gateway
- 设计：补件轮次显式限额（配置化，默认 3）；超限走 NEEDS_REVIEW 明确提示，而非预算中途爆掉；每轮消耗在 gate subject 中披露剩余预算
- acceptance_tests: 连续 needs_input 3 轮后第 4 次重入被限额拦（NEEDS_REVIEW）；限额内重规划预算记账正确（normal_calls=轮次+后续链）
- risk_level: medium（预算语义变化）　rollback_plan: 配置限额置 None 恢复原行为

### U-2 素材 kind 语义上收（04 §6）　Tier 2（跨模块）
- id: `op-u2-material-kind`　depends_on: 无（需仓储 owner 协调）
- scope: `birthco-local/backend/storage/`（materials.kind 语义）、桥接 `build_create_task`（去掉首素材启发式）
- 设计：materials 表 kind 采用 MaterialInput 枚举语义；桥接不再猜 kind；旧稿=显式标记的素材
- acceptance_tests: existing_draft 流在多素材下选中原稿正确；桥接 kind 归一代码删除后测试仍绿
- risk_level: medium（涉及迁移/共管）　rollback_plan: 迁移可逆、桥接保留归一层

### U-3 prompt/schema hash 申报冻结（G-06）　Tier 1　✅ 2026-11-07 merged
- id: `op-u3-prompt-hash`　depends_on: 无
- 落点：`operator.py:prompt_fingerprint()`、`evidence/operator-prompt-hash.json`（prompt_hash=78bb18f1…392f5）、`tests/contracts/test_hash_and_drift.py` 锁定
- scope: `evidence/`（申报件）、`registry.py`（占位换实值）、03-harness §7 公式
- acceptance_tests: 占位 `"b"*64` 不再出现在运营官相关路径；hash 随 SYSTEM/schema 变更而变（测试锁定）
- risk_level: low　rollback_plan: 恢复占位并作废证据

### U-4 schema 双源漂移检查（F-O10）　Tier 1　✅ 2026-11-07 merged
- id: `op-u4-schema-drift`　depends_on: U-3
- 落点：`tests/contracts/test_hash_and_drift.py::test_domain_schemas_do_not_drift_from_pydantic_models`（Brief/EditScope/Requirement/LengthRule 结构 + route 枚举）
- scope: `tests/five_agent/test_contract.py` 或 `tools/`（比对 birthco-local pydantic 导出与 `resources/domain_schemas.json`）
- acceptance_tests: 人为改一侧 schema 时检查失败；平时通过
- risk_level: low　rollback_plan: 删除检查测试

### U-5 [真实模型] MiMo 验收　Tier 3
- id: `op-u5-live-acceptance`　depends_on: 阶段 6 评测集、U-3
- scope: 评测脚手架（tools/eval_operator.py）跑 `--live`；`evidence/` 真实 usage 记录
- acceptance_tests: 评测集跑通、usage 为真实值（unknown 不填 0）、冻结不变量在 live 输出下全部成立；失败分类与 mock 同契约
- risk_level: high（真实计费）　rollback_plan: 单次显式调用、无自动重试；失败即停不重发
- 备注：**前置**——Key 已在 git 历史泄漏过（提交 615464d），live 前建议轮换；凭据仅环境配置

### U-6 输出分支兜底与 prompt 强化（F-EVAL-1/2）　Tier 2　✅ 2026-11-07 merged（用户拍板「重映射+prompt」）
- id: `op-u6-branch-remap`　depends_on: U-3
- 落点：`operator.py:_remap_branch/_load_envelope`（ok+questions/open_questions→needs_input 确定性重映射+围栏剥离，零新增调用）、SYSTEM 分支纪律、`prompt_hash` 重申报 `1198118a…613cf0`、4 条回归测试
- 效果：live pass@1 0.625→0.875、pass@3→1.000、pass^3 0.500→0.750

## 2. 依赖图

```
U-3 ──► U-4
  └────► U-5 ◄──（阶段 6 评测集）
U-1（独立）　　U-2（独立，需跨模块协调）
```

## 3. 合并队列规则（沿用）

- 依赖未清不入队；集成前重跑 `birthco-local` 与 `tests/five_agent` 全量；与 traffic_scout 批次在 `nodes.py` 的改动按区域合并，冲突由集成负责人裁决。
