# 运营官 架构审计报告（12 层 Agent 栈）

- schema: `hackjunction.agent-architecture-audit.report.v1`
- 审计对象：运营官（operations_officer / prepare_brief）全链路 —— `backend/workflow/five_agent/` 编排层 + `birthco-local/backend/agents/operator.py` 本体
- 证据基线：git main @809af8a + 未提交工作树；`python -m pytest tests/five_agent -q` → 55 passed；`python -m pytest tests/agents/test_operator.py -q` → 12 passed（2026-11-07）
- 结论：**high_risk** —— 本体自身纪律良好，但编排层与本体之间的契约/语义断层会在真实接入时放行被改写的用户要求、丢旧稿修改通道

## 总裁决

| 项 | 结论 |
|---|---|
| overall_health | high_risk |
| primary_failure_mode | 不变量只活在本体一层：编排层的 mock 生成器与契约校验都不执行「用户要求冻结」，双层语义（open_questions、hash、素材形状）互相漂移 |
| most_urgent_fix | 桥接层落地时把本体校验设为 prepare_brief 输出的唯一入口（F-O1/F-O2 不修则真实 Adapter 一接就穿透不变量） |

## 按严重度排序的发现

### F-O1 [high] 用户要求冻结不变量只在本体，编排层可放行被改写的 Brief
- 层：6 tool interpretation（叠加 12 的 mock 证据污染）
- 机制：「objective/audience/platform/requirements/length_rule/edit_scope 不得被模型改写」由本体强制（`birthco-local/backend/agents/operator.py:134-138`）。编排层对 prepare_brief 输出只做 DTO 结构校验（`contracts.py:166-170`，`domain[output_schema]`），`node_brief` 收下 `outcome.data` 直接落库（`nodes.py:312-318`），无任何语义比对。mock 生成器 `gen_brief` 自己就违反该不变量：无视输入编造 audience/platform/requirements/length_rule（`adapters.py:157-174`）。
- 证据：`nodes.py:288-324`、`contracts.py:208-215`（仅 BriefRef task 归属检查）、`adapters.py:145-176`、`test_seven_roles.py:56`（只断言 objective 含客户要求文本，mock 是回声行为不是不变量）。
- 根因：双实现各自校验，「权威校验」没有唯一入口；mock 证据无法证明需求保真。
- 修复（code-first）：真实 Adapter 入口强制经本体 `OperatorAgent.run` + `validate_brief_scope` + 冻结比对；编排层补「输出 requirements/objective 与输入派生目标一致」的轻量断言；测试用变异输出锁定（改写 objective/requirement 的输出必须被拒）。
- 置信度：0.92

### F-O2 [high] open_questions 语义冲突：本体判非法、编排层判合法
- 层：6 / 12（双实现漂移）
- 机制：本体规定 open_questions 非空必须走 needs_input，`status=ok` 携带 open_questions 直接 SCHEMA_INVALID（`operator.py:139-140`）。编排层接受 ok+open_questions 并路由 wait_input（`nodes.py:313-322`），且 `confirm_brief` 拒绝带 open_questions 的确认（`repository.py:244-246`）。mock 脚本可产出真实本体永远产不出的形状（ok+questions），mock 流程测试因此测的是本体不支持的协议分支。
- 证据：`operator.py:139-140`、`nodes.py:313-322`、`repository.py:244-246`、`adapters.py:375-435`（MockAgent 对 kind=needs_input/ok 的形状映射）。
- 根因：Envelope 语义在两层没有共同契约文档；各写各的。
- 修复：桥接契约冻结唯一语义（建议采纳本体语义：open_questions ⇒ needs_input），MockAgent 的 prepare_brief 生成器走同一校验；冲突分支加回归测试。
- 置信度：0.90

### F-O3 [high] existing_draft / edit_scope 通道在投影层缺失，旧稿定向修改不可达
- 层：6 tool selection（观测/输入投影缺失）
- 机制：本体支持旧稿流程：原稿材料→`draft_segments` 稳定分段→EditScope 校验→未选段落强制保留→缺 scope 先 needs_input（`operator.py:72-93`、`operator.py:51-55`）。编排层投影 `build_prepare_brief_input` 只有 `{user_input, input_mode, material_refs, selected_opportunity_ref}`（`projection.py:19-22`），无 edit_scope、无原稿分段、material_refs 不带 kind——真实入口无法区分原稿与素材，EditScope 无传入通道。
- 证据：`projection.py:19-22`、`operator.py:72-93`、`node_route` 的 has_draft 只用于路由（`nodes.py:104-108`）。
- 根因：投影契约按「最小心智负担」裁剪时把旧稿分支整个裁掉。
- 修复：投影扩字段（existing_draft 段快照 + edit_scope，走契约共管流程），或桥接层在 input_mode=existing_draft 时显式 needs_input 并声明该通道 P0 不可达——二选一，不能默不作声。
- 置信度：0.93

