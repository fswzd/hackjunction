# 运营官 Harness 设计（prepare_brief）

- schema: `hackjunction.agent-harness-construction.design.v1`
- 对象：运营官单动作 agent（`birthco-local/backend/agents/operator.py` + 编排层 prepare_brief）
- 前置：`02-architecture-audit.md`（F-O1/F-O3/F-O9 的 harness 结论在此落地）
- 基线改动：`frozen_fields` 子集冻结 + 要求列表严格一致（2026-11-07，`tests/agents/test_operator.py` 15 passed）

## 1. 动作空间

| 项 | 设计 | 理由 |
|---|---|---|
| 动作 | 单动作 `prepare_brief`，无工具面 | 整理任务书是确定性结构化生成；工具面越窄，出错面越窄 |
| 输入 | schema-first：`CreateTask`（+`EditScope`）或桥接投影 `{user_input, input_mode, material_refs, selected_opportunity_ref}` | 全部必填显式、`additionalProperties=false`；禁止 catch-all 上下文块 |
| 输出 | `Envelope[Brief]`（ok/needs_input 二态 + questions/issues） | 确定性形状；Brief 本身禁正文字段（结构上写不了正文） |
| 不做什么 | 不确认任务书、不写正文、不发布、不调用其他角色 | 由 schema（无相应字段）+ 校验 + prompt 三层共同保证，见 §3 |

## 2. 观测（模型可见输入）设计

- **三段式**：system = 职责 + 输出 schema（不变量）；user = 规范化 JSON 上下文（任务、素材快照、原稿分段、edit_scope、选中机会）。上下文是**数据**，与指令隔离——素材里的指令注入只能落在 user 数据区（`test_material_instructions_stay_inside_data_and_are_not_system_prompt` 锁定）。
- 素材进入模型观测的形态：`material_snapshot` 带 `material_id/kind/label/text/content_hash/source_url`；模型只能引用给定 `material_id`（evidence_refs 越界即 SCOPE_DENIED）。
- 编排层投影是最小集（不含素材正文）——桥接夹具负责在授权范围内补正文与 kind（见 04 桥接设计）；**投影补全发生在桥接层，不放宽投影契约本身**。
- 每次调用的观测记录进 `OperatorResult.material_index`（去 text）+ `input_hash`，供隔离断言与审计；模型输出原文永不回显进错误信息。

## 3. 约束分层声明（code-enforced vs prompt-only）

| 约束 | 执行层 | 证据 |
|---|---|---|
| material_ids ⊆ 提供集合；evidence_refs ⊆ 提供集合 | **code** | `operator.py` allowed 集合比对 |
| route ⊆ {draft, review, export}（P0） | **code** | `validate_brief_scope(p0_only=True)` |
| idea 无 edit_scope；existing_draft 必须恰好一份原稿 + scope 归属 | **code** | `validate_brief_scope` + `run()` 前置分支 |
| 未选段落强制保留（preserve 补全） | **code** | `run()` edit_scope 归一化 |
| 要求列表与输入逐条一致（编号+文本，禁增删改）——`requirements` 冻结时 | **code** | `run()` 冻结比对（本阶段收紧为集合相等） |
| input_mode/objective/audience/platform/length_rule 逐字保留——对应字段冻结时 | **code** | `run(frozen_fields=...)` 冻结比对；桥接自由文本流只冻 `{input_mode, objective?, requirements, length_rule}` |
| open_questions 非空 ⇒ 必须 needs_input | **code** | `run()` 判 SCHEMA_INVALID |
| 输出必须过 Envelope[Brief] schema | **code** | pydantic 校验；坏输出 SCHEMA_INVALID，无修复、无自动重试 |
| 不得虚构账号历史/来源/热点/效果 | **prompt-only** | 进评测集（阶段 6），不作硬保证 |
| 平台空缺用 generic | code（冻结比对）+ prompt 引导 | `task.platform.strip() or "generic"` |
| 不写正文、不确认、不冒称调用其他角色 | 结构（Brief 无正文字段）+ prompt-only 行为约束 | 验收按 prompt-only 计 |
| 素材内指令不得改变职责 | prompt 隔离（数据区）+ code（输出仍全量校验） | 注入只能影响生成内容，不能绕过校验 |

**规则**：prompt-only 项在验收文档里不得表述为「已保证」；评测集必须覆盖每一项 prompt-only。

## 4. 冻结语义（frozen_fields）

- 默认 `frozen_fields=None` ⇒ 全字段冻结（独立运行场景：用户结构化填单，逐字保留）。
- 桥接自由文本流传子集，如 `frozenset({"input_mode","objective","requirements","length_rule"})`：audience/platform/style 属**推断字段**——允许模型从任务文本整理，但受 schema 非空约束，最终由用户在 confirm 闸门看到并确认。
- `edit_scope` 提供即冻结（与子集无关）；未知字段名在任何调用前拒单。
- `requirements` 冻结 = **集合相等**（编号+文本），不再允许「保留原有但增发新编号」。

## 5. 恢复契约（错误即终态，无隐藏修复环）

| 错误码 | 含义 | safe next action（已在 ErrorDetail.cause_hint/next_action） | 重试 |
|---|---|---|---|
| SCHEMA_INVALID | 输出不合契约/截断/open_questions 走错分支 | 检查 schema，显式发起新的一次调用 | 无自动重试 |
| SCOPE_DENIED | 越域引用/冻结字段被改/未知冻结字段 | 保留原目标与范围 | 不重试（模型行为问题） |
| MODEL_REJECTED / MODEL_UNAVAILABLE | 供应商拒绝/不可用 | 检查配置或供应商 | 显式重发 |
| INTERRUPTED | 已发出但结果未知 | 对账 usage 后显式重发（成本风险确认） | **绝不**自动重发 |
| OUTPUT_TOO_LARGE / INPUT_MISSING | 超限/缺件 | 缩减素材 / 补充输入（needs_input 路径） | — |

技术重试次数由调用方（编排层预算）控制，agent 本体零重试。

## 6. 上下文预算

- system 常驻且不变（职责+schema）；schema 以 `canonical_bytes(Envelope[Brief].model_json_schema())` 注入，与 contracts 同源。
- 素材合计 ≤80,000 字符、原稿 ≤32 段、单次 max_completion_tokens=4000、响应 ≤1 MiB、90s 超时。
- 长文档不进 prompt——素材以 JSON 数据整体注入且有硬上限；不做随取随载（单动作 agent 无检索回路，见阶段 4 记忆设计）。

## 7. prompt/schema hash 冻结（G-06 运营官侧）

- SYSTEM 文本 + 输出 schema 的规范字节一起构成 prompt 承诺：`prompt_hash = sha256(canonical_bytes({"system": SYSTEM, "schema": canonical_json(Envelope[Brief].model_json_schema())}))`。
- 申报时机：阶段 3 桥接接入时按此公式产出实值并写入 `evidence/`，此后 SYSTEM/schema 变更 = hash 变更 = 失效重报；占位值（`"b"*64` 类）不得进入验收证据。
- 编排层 `frozen_input_hash` 已含 `prompt_schema_version`；本体侧 `input_hash` 同样绑定上下文规范字节，两层指纹语义并存时以桥接契约为准（04）。

## 8. 架构模式选择

单动作无回路 → **纯 function-calling 形态**（一次结构化生成 + 严格校验），不引入 ReAct/多步规划。恢复不靠 agent 自我修正，靠调用方显式重发 + 预算闸门。
