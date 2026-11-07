# 模拟观众开发

> 交付对象：即将开发「模拟观众」模块的队友工程师。按本文可直接开工。
> 路径约定：仓库路径以 `birthco-local/` 为根（编排层在仓库根 `backend/workflow/five_agent/`，下称 ORCH）。

## 1. 背景与目标

- 位置：七角色工作流（商单需求分析员/运营官/内容主创/审稿员/流量捕捉者/数据分析师/模拟观众）中的**模拟观众**，在试映（preview）阶段对已冻结的内容快照逐段给出真实感观众反应，供分析师生成可解释反馈。
- 编排层现状：LangGraph StateGraph，preview 流程 `wait_conditions -> project -> audience_step -> commit_event -> advance`（ORCH `backend/workflow/five_agent/graph.py:5,129-147`）；mock_connected 已落地，观众能力 `awaiting_owner_handoff`（`docs/orchestration/01-contract.md:58-59`）。
- **交付物**：
  1. 观众真实入口（替换 ORCH `backend/workflow/five_agent/adapters.py:525` 的 `RealAdapterStub("simulated_audience", ("read_segment",))`），同契约 `AgentAdapter.invoke(AgentCall) -> AgentResult`；
  2. 业务侧完整试映管线（persona 抽样→逐段反应→报告），基于已有 `backend/simulation/audience_session.py` 扩展；
  3. 反馈增强：评论去同质化、立场聚合、风险预判（见 §6）；
  4. A07b 试映 HTTP API + Token 预留账本（`AUDIENCE.md:18` 缺口）。
- **不在范围**：feed 排序/推荐算法、多步信息扩散、社区发现/茧房测量、恶意 bot、封禁治理执行、点赞/关注/旗标等平台写操作、其他五个角色的实现。试映是**一次性小规模、可解释反馈**，不是生态仿真。

## 2. 现状盘点（birthco-local，核心逻辑均已实现非 stub）

| 文件 | 状态 | 要点 |
|---|---|---|
| `backend/agents/audience.py`（115行） | 完整 | `AudienceAgent.react` 单次反应；投影/封面/exit 后拒调（:70-77）；live 需显式 adapter+model_id（:58-59）；默认 MockAdapter 机械 continue/exit 并强制披露（:87-93）；失败分类 INTERRUPTED/MODEL_REJECTED/MODEL_UNAVAILABLE/SCHEMA_INVALID/INPUT_MISSING/OUTPUT_TOO_LARGE>1MiB（:96-103） |
| `backend/simulation/audience_session.py`（84行） | 完整 | 输入校验、合成封面 `cover_<version_id>`、`AudienceSimulator.run` 顺序逐 persona、预算检查在调用前（:59-61）、timeout=min(90, remaining)（:64） |
| `backend/simulation/analysis_data.py`（219行） | 完整 | 无模型的报告校验 `validate_report`（:84-151）+ `summarize()` 统计（:187-203）；「模型解释数字」属 Analyst 角色 |
| `backend/adapters/personas.py`（91行） | 完整 | 三库→`Persona` 映射与截断（:28-46）、6:3:1 最大余数法 `_allocate`（:59-73）、`random.Random(seed)` 可复现（:76-90） |
| `backend/domain/schemas.py` | 契约共管 | Persona(:180-184)、AudienceEvent(:193)、AudienceInput(:203)、Envelope(:263)、PreviewSpec/PreviewCreate(:434-441)、PreviewRead(:762)、PreflightRead(:781) |
| `contracts/schemas.json` | 部分 | AudienceEvent/AudienceInput/StoredAudienceEvent/AudienceEventPage 已导出；**AudienceSimulationInput/SimulationReport/AnalystInput 未进 contracts**（缺口） |
| `backend/storage/migrations/001_initial.sql:105-118` | 就绪 | audience_sessions/audience_events 表，事件不可变 trigger（:115）；`Repository.reserve_call/commit_step` 是 Token 预留账本入口（未接入） |
| `backend/api/` | 缺 | A07b 契约已定义（`tools/export_contracts.py:55-60`：POST `/api/v1/previews/preflight|previews`、GET `previews/{id}|events`、cancel/resume），**无 previews 实现** |
| `tools/run_audience.py` | 完整 | CLI：`python tools/run_audience.py --input examples/audience-task.json --output out.json [--live] [--mock-exit-after N]`；`--live` 与 `--mock-exit-after` 互斥（:20）；退出码 0=COMPLETED、3=未完成仍存输出、1=DomainError、2=输入/配置错（:31,36-39） |
| `tests/agents/test_audience.py`（198行）/`tests/adapters/test_personas.py`（257行） | 完整 | 风格见 §8 |
| persona 数据 | 就绪 | 仓库根 `personas/{positive,neutral,negative}_personas_database.json` 各 200 条 |

