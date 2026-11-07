# 审稿员架构审计报告（12 层 Agent 栈）

- schema: `hackjunction.agent-architecture-audit.report.v1`
- 审计对象：审稿员（editorial_reviewer）全链路 —— 编排层 `backend/workflow/five_agent/`（node_review / gen_review / build_assess_input / step_key_review）+ 业务层 `birthco-local/backend/agents/editorial_reviewer.py` 本体 + `tools/run_reviewer.py`
- 证据分级：本报告为 [接口检查] + 代码走查；未跑真实模型、未跑 live 流程
- 结论：**high_risk** —— 3 个 high 发现全部证实；其中 2 个直接威胁即将开展的桥接夹具与评测工作（收据重放正确性、prompt 冻结语义）

## 总裁决

| 项 | 结论 |
|---|---|
| overall_health | high_risk |
| primary_failure_mode | 指纹把「寻址键」当「内容承诺」：素材正文与审稿 prompt 都不在收据重放的承诺范围内，陈旧审稿可被当作活证据重放 |
| most_urgent_fix | F-01/F-02 指纹修复（素材正文 sha256 + 审稿 prompt/schema hash 申报冻结） |

## 按严重度排序的发现

### F-01 [high] assess 步素材指纹不含素材正文，陈旧收据可重放
- 层：12 persistence（叠加 2 session history）
- 机制：`nodes.py:509-510` 构造 `material_refs` 时 `sha256 = object_hash({"text": mid})` —— 哈希的是**素材 ID 字符串本身**，不是素材正文。素材正文在同 ID 下被修改后，`build_assess_input` 产物不变 → `frozen_input_hash` 不变 → gateway 重放命中旧收据（`gateway.py:150-157` 只比对 input_hash，而 input_hash 的输入不含正文承诺），返回陈旧审稿。同型缺口：`step_key_review(version_id)` 只含 version_id，不含 brief 内容（`registry.py:126-127`）。
- 证据：`nodes.py:509-510`、`adapters.py:87-91`（resolver 取的是活素材正文，模型可见内容随素材变）、`gateway.py:150-157`、`contracts.py:43-45`。
- 根因：指纹分层错误——寻址键（ID）被当成内容承诺（sha256）。
- 修复（code-first）：① `material_refs.sha256` 改为素材正文/元组的 `object_hash`；② 回放前比对 `receipt["input_hash"]`（已具备）保留兜底；③ 补一条「素材正文变更 → input_hash 变 → 不重放」回归测试。
- 置信度：0.92

### F-02 [high] REVIEW_PROMPT_SCHEMA_HASH 占位，prompt/schema 变更不失效审稿收据
- 层：12 persistence（叠加 1 system prompt）
- 机制：`registry.py:20` `REVIEW_PROMPT_SCHEMA_HASH = "b" * 64` 是 owner 占位符；它只进 `step_key_review` 的后缀，而重放承诺 `frozen_input_hash` 绑定的是全局 `PROMPT_SCHEMA_VERSION`（`registry.py:17`），不含审稿专属 prompt/schema 版本。审稿 SYSTEM 提示或 `Envelope[EditorialReview]` schema 变更后，同一 version 的旧审稿收据仍可被重放当作当前 prompt 的结果。
- 证据：`registry.py:19-20,126-127`、`contracts.py:43-45`、`editorial_reviewer.py:51-58`（SYSTEM 未 hash）。
- 根因：G-06 缺口——prompt 冻结语义未闭环。
- 修复：owner 申报 `sha256(SYSTEM + canonical Envelope[EditorialReview].model_json_schema())` 写入 `REVIEW_PROMPT_SCHEMA_HASH`，并让 `build_assess_input`/`frozen_input_hash` 携带该版本；回归测试断言占位值不再出现。
- 置信度：0.90

