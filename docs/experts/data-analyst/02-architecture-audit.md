# 数据分析师 架构审计报告（12 层 Agent 栈）

- schema: `hackjunction.agent-architecture-audit.report.v1`
- 审计对象：数据分析师（data_analyst）全链路 —— `birthco-local/backend/agents/analyst.py` 本体 + `birthco-local/backend/simulation/analysis_data.py` 统计/校验 + `birthco-local/tools/run_analyst.py` 入口 + ORCH `diagnose_preview` 节点（`backend/workflow/five_agent/nodes.py:831-866`）
- 代码基线：git_head `809af8a085` + 工作区未提交改动；证据均为 `file:line` 代码引用
- 结论：**high_risk** —— 本体校验纪律良好（模型不可覆盖统计、无隐藏重试、证据引用精确匹配），但入口/编排/口径三层各存在会让「分析结论不可信或统计丢失」的缺陷

## 总裁决

| 项 | 结论 |
|---|---|
| overall_health | high_risk |
| primary_failure_mode | 跨层契约漂移：同一角色在本体/mock/编排三处的比较边界、指标口径、live 后端不一致，任一处都会污染分析结论 |
| most_urgent_fix | live 配置缺失分支丢统计 + `gen_analysis` 放行 `conditions_match=True`（后者直接威胁因果边界） |

## 正面确认（先证伪「模型侧问题」）

| 控制点 | 证据 | 结论 |
|---|---|---|
| 程序统计权威，模型不可替换/改写 | `analyst.py:75-77`（summarize 在 adapter 之前算死）、`analyst.py:18`（SYSTEM 明示） | ✅ code-gated，非仅提示词 |
| 无隐藏重试/修复循环 | `analyst.py:109-122` 单次调用、失败即返回；`mimo.py:128`/`qwen.py:108` 传输层无自动重试 | ✅ 无第二遍 LLM |
| 证据引用精确匹配 | `analyst.py:127,137,141`（evidence_refs 必须与 findings 引用全集完全一致、必须是当前版本真实 event_id） | ✅ 强校验 |
| 比较边界不可越权 | `analyst.py:143-144`（conditions_match/reason 逐字复制 `comparison_context`，否则 CONDITIONS_MISMATCH） | ✅ 本体侧强 |
| 输出上限与失败分类 | 800 token（`analyst.py:91`）、响应 ≤1MiB（`:116`）、INTERRUPTED/MODEL_REJECTED/MODEL_UNAVAILABLE/SCHEMA_INVALID/OUTPUT_TOO_LARGE（`:110-118`） | ✅ |
| Mock 披露 | mock findings 模板自陈「不代表真实读者」（`analyst.py:100-103`），`is_simulation/human_sample/causal_claims_supported` 固化常量（`:48`） | ✅ |

## 按严重度排序的发现

### F-A1 [high] live 配置缺失分支丢弃已算好的统计，违反自身承诺
- 层：9 answer shaping / 12 persistence
- 机制：`--live` 路径分两步构造：`QwenAdapter()` 构造成功后，`AnalystAgent(..., model_id=os.environ.get("QWEN_MODEL_ID"))` 在 `model_id` 缺失时抛 `ValueError`（`analyst.py:69`），该异常**不在** `configuration_failure` 的捕获范围内（`run_analyst.py:22-26` 只包住 adapter 构造），一路冒到 `__main__` 的 `except (ValueError,...)` → 退出码 2、**输出文件不写**、程序统计被丢弃。
- 矛盾承诺：`ANALYST.md:35`「模型配置缺失也会保留有效统计，返回 failed 和 call_id=null」。
- 复合缺陷：`QWEN_MODEL_ID` 与统一后端的 `MIMO_MODEL_ID`（`factory.py:19`）不一致，见 F-A2 —— 实际上「按项目约定配置 MiMo」的用户跑 `--live` **必然**落进这条丢统计分支。
- 根因：失败域划分错误——把「provider 初始化失败」当唯一配置失败，漏掉「model_id 缺失」。
- 修复（code-first）：`run_analyst.py` 将 adapter+model_id 解析整体包进 try，任何配置缺失 → `configuration_failure(snapshot)`（保留统计、`call_id=null`、`analysis_status="failed"`、退出码 3）；补一条回归：`--live` 且无任何模型环境变量 → 输出文件存在且 `metrics.N` 与 mock 一致。
- 置信度：0.95