编排层挂接要点（ORCH `backend/workflow/five_agent/`）：
- 绑定：action `read_segment` ↔ agent_id `simulated_audience`（`registry.py:41`）；输出 DTO AudienceEvent（`registry.py:52`）；persona 上限 6（`registry.py:94`）。
- step_key 幂等键 `audience:{session_id}:{ordinal}:{projection_hash[:16]}`（`registry.py:134-135`）→ 投影不变重放 0 新调用。
- 预算：preview run 正常 49（≤48 观众=6 persona×8 段+1 分析）+共享重试 4=总量 53、200k tokens（`registry.py:75-76`）；单段单会话步进（`01-contract.md:58`）。
- 事件校验：commit_event 只认已提交回执；exit→会话 exited，否则推进 next_ordinal（`nodes.py:776-797`）；unknown/超时→incomplete+事件保留+**不伪造 exit**+其他会话继续（`nodes.py:755-761`）；越域 SCOPE_DENIED 计已发生调用、不写事件（`nodes.py:768-773`）。
- live 不回退：RealAdapterStub 抛 AGENT_UNAVAILABLE，绝不静默换 Mock（`adapters.py:447-457`）。

证据分级现状（`docs/orchestration/04-verification.md`）：[接口检查]✅、[Mock 流程]✅、[真实 Adapter 联调]❌、[真实模型]❌、[真实用户]❌（与观众模块直接相关的是前三项+真实模型）。

## 3. 设计思路与取舍

模拟观众的核心思路：**小规模 persona 驱动的逐段反应仿真**——每个观众是独立 persona，按冻结顺序逐段阅读，只对「已见内容」产出结构化反应事件；互动动态只保留对「可解释反馈」有贡献的部分。逐项设计决策：