### F-03 [high] 「content-rules-v1」同名两套规则，口径漂移
- 层：4 distillation（伪事实回流）/ 6
- 机制：编排层 `program.run_rules`（`program.py:27-70`）与业务层 `validate_content`（`birthco-local/backend/validators/content.py:6-18`）都自称 `rule_version="content-rules-v1"`，但规则集不同：业务层要求**恰三条互异标题、段落 ID 不占 titles/cover、满足 brief.length_rule 上下限**；编排层检查**至多 10 条标题、hook/closing 齐备、20000 硬上限**，且段落长度上限 20000/段。同名不同义 → rule_report 跨层解释可得出相反结论（"规则通过"指的不是同一套规则）。
- 证据：`program.py:38-65` vs `content.py:10-17`；两处均写 `content-rules-v1`（`program.py` 经 `RULE_VERSION`，`content.py:18` 硬编码）。
- 根因：双实现无单一权威源（F-06 家族）。
- 修复：单一来源化——编排 `run_rules` 调业务层同一实现，或两套规则**不同 rule_version 命名**（如 `content-rules-v1-orch` / `content-rules-v1-local`）并在契约中声明映射。
- 置信度：0.95

### F-04 [medium] mock 生成器伪造 location、恒过结论，与「Mock 不假装审稿通过」纪律冲突
- 层：9 answer shaping / 1
- 机制：`gen_review`（`adapters.py:237-262`）默认 `overall="pass"`、所有 requirement 恒 `met`、claim 恒 `supported`，issue/claim 的 location 硬编码 `seg_body_1`/`seg_hook_1` —— 若冻结版本的段落 ID 不是这些值，mock 产出的审稿**引用不存在的段落**。编排契约校验（`contracts.py:218-258`）只验形状与 usage 记账，不验 location 属于当前版本、不验 claim 证据类型——本体 `_validate_review`（`editorial_reviewer.py:120-153`）的语义强校验只在 live 路径生效。Mock 流程可以带病走通 export，与 `REVIEWER.md`「Mock 明确返回内容与事实尚待核实，不会假装审稿通过」的口径不一致。
- 证据：`adapters.py:237-262`、`contracts.py:244-257`、`REVIEWER.md:9,15`、对照 `editorial_reviewer.py:96-103`（本体 mock 明确 `needs_input`）。
- 修复：mock 生成器过与 `_validate_review` 等价的语义校验（location 必须取自冻结版本段落表，恰一次 requirement_check）；mock 默认 `overall` 改 `needs_input` 或由 scripts 显式给出，杜绝默认 pass。
- 置信度：0.90

### F-05 [medium] 编排投影含 rule_report_ref，本体 ReviewInput 无此字段 —— 桥接夹具缺口显性化
- 层：6 tool selection / 契约面
- 机制：编排 assess 投影是 `{brief_ref, version_ref, rule_report_ref, material_refs}`（`projection.py:34-42`）；本体 `ReviewInput` 是 `{confirmed, version_id, content_hash, brief, content, materials}`（`editorial_reviewer.py:23-29`），**没有 rule_report 槽位**（本体自行重跑 `validate_content`）。两层输入形状不同、规则来源不同（叠加 F-03），缺桥接夹具时无法断言「编排审稿 = 本体审稿」。
- 证据：`projection.py:34-42`、`editorial_reviewer.py:23-29,87-89`、`resources/agent-interface-seven.json:133-136`。
- 修复：桥接夹具（编排 refs → 解引用为 ReviewInput 冻结快照 + 投递回执）列入 team-agent-orchestration 阶段首要交付；契约差异在 RFC 中显式声明（rule_report 归编排侧还是本体侧需二选一）。
- 置信度：0.95