### F-O4 [high] 桥接输入不含素材正文与 kind，跨层 hash 约定不一致
- 层：6 / 8
- 机制：`node_brief` 的 material_refs 仅 `{id, sha256}`（`nodes.py:292`），sha256 = `object_hash({"text": ...})`；本体素材内容指纹是 `sha256_json(text)`（`operator.py:44-48`）。mock 生成器借 `resolver.material(ref)` 拿正文（`adapters.py:148-151`），真实入口没有等价 resolver 约定——不补就只能把 refs 递给模型（引不出素材），补了又绕开最小投影设计。同概念两种 hash 使「素材一致」断言跨层无法互认。
- 证据：`nodes.py:292`、`operator.py:44-48`、`adapters.py:148-151`、`contracts.py:33-45`。
- 根因：桥接夹具缺位（双实现漂移同根）。
- 修复：桥接夹具负责 material text/kind 解析（授权范围=本 task），hash 映射表进桥接契约；素材正文进模型可见输入前做长度截断与授权校验（对齐本体 80k/20k 上限）。
- 置信度：0.85

### F-O5 [medium] pr_analysis 要求并入丢 requirement_id，需求可追溯链断裂
- 层：8 tool interpretation
- 机制：商单链把客户硬性要求拼成一段文本并进 user_input（`nodes.py:299-304`），requirement id 全丢。Brief.requirements 的 id 由模型现编，无法回指 pr_analysis 产物；下游 `RequirementCheck(requirement_id)` 追溯链在此断开。本体要求「保留原有 requirement_id」（`operator.py:14-20` SYSTEM），桥接输入却不给 id。
- 证据：`nodes.py:299-304`、`birthco-local/backend/domain/schemas.py:58-60,146-150`。
- 修复：并入改为结构化 `requirements: [{id,text}]` 进桥接输入，Brief.requirements 必须原 id 原文回填（代码比对，非 prompt）。
- 置信度：0.85

### F-O6 [medium] 三种 brief hash 概念并存，确认 CAS 指纹未统一
- 层：12 persistence
- 机制：本体建议指纹 `proposal_hash=sha256_json(brief)`（`operator.py:141`）；本体正式 CAS 设计 `brief_hash=sha256_json({"brief","frozen_rules"})`（`birthco-local/backend/domain/hashing.py:21-22`，含冻结规则，当前无调用方）；编排层 `brief_hash=object_hash(payload)`（`repository.py:209`，确认闸门与 CAS 用它，`nodes.py:368-389`）。三者互不相等；用户或下游拿 proposal_hash 当确认指纹必然对不上。
- 证据：如上三处 + `repository.py:238-252`（CAS）。
- 修复：桥接契约声明唯一权威 CAS 指纹（建议=编排层 object_hash，本体 proposal_hash 降级标注「非 CAS」）；如需 frozen_rules 参与承诺，走契约共管升级，不允许第三种私有定义。
- 置信度：0.80

### F-O7 [medium] 补件轮次无预算策略，重复 needs_input 可耗尽内容 run 预算
- 层：11/12（预算纪律）
- 机制：每轮 wait_input→brief 重入因 user_input 变化产生新 step_key、新 prepare_brief 调用，计入 content run normal 预算（`nodes.py:305-310`、`registry.py` BUDGETS content=5 normal/1 repair/2 tech/7 total/60k）。brief×N + draft + assess(+repair pair 2)：N≥3 时 repair 空间消失，N≥4 中途 BudgetExceeded，失败在链条中段爆出；无「补件轮次上限」策略，也无「预算将耗尽」的用户提示。
- 证据：`nodes.py:305-310`、`registry.py:65-68`、`nodes.py:545-549`（repair 计数）。
- 修复：补件轮次显式限额（配置化，超限 NEEDS_REVIEW 而非预算爆掉）；或补件重入复用已确认输入指纹的增量预算策略——排入 RFC。
- 置信度：0.80

### F-O8 [medium·security] 明文模型 Key 在仓库脚本中（继承全局 F-08）
- 证据：仓库根 `an.py` 含 base_url + 明文 Key。
- 修复：MiMo live 接线（阶段 3）之前移出仓库并轮换 Key；凭据一律环境配置 + `.env.example`；测试用去敏离线夹具。
- 置信度：1.0