| 方面 | 设计决策 | 理由与边界 |
|---|---|---|
| persona 抽样 | 正/中/负三库按 6:3:1 最大余数配额 + `random.Random(seed)` 可复现（已有） | 配比稳定、跨轮可比；不用 1:1:1 或偏好加权 |
| 多轮去重（W1） | `used_ids` 去重池，耗尽后重置 | 防止多轮试映反复抽到同一批人 |
| 跨轮演化（W1，P1） | 记录 feedback/effectiveness/learned_patterns，按效果加权后续抽样 | 人设随试映反馈微调，权重可解释、可复现 |
| 输出契约 | 固定 schema（`continue`\|`exit` + 四文本字段 + interactions），解析收在 agent 层 | 窄而稳；模型只做反应，不做自由发挥 |
| prompt 结构 | 三段式：system＝角色基座＋persona 第二人称叙述注入；user＝当前段＋引用细节＋仅输出 JSON | persona 与内容解耦；配额由 schema/预算硬约束 |
| 评论多样性护栏（W3） | 中文套话黑名单＋字符 n-gram/分词重叠 >0.7 → 升温重写一次（温度递增 ≤3 次） | 防同质化八股；失败回退原文并记录 |
| 输出解析兜底 | 剥 markdown 围栏 → `json.loads` → `raw_decode` 兜底 | 模型输出不稳时最大兼容；失败归 SCHEMA_INVALID，**无自动重试** |
| 调度顺序 | 冻结 persona 名单 → 逐 persona 顺序生成 → 事件逐条提交 | 防同段互相污染；与现有顺序调度兼容 |
| 情绪传染（W4） | 已见内容负向关键词占比 → 情绪分 → 按分档注入 persona prompt 修饰段 | 「观众情绪基调→评论风格」可解释链路；零依赖纯函数 |
| 立场聚合（W4） | 语义相似度聚合 support/neutral/oppose ＋代表性评论 | 只做聚合，不做社区发现/聚类 |
| 风险预判（W5） | keyword+LLM 双通道 → `{flagged, category, severity, confidence, reason}` verdict；keyword 白名单防误杀 | 只出报告，不做封禁/降权/落库等治理动作 |
| 反馈报告 | 情绪/互动/影响/均衡四维 ＋立场占比 | 报告骨架固定，指标可解释 |
| 明确不做 | 时间启发式点赞增量、信息扩散、茧房/同质化测量、feed 排序、封禁治理、平台写操作 | 单次试映无扩散过程；与内容质量无关的数字不可信 |
| 工程纪律 | 一切随机走 `random.Random(seed)`；纯 async；持久化只过 Repository/迁移表；中文输出 | 可复现、可集成 |
| 验收分层 | Mock 流程 → 真实 Adapter 联调 → 真实模型，证据分列 | 与项目证据分级对齐；Mock 成功不算联调成功 |

## 4. 数据模型与契约（字段级）

**4.1 输入 `AudienceSimulationInput`**（`backend/simulation/audience_session.py:13-34`）
- `confirmed: bool` — 冻结快照声明。
- `version_id: Id` — 必须匹配 `v_[a-f0-9]{32}`（:25）。
- `content_hash: Hash` — 与 `content` 实算一致（:26）。
- `content: ContentDelivery`（`backend/domain/schemas.py:115-129`）— `titles`×3 互异、`cover_copy`、`segments[]` 每段 `{segment_id, kind, text, source_refs}`。
- `personas: list[Persona]` — 1-6 个，id 唯一、goal/knowledge 非空、preferences 非空白（:32-33）。
- `max_segments: int` — 1-8，默认 8；封面占 1 段；cover+body 超限**直接拒**不截断（:28）。
- `max_calls: int` — 1-48，必填无默认（:20）。
- `max_active_seconds: int` — 1-1200，默认 1200。
- 其它校验：正文片段非空白、全稿非空白字符 ≤20000（:30-31）；body ID 不得撞合成封面 ID `cover_<version_id>`（:29,37-39）。

**4.2 `Persona`**（`backend/domain/schemas.py:180-184`）：`id`、`goal`（≤1000 截断）、`knowledge`（≤1000）、`preferences`（≤10 条）。映射来源见 `backend/adapters/personas.py:28-46`（traits+tone/engagement_level/argument_approach 拍平进 preferences；demographics 压进 knowledge；profession 双位置容错 :13-16）。注意 `name/type/engagement_level` 无独立承载位——扩字段属跨模块变更（§9）。

**4.3 每次调用输入 `AudienceInput`**（`backend/domain/schemas.py:203`）— **严格 4 字段投影**：`persona` / `current_segment`(VisibleSegment) / `visible_history`（≤7，严格前缀）/ `own_previous_reactions`（≤7，仅本会话自身事件尾部）。无全文、无总片段数、无他人反应（`backend/agents/audience.py:14-20` SYSTEM 提示强制）。投影构造 `ORCH backend/workflow/five_agent/projection.py:53-83`；隔离五重断言 `assert_audience_isolation`（:86-114）：键集合恰四字段、current_segment 属冻结版本、history 精确前缀、序列化投影不含未来段文本（≥12 字符子串扫描 :101-105）、反应/persona 归属校验；违反即 IsolationError/SCOPE_DENIED 且发生在**调用发出前**。

