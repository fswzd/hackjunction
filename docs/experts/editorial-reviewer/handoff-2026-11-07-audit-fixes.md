# 交接｜审稿员架构审计 + 阶段 1 缺陷修复（2026-11-07）

工作包：审稿员全链路架构审计（阶段 1）+ 可立即修复的 code-first 缺陷 F-01/F-02/F-04 + live 后端统一 MiMo。
证据分级：本轮全部为 [接口检查] + [Mock 流程]；[真实 Adapter 联调]/[真实模型] 未做。

## 改动文件

| 文件 | 改动 |
|---|---|
| `docs/experts/editorial-reviewer/02-architecture-audit.md` | 新增：12 层审计报告，7 项发现（3 high / 2 medium / 1 low / 1 security），含有序修复计划 |
| `backend/workflow/five_agent/nodes.py` | node_review：素材指纹改哈希素材正文（与 traffic/brief 同公式，F-01）；brief 引用未知素材抛 `INPUT_MISSING`；`_call` 支持按步传 `prompt_schema_version` |
| `backend/workflow/five_agent/registry.py` | `REVIEW_PROMPT_SCHEMA_HASH` 冻结真实值（F-02，替换 `"b"*64` 占位） |
| `backend/workflow/five_agent/adapters.py` | `gen_review`（F-04）：issue/claim/evidence 的 location 全部取自冻结版本真实段落 ID；文档标注"开发 Mock＝队员替身，不代表内容质量" |
| `tools/check_review_prompt_hash.py` | 新增：校验 registry 冻结 hash 与业务侧 SYSTEM+schema 实算 hash 一致（两树同名包，子进程计算） |
| `tests/five_agent/test_reviewer_fixes.py` | 新增 7 个复现用例（F-01×3、F-02×2、F-04×2） |
| `birthco-local/backend/adapters/model/mimo.py` | `validate_base_url` 补 host 白名单（仅 `api.xiaomimimo.com`，对齐原 qwen 栈安全姿态） |
| `birthco-local/tests/adapters/model/test_transport.py`、`test_redaction.py` | 传输安全/脱敏测试从 Qwen 栈迁移到 MiMo 栈 |
| `birthco-local/backend/adapters/model/qwen.py`、`tools/check_qwen.py` | 标注 deprecated（删除需契约 owner 点名确认，被安全策略拦截） |
| `birthco-local/tests/agents/test_team_demo.py` | 离线断言补 MiMoAdapter 构造禁止（原只禁 QwenAdapter） |
| `birthco-local/.env.example`、`birthco-local/完整使用说明.md`、`REVIEWER.md` | Qwen/DASHSCOPE 残留清为 MiMo（MIMO_API_KEY/MIMO_MODEL_ID=mimo-v2.6-pro） |
| `.env`（不入库） | MIMO 凭据环境配置 |

## 需求映射

| 需求 | 落点 |
|---|---|
| 审计（skill: agent-architecture-audit） | 02-architecture-audit.md：7 发现 + 诊断表 + 修复计划 |
| F-01 陈旧审稿收据重放 | node_review 素材正文 hash + 3 个复现用例（含端到端"素材变更→重新审稿、未变→零新调用"） |
| F-02 prompt 冻结语义 | 真实 hash 冻结进 registry + input_hash 绑定 review 专属 prompt 版本 + 校验工具 + 2 个复现用例 |
| F-04 mock 伪造段落引用 | gen_review 真实 location + 2 个复现用例（含无段落回退 cover） |
| live 后端统一 MiMo | 七 CLI 全走 factory.create_live_adapter()（mimo-v2.6-pro）；传输/脱敏测试迁移；host 白名单补齐 |

## 验证命令及结果

- `python -m pytest tests/ -q`（编排层）→ **81 passed**（含 7 个新增复现用例）
- `cd birthco-local && python -m pytest tests/ -q` → **406 passed**
- `python tools/check_review_prompt_hash.py` → `OK: REVIEW_PROMPT_SCHEMA_HASH=658c498f...`
- Mock 输出（确定性夹具）与真实调用分别标记；本轮**无真实模型调用**、无模型生成产物进入交付

## 设偏差（相对修复前行为）

1. **审稿收据失效**：`REVIEW_PROMPT_SCHEMA_HASH` 从占位变真实值 + review 专属 prompt 版本进 input_hash——修复前持久化的审稿收据在新指纹下不再命中，恢复执行会发起新调用（预期行为，避免陈旧结果）。
2. **素材缺失语义**：brief 引用未知素材 ID 时 review 步抛 `INPUT_MISSING`（修复前静默哈希 ID 值）。
3. **mock gen_review 引用**：issue 默认定位从固定 `seg_body_1` 改为按冻结版本段落表推导（body 优先、无段落回退 cover）——依赖旧固定 ID 的夹具如有断言需按真实段落 ID 更新（本轮全量测试无此情况）。
4. **MiMo base URL 白名单收紧**：仅允许 `https://api.xiaomimimo.com/anthropic`；自定义端点需求需契约 owner 评审后放开。

## 剩余问题（进入后续阶段）

- **F-03 [high]** 规则双轨（content-rules-v1 同名两套）→ 阶段 2/5：单一来源化或双 rule_version 改名+映射声明（`domain_schemas.json` 有 const 约束，属契约变更）
- **F-05 [medium]** 桥接夹具缺口（编排 refs ↔ ReviewInput）→ 阶段 3（team-agent-orchestration）首要交付
- **F-06 [low]** code-enforced / prompt-only 两栏声明 → 阶段 2（agent-harness-construction）
- **F-07 [security]** MiMo Key 已在会话明文暴露 → **用户须轮换**后更新 `.env`
- **qwen.py/check_qwen.py 删除**：被安全策略拦截，需你点名确认删除这两个文件（或保留为 deprecated）
- **[真实 Adapter 联调]/[真实模型]**：阶段 3/6；G-06（prompt hash）已闭环，G-05（live 接入）待桥接
- node_draft 的素材指纹（`object_hash({"text": mid})`）是 F-01 同型缺口，但节点归内容主创工作包（其开发决策为"主创+审稿成对"），未越界修改——由该工作包修复