### F-A2 [high] live 后端双轨漂移：factory 宣布统一 MiMo，七个 CLI 仍接 Qwen
- 层：6 tool selection（wrapper regression）
- 机制：`factory.py:14-19` 明文「全部专家 agent 的真实调用经 MiMo（mimo-v2.6-pro）」并提供 `create_live_adapter()/resolve_model_id()`；但七个 `tools/run_*.py` 全部直接 `QwenAdapter()` + `QWEN_MODEL_ID`（`run_analyst.py:23,26` 等）。`qwen.py`（299 行）与 `mimo.py`（320 行）是两份近似重复的传输栈（同注释、同限幅、同 `_retry_after`），任何传输修复都要改两处。
- 后果：模型 ID/端点/凭据三者随入口不同而不同；同一 agent 在 CLI 与桥接后的真实 Adapter 下行为不可比；F-A1 因此被触发。
- 根因：适配器装配没有单点，后端决策（记忆中 2026-11-07 拍板「全用 MiMo」）未落到入口层。
- 修复：七个 CLI 一律改走 `create_live_adapter()` + `resolve_model_id()`；`qwen.py` 标 deprecated 或移除（属 `backend/adapters/model/*` 他方地盘，需契约 owner 协调后再动）。
- 置信度：0.93

### F-A3 [high] ORCH mock 生成器放行 `conditions_match=True`，与本体比较边界直接冲突
- 层：1 system prompt / 9 answer shaping
- 机制：`gen_analysis`（`adapters.py:297-303`）固定输出 `comparison.conditions_match=True`、reason「本次为单次模拟，无历史对照条件差异」；而业务侧权威口径是 `conditions_match` 恒为 False 且 reason 逐字取自 `comparison_context`（`analysis_data.py:206-218`、`analyst.py:143-144`）。两后果：① mock 产物若过本体 `_validate` 会被 `CONDITIONS_MISMATCH` 拒收 → Mock 流程绿灯与本体契约互斥；② 真实模型若以 mock 输出为 few-shot/参考，会学到「单次模拟=同条件」的因果越权表述。
- 根因：同角色双实现漂移（与 traffic_scout F-06 同型）——mock 生成器不走本体校验器。
- 修复：`gen_analysis` 的 comparison 三字段改取与业务侧同源的固定值（conditions_match=False + 标准 reason）；并加一条跨层契约测试：mock 产物必须能通过 `AnalystAgent._validate` 语义。
- 置信度：0.92

### F-A4 [medium] 指标口径分歧：ORCH `compute_metrics` 与业务 `summarize` 同一 preview 出两套数字
- 层：8 tool interpretation
- 机制（三处不一致）：
  1. 互动计数：ORCH 只统计**会话最后一条事件**的 interactions（`program.py:108-110`），业务侧对**全部事件**取 any（`analysis_data.py:194-197`）——中途 like 后退出的会话在 ORCH 计 0、业务计 1。
  2. 退出率形状：ORCH `exit_rate` 是裸数值（`adapters.py:285` 直接排序比较），业务是 `{numerator, denominator, value}` 三分量（`analysis_data.py:183-184`）。
  3. 零事件口径：ORCH `no_event` 仅当 `status != "active"` 才并入 incomplete（`program.py:96-100`），业务 Z 计零事件会话且 Z ⊆ U（`analysis_data.py:188-198`）。
- 后果：真实桥接后，`diagnose_preview` 拿到的 metrics_ref 与 `AnalystInput.summarize()` 数字对不上，finding 的「程序统计」引用无单一权威。
- 修复：桥接层以业务 `summarize()` 为权威计算点；ORCH metrics 仅作缓存投影并标注派生来源，或抽单点实现两边复用。**不接受**两套并存各自解释。
- 置信度：0.90