### F-O9 [low] prompt-only 与 code-enforced 未分层声明（F-09 同型）
- 层：1 system prompt / 6
- 机制：SYSTEM 承诺「不虚构账号历史/保留 requirement_id/平台空缺 generic/只走 draft|review|export」（`operator.py:14-20`）。code 实际强制：material_ids ⊆ 提供集合、冻结字段逐字比对、route p0_only（`errors.py:44-47`）、open_questions⇒needs_input。**未**强制：core_promise 内容任意、requirements 允许增发新 id（`operator.py:136` 只查原有 id 保留，不限新增）、不虚构类内容约束。
- 修复：契约文档两栏声明；未强制项进评测集（阶段 6）；「限增发 requirement id」可低成本加代码断言。
- 置信度：0.75

### F-O10 [low] 残余与卫生项
- step_key planning 指纹不含素材正文 hash（`nodes.py:303-307`）——**已被 input_hash 回放护栏兜底**（`gateway.py:150-157` 明确拒绝不同输入的陈旧回执；`repository.py:450-461`），陈旧重放不可达，补指纹降为卫生项。
- schema 双源：`resources/domain_schemas.json` 是提取快照，与 `birthco-local/backend/domain/schemas.py` 无漂移检查；改一侧不报错（`test_contract.py` 只验自洽）。
- G-06 同型：prepare_brief 的真实 prompt/schema hash 未申报冻结，step_key/指纹承诺不完整。

## 架构诊断（哪层污染了什么）

本体（prompt 层+校验层）纪律是全项目最好的一类：冻结比对、引用边界、失败分类、无自动重试、unknown 不回退。问题集中在**层间**：6/8 层的投影与桥接把本体的输入契约裁剪到不可用（F-O3/F-O4），12 层的哈希概念三足鼎立（F-O6），mock 生成器（7 层模拟）自造协议形状与语义（F-O1/F-O2），使 [Mock 流程] 证据对「需求保真」「旧稿保护」没有证明力。没有隐藏修复环（business repair 只作用于 draft/规则失败路径，prepare_brief 无二次 LLM pass）；无记忆系统（阶段 4 引入时需防 pending_questions/artifact 被当事实回流）。

## 快速诊断问答

| # | 问题 | 结论 |
|---|---|---|
| 1 | 模型能否跳过必需约束仍出答案？ | 能（编排层）——需求冻结非 code-gated → F-O1 |
| 2 | 旧内容会进新轮次吗？ | 不会——input_hash 回放护栏已生效 → F-O10（卫生项） |
| 3 | 同一信息多处注入？ | 轻微（user_input 同时进指纹与 payload；pr 要求以文本重复并入） |
| 4 | 平台有二次 LLM 修复 pass？ | 无；repair 仅限 draft/规则失败，prepare_brief 无 |
| 5 | 内部生成与交付不一致？ | 双实现输出形状/语义不一致 → F-O2/F-O4 |
| 6 | 「必须用 X」只写在提示词？ | 是（不虚构、保留 requirement_id 等） → F-O9 |
| 7 | 独白会进持久记忆？ | 当前无记忆系统；阶段 4 建记忆时须设准入（用户确认>agent 断言） |

## 有序修复计划（code-first）

| 序 | 修复 | 为什么现在 | 预期效果 |
|---|---|---|---|
| 1 | F-O1/F-O2：桥接层唯一校验入口（本体校验=权威）+ MockAgent 走同校验 | 真实 Adapter 接入（阶段 3）的前置，不修则一接就穿透 | 被改写的 Brief 出不了本体；mock 证据恢复证明力 |
| 2 | F-O3/F-O4：投影/桥接夹具补 edit_scope、素材正文与 kind、hash 映射 | 同为阶段 3 前置 | 旧稿通道可达；素材溯源不断链 |
| 3 | F-O8：Key 轮换 + env 化 | 任何 live 前置 | 消除泄漏面 |
| 4 | F-O5：requirements 结构化并入 + id 回填断言 | 随桥接夹具一并做 | 需求追溯链闭合 |
| 5 | F-O6：CAS 指纹唯一化声明 | 契约冻结时定 | 确认流程指纹唯一 |
| 6 | F-O7：补件轮次限额/预算策略 | RFC 批次 | 补件不再中途爆预算 |
| 7 | F-O9/F-O10：两栏声明 + 漂移检查 + prompt hash 申报 | 文档/评测阶段（阶段 2、6） | 边界不被误述 |

## 给后续阶段的输入

- **阶段 2（harness）**：F-O9 两栏清单以本报告为准；prompt 三段式设计需吸收 F-O1/F-O3 的输入契约结论。
- **阶段 3（编排接入）**：修复序 1-4 是接入包的验收条件；F-O6 声明进桥接契约。
- **阶段 4（记忆）**：准入规则（用户确认>agent 断言）按诊断问答 #7 落地。
- **阶段 6（评测）**：F-O1/F-O2/F-O3 的变异用例直接进回归集；mock 流程证据在修复 1 完成前不得用于「需求保真/旧稿保护」主张。