**4.4 输出 `AudienceEvent`**（`backend/domain/schemas.py:193`；`contracts/schemas.json:1097-1170`）：
| 字段 | 类型/约束 |
|---|---|
| `segment_id` | 必须 = 当前段 |
| `action` | enum `continue` \| `exit` |
| `understanding` | str ≤1000，非空 |
| `question` | str ≤1000 \| null（非空串不允许） |
| `reaction` | str ≤1000，非空 |
| `interactions` | 数组，元素 `like`\|`comment`\|`save` 各 ≤1、总数 ≤3 |
| `comment_text` | 有 `comment` 交互时非空 str ≤1000，否则 null |

全部 required、additionalProperties=false；包装在 `Envelope[AudienceEvent]`（schema_version=`creator-agent.v1`，`schemas.py:263`）。语义校验 `validate_event`（`backend/agents/audience.py:23-36`）。

**4.5 会话状态流转**：`session{session_id, persona_id, outcome: incomplete→completed|exited, stop_reason, cursor, events[]}`（`audience_session.py:55`）。`stop_reason` 枚举：`viewer_exit|call_budget|time_budget|unknown_remote_outcome|invalid_or_failed_response`（`analysis_data.py:31`）。事件是连续前缀（seq=ordinal 对应 segment 序），exit 后不得再有事件（`analysis_data.py:104`）；全局 stop 后未访问会话保留 incomplete、零事件不伪装 exit（`audience_session.py:57,141-146`）。status：有 unknown 调用→INTERRUPTED，全 completed/exited→COMPLETED，否则 INCOMPLETE（:77）。

**4.6 输出报告 `SimulationReport`**（`analysis_data.py:62-81`）：`mode`、`medium:"text"`、`version_id`、`content_hash`、`input_hash`、`status`、`persona_count`、`segment_count`、`sessions[]`、`calls[]`、`calls_attempted`、`call_budget`、`time_budget_seconds`、`usage{known_total_tokens, usage_not_reported_calls, remote_outcome_unknown_calls}`、`mock_fixture_exit_ordinal`、`is_simulation:True`、`predicts_real_traffic:False`、`automatic_resume:False`、`explicit_new_request_required:True`。`validate_report`（:84-151）：input_hash 绑定、call 顺序/前缀哈希复算（:122-123）、received call 与 observation 一致、失败 call 必须解释 incomplete、usage 汇总复算。

**4.7 下游**：`AnalystInput{analysis_requested, source, simulation, comparison_*?（需 allow_descriptive_comparison）}`（`analysis_data.py:154-180`）；`summarize()` 指标 N/S/C/U/Z/exited/coverage_ratio/completion_ratio/per_segment/interaction_intentions（:187-203）。

**4.8 内容链路对应**：上游原始材料→Brief→内容创作/审校（其他角色）→**用户接受冻结**＝`confirmed=true` + `version_id` + `content_hash`；观众只见 `ContentDelivery` 投影（segments 携带 `source_refs` 可回溯素材）；观众报告以 `input_hash` 绑定该冻结版本，分析 finding 的 `observation_refs` 必须是真实已提交事件 id（`docs/orchestration/04-verification.md:43,57`）。规则报告/审校报告属上游角色产物，**不进观众投影**（信息隔离，`01-contract.md:77`）。

## 5. 生成流程设计

分步管线（每 persona × 每段 = 一次调用，单段单会话步进）：
1. **冻结/预检**：`preview_conditions` 闸门冻结 version+scenario+预算后才建会话，拒绝=零观众调用（`docs/orchestration/03-control.md:16`）；业务侧对应 `AudienceSimulationInput` 校验。
2. **persona 抽样**：`sample_personas`（seed 走 `random.Random(seed)`，`personas.py:76-90`）→ 6 persona 上限。
3. **投影**：`build_audience_input` 生成四字段输入 + `assert_audience_isolation` 预断言（ORCH `projection.py:62-114`）；业务侧镜像同一语义。
4. **反应生成**：`AudienceAgent.react` → adapter（live：真实模型；mock：可脚本化）→ 输出解析校验。
5. **提交**：事件入库（`audience_events` 不可变 trigger）；exit→会话 exited；预算检查在调用**前**（`audience_session.py:59-61`）。
6. **汇总**：`SimulationReport` +（W4/W5）反馈报告 → `AnalystInput`。