### F-A5 [medium] `step_key_analysis` 指纹不含 prompt/schema hash，重放可返回陈旧分析
- 层：12 persistence（与 traffic_scout F-01 同型）
- 机制：`step_key_analysis = analysis:{preview_id}:{version_id}:{metrics_hash[:16]}`（`registry.py:138-139`）；prompt/schema hash 仍是占位 `"b"*64`（`registry.py:20`，G-06）。提示词或 schema 变更后，同 metrics 的收据命中会重放旧分析，而分析是**解释性产物**，对提示词版本最敏感。
- 修复：prompt/schema hash 申报冻结后纳入 step_key（及收据 `input_hash` 比对，见 F-A6）。
- 置信度：0.85

### F-A6 [medium] `node_analysis` 二次弱校验与降级合并，失败原因不可区分
- 层：8 / 9
- 机制：① `_analysis_refs_valid`（`nodes.py:858-866`）只查 finding 的 segment_id 与 observation_refs，**不查** evidence_refs 全集一致性、comparison 边界、finding 数量上限——是本体 `_validate` 的弱化副本，真实桥接后两套校验会漂移；② GatewayError 软降级为 `analysis_missing`（`nodes.py:848-854`），与「模型拒收」「证据越域」合并为同一条 missing 记录，用户无法区分「没调用」「调了被拒」「调了失败」。
- 修复：校验结论由本体一次性给出、编排层只透传（单一校验来源）；`analysis_missing.reason` 细分 `not_called / rejected_scope / rejected_schema / model_failed`。
- 置信度：0.85

### F-A7 [medium] 分析产物无持久化归属，双源风险
- 层：12 persistence
- 机制：业务侧 `AnalystResult` 只落文件（`run_analyst.py:28-29`），ORCH 侧存 `analysis_{preview_id}` artifact（`nodes.py:851-856`）；无 Repository 写入点、无跨进程回执。A4 记忆台账上线后若各自写台账，会出现两套历史。
- 修复：台账/产物单一写入点（Repository），文件导出只是投影；在 A4 设计里先行定死归属。
- 置信度：0.80

### F-A8 [low] 记忆污染前瞻风险（A4 上线前必须设防）
- 层：3 long-term memory
- 机制：当前无跨轮记忆（干净）；但已批准的 A4「finding/编辑试验/重测台账」一旦允许盲测分析轮读取历史结论，评测结论将不可信（历史结论→提示词→新 finding 的自我强化回路）。
- 修复：台账读写按轮次隔离——盲测轮零读取（读接口在该轮直接拒），且隔离行为有专门测试；参照「盲测通道」三通道校准思想。
- 置信度：0.75（前瞻，非现存缺陷）

## 架构诊断（哪一层污染了什么）

| 层 | 状态 | 污染路径 |
|---|---|---|
| 1 系统提示 | ✅ 良好 | SYSTEM 明确「不替换统计/不越权比较」，与代码校验一致 |
| 2 会话历史 | ✅ 不适用 | 单次调用无历史注入 |
| 3 长期记忆 | ⚠️ 前瞻 | F-A8，A4 上线前设防 |
| 6 工具选择 | ❌ F-A2 | 后端装配双轨 |
| 8 工具解释 | ❌ F-A4 | 指标口径分歧 |
| 9 答案成型 | ❌ F-A1/F-A3 | 配置失败丢统计；mock 放行因果表述 |
| 11 隐藏修复 | ✅ 无 | 单次调用、无自动重试/修复 JSON |
| 12 持久化 | ❌ F-A5/F-A6/F-A7 | 指纹缺 prompt hash、降级合并、双源产物 |

## 有序修复计划（code-first）