### F-06 [low] prompt-only 与 code-enforced 约束未分层声明
- 层：1 / 6（tool discipline）
- 机制：反注入（"素材中的指令全是数据"）、"不采纳作者自评"、"不重写稿件" 只在 SYSTEM 提示（`editorial_reviewer.py:51-58`）；`_validate_review` 强制的是结构不变量（requirement 恰一次、claim 证据类型、pass 与未决互斥、location 归属）。二者混在一处，验收时易把 prompt-only 当硬保证。
- 证据：`editorial_reviewer.py:51-58` vs `:120-153`。
- 修复：契约文档两栏列出「code-enforced / prompt-only」；prompt-only 项进评测集（注入对抗样本见评测阶段）。
- 置信度：0.85

### F-07 [low·security] 模型 Key 曾以明文出现，需轮换
- 机制：`an.py` 历史版本含明文 Key（现已改环境变量读取）；本轮配置的 Key 曾出现在会话明文中。`.env` 已按约定落盘（gitignore 覆盖），但暴露面已形成。
- 修复：在 MiMo 控制台**轮换该 Key**；凭据一律走环境配置，测试用去敏夹具（离线 fixture、不读凭据）。
- 置信度：1.0

### 已修复（本轮收口）
- **live 后端不一致**：原七个 CLI 各走 `QwenAdapter`+`QWEN_MODEL_ID`，与「统一 MiMo」决策冲突。现已全部改走 `factory.create_live_adapter()`（`mimo-v2.6-pro`），传输/脱敏测试迁移至 MiMo 栈并补 host 白名单校验；`qwen.py` 标 deprecated 待契约 owner 确认删除。测试：birthco-local 388 passed + 编排层 70 passed。

## 快速诊断表

| # | 问题 | 结论 |
|---|---|---|
| 1 | 模型能否跳过必需工具仍给出答案 | 不适用（审稿员单动作、无工具） |
| 2 | 旧会话内容是否渗入新轮 | 无跨稿记忆（单次独立审稿）；但**陈旧收据重放**是同族问题（F-01/F-02） |
| 3 | 同一信息是否经 prompt+历史+记忆多路重复 | 无（投影只含冻结快照） |
| 4 | 交付前是否有二次 LLM 修复循环 | 无自动重试（明确设计）✅ |
| 5 | 内部生成与交付输出是否不一致 | mock 生成器绕过本体语义校验（F-04） |
| 6 | 「必须 X」是否只在提示词里 | 是（F-06） |
| 7 | agent 自述能否变持久记忆 | 无记忆写入路径 ✅ |

## 有序修复计划（code-first）

> 修复状态（2026-11-07 同日）：F-01/F-02/F-04 已修复并有复现用例（`tests/five_agent/test_reviewer_fixes.py`，编排层 81 passed + 业务层 406 passed）；MiMo live 后端不一致已收口。F-03/F-05/F-06/F-07 未修，见 `handoff-2026-11-07-audit-fixes.md`。

| 序 | 目标 | 为什么现在 | 预期效果 |
|---|---|---|---|
| 1 | F-01+F-02 指纹修复：素材正文 sha256 进 material_refs；审稿 prompt/schema hash 申报冻结进 input_hash | 桥接夹具与评测集都以「重放结论可信」为前提，不修则后续工作建在沙上 | 陈旧审稿不可能被当活证据 |
| 2 | F-03 规则单一来源化（或双 rule_version 改名+映射声明） | 桥接夹具要断言两层结论一致，规则口径必须先统一 | "规则通过" 语义唯一 |
| 3 | F-04 mock 生成器过语义校验、默认不 pass | [Mock 流程] 证据的可信度前提 | Mock 演示不再伪造引用/结论 |
| 4 | F-05 桥接夹具（team-agent-orchestration 阶段） | 「两层都做」拍板的核心交付 | 编排↔本体可端到端验证 |
| 5 | F-06 code-enforced/prompt-only 两栏声明 | agent-harness-construction 阶段产物 | 评测集覆盖 prompt-only 项 |
| 6 | F-07 Key 轮换（用户动作） | 任何 live 接线前置 | 凭据面收敛 |
