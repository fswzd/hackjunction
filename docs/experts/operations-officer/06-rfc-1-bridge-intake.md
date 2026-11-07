# RFC-1｜运营官真实入口桥接与契约对齐（设计冻结）

- schema: `hackjunction.rfc.v1`　状态：**accepted（实现已合入本地工作树，待集成评审）**
- 关联：02-architecture-audit（F-O1~F-O6）、03-harness、04-orchestration-bridge
- 冻结日期：2026-11-07

## 决策记录（冻结项，变更需新 RFC）

| # | 决策 | 内容 |
|---|---|---|
| D1 | 唯一校验入口 | prepare_brief 真实调用一律经本体 `OperatorAgent.run`；编排 `ContractValidators._check_prepare_brief` 为第二道闸，mock/真实同受 |
| D2 | 冻结语义双档 | 独立运行=全字段冻结；桥接自由文本流=冻 `{input_mode, requirements(结构化时), edit_scope}`，objective/audience/platform/length_rule 为推断字段（confirm 闸门确认） |
| D3 | open_questions 协议 | open_questions ⇒ needs_input 为唯一语义（本体原语义胜出）；ok+open_questions 非法 |
| D4 | ID/指纹映射 | 桥接负责本体内部 material_id ↔ 编排 ID 双向映射；素材指纹=编排约定 `sha256(canonical({"text"}))`，桥接复算比对 |
| D5 | 需求可追溯 | pr_analysis 要求以 `requirements`（原 id+text）结构化传入并冻结为集合相等 |
| D6 | 哈希权威 | confirm CAS 唯一指纹=编排 `object_hash(payload)`；`proposal_hash` 仅标识；`brief_hash(frozen_rules)` 预留 |
| D7 | 失败映射 | INTERRUPTED→显式重发（sent-unknown）；其余 DomainError→已知 error 结果零重试；usage 未知记 unknown 不伪造 0 |
| D8 | 记忆准入 | 记忆只进 user 数据区（trust=unreviewed）；用户确认>agent 断言；密钥拒收（见 05） |
| D9 | live 后端 | 统一 MiMo（mimo-v2.6-pro，Anthropic 兼容），凭据环境配置；live 绝不回退 mock |

## 单元计分卡（已完成）

| 单元 | Tier | scope | 验收 | 结果 |
|---|---|---|---|---|
| WP-B1 桥接夹具+真实入口 | 2 | `orch_bridge.py` + 测试 | `pytest tests/adapters/test_orch_bridge.py`（10） | merged，10 passed |
| WP-B2 契约语义闸 | 2（契约共管） | `contracts.py`、`agent-interface-seven.json` | 语义拒绝 ok+questions/需求漂移/越界引用/越域 route | merged，3 passed（test_operator_entry） |
| WP-B3 投影/节点/生成器对齐 | 2 | `projection.py`、`nodes.py`、`adapters.py` | 需求结构化透传、旧稿缺 scope→needs_input、reals 钩子 | merged，全量回归 397+74 |
| WP-B4 记忆+三轮检索 | 2 | `backend/memory/`、桥接注入 | 准入纪律+注入隔离 8 测试 | merged，8 passed |
| WP-B5 冻结子集+严格需求 | 1 | `operator.py` | frozen_fields、需求集合相等 | merged，15 passed |

## 集成风险

- 与并行工作（traffic_scout 缺陷修复）同仓改动 `nodes.py/adapters.py`：改动面已收窄到 node_brief/gen_brief/reals 钩子，集成时按区域合并。
- 契约变更（D5 输入扩展、语义闸）**待契约 owner 追认**；向后兼容（旧输入形状合法）。
- [真实模型] 未验收：MiMo live 路径仅静态接线，评测集（阶段 6）就绪后跑真实调用。

## 回滚

桥接与语义闸均为增量：回滚=reverts WP-B1~B5 的 diff；`agent-interface-seven.json` 两键删去即回旧契约；`reals` 默认空不影响旧路径。