**prompt 组装要点**（三段式，中文）：
- system = 通用语气基座 + persona 注入（goal/knowledge/preferences，以第二人称叙述）+ 已读历史说明（`visible_history`/`own_previous_reactions` 已在 payload 投影中，**不重复注入全文**）。
- user = 当前段 + 「引用当前段至少一处具体细节」+ 输出仅 AudienceEvent JSON（禁编造 ID、只回正文）。
- 软配额：comment 倾向、interactions ≤3 由 schema 硬约束；可加 REACTION MIX 软目标防全 like。
- **禁止**：完整 AgentCall/GraphState/其他 persona/未来段进入 prompt（`interaction-design.md:89`）。
- prompt/schema hash 须申报后冻结（G-06，现为占位 `"b"*64`，`registry.py:20`），否则 `input_hash`/`step_key` 冻结语义不完整。

**输出解析校验**：JSON 剥围栏→`json.loads`→`raw_decode` 兜底 → `validate_event` → 过 ContractValidators 的 AudienceEvent 校验（ORCH `contracts.py:208-212,253-257`）。坏事件不入库（`tests/agents/test_audience.py:114`）。失败**无自动重试**、无自动恢复（`AUDIENCE.md:16`）；重试只能走编排层共享重试额度（4 次，每次过中央 BudgetGate，`docs/orchestration/02-orchestration.md:52-54`）。

**mock/真实区分**：MockAdapter 机械 continue/exit，`mock_fixture_exit_ordinal` 披露且 live 禁用合成 mock（`audience.py:87-93`、`AUDIENCE.md:10`）；Mock 可脚本行为（真实实现的行为参照）：`gen_audience_event`（ORCH `adapters.py:355`）、p_exit_first 封面退/p_full 读完/p_exit_mid 第 2 段退/p_timeout_mid unknown/p_ask 提问（:382-389,461-462）；每次调用记录 `model_visible_input` 与 `context_seen_by_model=False` 供隔离断言（`01-contract.md:80-81`）。live 需显式 adapter+model_id；适配器禁止隐藏重试/自动修 JSON/换模型/额外调用（`02-orchestration.md:52-54`）。

**随机种子**：一切随机（persona 抽样、W3 重生成温度抖动、W4 采样）必须走 `random.Random(seed)` 分支以保可复现。

## 6. 互动动态取舍

**最小必要集**（P0，一次性试映必须）：
1. persona 评论仿真本体（§5 管线）。
2. **情绪传染**（W4）：已见内容负向关键词占比 → 情绪分（如占比 >0.5→-0.8、>0.3→-0.5、>0.1→-0.2、否则 +0.1）→ 按分档拼接 persona prompt 修饰段——给出「观众情绪基调→评论风格」的可解释链路；零依赖纯函数，词表换本项目受众语料。
3. **立场聚合**（W4）：按语义相似度把各 persona 的 reaction/comment 聚成 support/neutral/oppose 占比 + 每类代表性评论（每段与全稿两级）；只做聚合，不做社区发现。
4. **风险预判**（W5）：keyword+LLM 双通道 verdict（`{flagged, category, severity, confidence, reason, detected_keywords}`），keyword 白名单防误杀，LLM 判定失败降级 keyword-only；severity→反馈强度走纯配置映射。

**P1（多轮试映增强）**：persona 跨轮反馈演化（effectiveness/learned_patterns 加权）、comment 去同质化高温重写（W3）、争议预警文案（flag 阈值**配置化**，默认值取保守档）。