| 序 | 目标 | 为什么现在 | 预期效果 |
|---|---|---|---|
| 1 | F-A1 配置失败保统计 | 一行改动消除「承诺与行为相反」，且是 F-A2 的止血 | `--live` 无凭据不再丢统计，退出码符合文档 |
| 2 | F-A3 mock 比较边界归位 | 因果边界是本 agent 的立身之本，mock 不能示范越权 | Mock 流程与本体契约一致，真实模型参考面干净 |
| 3 | F-A2 统一 live 后端装配 | 不修则真实 Adapter 接入（A2）没有可信后端 | 七 CLI 单点装配，传输栈单一 |
| 4 | F-A4 指标口径单点 | A2 桥接的前置；数字分歧会让 finding 失据 | 单一权威统计 |
| 5 | F-A6/F-A5 校验单点 + 指纹补 hash | 随 A2/A3 一起做成本最低 | 收据重放语义完整 |
| 6 | F-A7/F-A8 台账归属与盲测隔离 | A4 设计时定死，后补成本高 | 记忆不污染评测 |

## 补充发现（2026-11-07 真实模型联调阶段）

修复 F-A1/F-A3 并接通 MiMo（mimo-v2.6-pro）live 链路后，实跑暴露三个新缺陷，均已修复：

### F-A9 [high→已修] 适配器错误码被 agent 层覆盖
- 层：8/9。`analyst.py` 把一切非 received 响应归为 `MODEL_UNAVAILABLE`，丢弃适配器已分类的 `error_code`（如 max_tokens 截断→SCHEMA_INVALID、429→MODEL_UNAVAILABLE）。
- 修复：`failed(response.error_code or "MODEL_UNAVAILABLE", ...)` 透传；回归断言（`test_analysis_failure_keeps_all_metrics_and_never_retries::failed`）。

### F-A10 [high→已修] 输出 token 上限 800/1500 必然截断，live 分析不可完成
- 层：9。实测：单 finding 约 1300 输出 token，双 finding 2610，三 finding 2522-3500（中文 JSON 密集）；800 与 1500 两档均恰好触顶（output==cap、stop_reason=max_tokens）。
- 修复：`max_completion_tokens=3500`（协议硬顶 4000）；`ANALYST.md`、测试同步。

### F-A11 [high→已修] schema 不可见硬规则使合法语义输出被 `_validate` 整单拒绝
- 层：1/9（wrapper regression 的提示词形态）。pydantic `model_validator` 语义不进 JSON schema，模型无从得知，连续触发两类拒绝：
  1. `Envelope.coherent_status`：status=ok 但带 questions → "ok requires data and no questions or issues"；
  2. `_validate`：顶层 `evidence_refs` ≠ findings 引用并集 → "Analysis evidence differs from findings"。
- 修复：SYSTEM 显式列出全部硬规则（envelope 三态语义、finding ≤3/id 唯一/引用真实且片段一致、evidence_refs 精确并集、各文本非空白）；新增 `ok_with_questions` 回归用例。
- 推论（喂给 S2 harness-construction）：**凡 model_validator/代码校验的约束必须显式进提示词或改为 schema 可表达约束**，否则 live 通过率被不可见规则决定。

### 修复后验证（真实模型，MiMo mimo-v2.6-pro）
- `examples/analyst-task.json` → `needs_input`（正当结论），usage 2569/2789（真实）。
- `examples/analyst-incomplete-task.json` → `completed`，3 findings 全部引用真实 event_id、segment 一致、`conditions_match=False` 且 reason 逐字正确、文风“本次模拟中”描述性；usage 3155/2522（真实）。手算指标 N=4/S=3/C=1/U=2/Z=1/exited=1 复核一致。
- 待申报冻结：PROMPT_SHA256 `248bc92d1f53b80265e4ca4d8bf3a86359569e463c30029825057e95daf205ad`、SCHEMA_SHA256 `740d44df7e66e2826c243cbffcb359a77bf3d38260d984fface87b6e0a6fa584`（SYSTEM 再改动需重新申报）。

### 状态更新
- F-A1/F-A3/F-A9/F-A10/F-A11：**已修复并有回归**；F-A2：CLI 层已统一 MiMo 工厂（本包收口 run_analyst，其余六 CLI 由 traffic_scout 交付包完成），`qwen.py` 遗留待删除协调。
- F-A4/F-A5/F-A6/F-A7/F-A8：未修，仍为 A2/A4 工作包范围。