**明确不做**：时间启发式点赞增量、信息扩散模拟、茧房/同质化测量、feed 排序、线程监控式实时大盘（只保留四维报告骨架）。

## 7. 工作包分解

| WP | 目标 | 改动文件（互斥范围） | 依赖 | 验收条件与命令 |
|---|---|---|---|---|
| W1 Persona 选择器 | AudiencePersonaSelector：used_ids 去重池+耗尽重置、多轮不重复；（P1）跨轮 feedback | `backend/adapters/personas.py`、`tests/adapters/test_personas.py`（独占） | 无 | 抽样可复现（同 seed 同结果）、1-6 配额、去重；`python -m pytest tests/adapters/test_personas.py -q` |
| W2 生成核心+prompt | live prompt 组装（§5）、AudienceEvent 输出解析校验、失败分类 | `backend/agents/audience.py`、`tests/agents/test_audience.py`、`backend/simulation/audience_session.py`（独占） | W1 | 同一套契约测试过 mock 与假 live（`AudienceAgent(fixture, mode="live", model_id="fixture")` 风格）；`python -m pytest tests/agents/test_audience.py -q`；`python tools/run_audience.py --input examples/audience-task.json --output out.json` 退出码 0 |
| W3 内容护栏（P1） | comment_text 去同质化：中文黑名单+字符 n-gram/jieba 词重叠>0.7→高温重写一次（≤3 次温度递增） | 新建 `backend/simulation/audience_quality.py` + W2 文件内钩子 | W2 | 同 persona 跨段 comment_text 相似度低于阈值；失败回退原文并记录；同上 pytest + `--mock-exit-after` 分支 |
| W4 反馈聚合 | 情绪传染 + 立场聚合 support/neutral/oppose + 四维反馈报告 | 新建 `backend/simulation/audience_feedback.py`（独占） | W2 | 报告含四维+立场占比+代表性 comment，全部引用真实事件 id；`python -m pytest tests/ -q`（新增 tests/simulation/test_audience_feedback.py） |
| W5 风险预判 | keyword+LLM 双通道 verdict → 报告风险段 | 新建 `backend/simulation/audience_risk.py`（独占） | W2 | verdict 可解释（category/severity/confidence/reason/detected_keywords）；LLM 判定失败降级 keyword-only；同上 pytest |
| W6 A07b API+账本 | previews HTTP API + `Repository.reserve_call/commit_step` Token 预留账本 + 进程恢复（步进幂等） | 新建 `backend/api/previews.py` + `tests/api/`（独占） | W2 | preflight→create→get→events→cancel/resume 全链路；重放 0 新调用；跨进程重启靠回执+显式 reinvoke；`python -m pytest tests/api -q` |
| W7 契约导出+验收收口 | AudienceSimulationInput/SimulationReport/AnalystInput 进 contracts；prompt/schema hash 申报冻结；真实模型验收 | `contracts/schemas.json`、`tools/export_contracts.py`（**共管**，改前协调） | W2-W6 | `python tools/export_contracts.py` 后 diff 仅含新增；跑同一套契约测试达 [真实 Adapter 联调]；`--live` 输出 usage 为真实值 |

- 各 WP 交付按工作包卡六节结构（前置/允许文件/实施步骤/验收/恢复/交付）记 Handoff（改动/hash/测试映射/命令/退出码/fixture 类型/mode），作者只提交 review，集成由 Integrator 判定；`tests_run>0` 才算通过，依赖缺失标 blocked **不伪造通过**。
- 别人地盘只读不改：`backend/adapters/model/*`、`backend/storage/*`、`tools/demo_team.py:125-132`、`tools/run_analyst.py`；`backend/domain/schemas.py`、`backend/domain/errors.py:52`（validate_audience_scope）改动需协调。

## 8. 验证与证据

- 测试约定：pytest；`tests/conftest.py` 仅注入 sys.path；`tests/agents/test_audience.py` 风格——`input_data()` 内联构造冻结输入并用 `content_hash()` 算指纹（:17-25），Fixture 包装 MockAdapter 按 call_id 回放+transform 钩子篡改输出测失败分支（:34-40），假 live 测真实校验路径（:43）。已有覆盖：投影不泄漏未来/全文（:62）、exit 只终本会话（:79）、mock 披露且 live 禁用（:89）、预检拒绝（:97）、坏事件不入库（:114）、comment/question 保留（:134）、exit 后拒调（:142）、call 预算保零事件会话（:150）、时间预算（:158）、失败不重试保 usage（:166）、非法前缀调用前拒绝（:186）。
- 证据分级（`docs/orchestration/04-verification.md:3-14`）：观众真实入口替换后跑**同一套契约测试**才算 [真实 Adapter 联调]；[真实模型] 要求真实 usage 上报（unknown 不得填 0）、真实凭据来源、与 Mock 合成 usage 区分。
- mock 标记纪律：`mock_fixture_exit_ordinal` 披露 + `is_simulation:True/predicts_real_traffic:False` 固化在输出常量（`analysis_data.py:78-79`）；「模拟观众的模型模拟」是业务角色行为，「开发 Mock」是队员替身，**两者不得混称**，Mock 成功不代表联调成功（`04-verification.md:13-14`）。
- 验收命令（可直接复制）：
  ```
  python -m pytest tests/agents/test_audience.py tests/adapters/test_personas.py -q
  python tools/run_audience.py --input examples/audience-task.json --output out.json
  python tools/run_audience.py --input examples/audience-small-budget.json --output out.json   # max_calls=1 演示 call_budget 耗尽
  python tools/run_audience.py --input examples/audience-task.json --output out.json --live    # W7 后
  python tools/export_contracts.py
  ```
- 硬上限速查：8 片段含封面（正文≤7）、20000 非空白字符、每调用输出 ≤800 token/90s、响应 ≤1MiB、max_calls≤48、max_active_seconds≤1200。

## 9. 风险与待决

**已知缺口（G-xx，`04-verification.md:74-95`）**：
- **G-01（直接阻塞）**：观众真实入口/样例/调用计划未提交，[真实 Adapter 联调] 无法开始——W2/W7 首要交付。
- **G-05**：无 live 模型接入、usage 为合成值；真实 LLM 需等 A03a 模型接口 owner；「同条件比较禁放行」。
- **G-06**：prompt/schema hash 占位（`registry.py:20`）；观众 prompt hash 须 owner 申报后冻结。
- **G-02**：langgraph-checkpoint-sqlite 未装（现 MemorySaver）；长会话需保证步进幂等以兼容跨进程恢复。
- **G-03**：无 preview_conditions 闸门 UI（[真实用户] 证据缺失，观众模块本身不涉用户交互）。
- **G-07**：真实反馈导入需显式授权，禁止借 diagnose_preview 偷渡新请求。
- **G-09（安全）**：仓库根 `an.py` 明文 API Key——接真实模型前**必须移除并轮换**；凭据一律走环境配置，测试用去敏夹具（离线 fixture、不读凭据）。

**需提交架构师的契约疑问**：
1. Persona 扩字段（name/type/engagement_level/数值人格）承载位——现仅 4 字段（`schemas.py:180-184`），扩字段需改 domain schema 并同步 `audience_session.py:32-33` 校验与 contracts 导出，属跨模块变更。
2. AudienceSimulationInput/SimulationReport/AnalystInput 导出进 `contracts/schemas.json` 的版本策略（W7）。
3. `AudienceEvent.interactions` 含 like/save——语义上是**模拟反应记录**、非平台写操作，与「不执行 like/follow/flag」的写操作边界不冲突；确认后按现契约开发。

**工程注意**：情绪/风险词表须用本项目受众语料初始化（勿用通用英文新闻词表）；所有规则阈值（多样性 0.7、flag 阈值、severity 映射）配置化；LLM 风险预判与仿真共用 API 配额时注意限速；反应生成全部为纯 async，禁用「线程池跑 async」式写法。
