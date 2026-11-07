# 运营官开发链 Handoff（2026-11-07）

- 交付人：运营官执行模型工程师　→ 评审/集成
- 覆盖阶段：审计(02) → harness(03) → 编排桥接(04) → 记忆检索(05) → RFC(06/07) → 评测(09)

## 1. 改动文件

| 文件 | 改动 |
|---|---|
| `birthco-local/backend/agents/operator.py` | frozen_fields 子集冻结、需求集合相等、memory_notes 注入（account_memory 数据区）+ SYSTEM 声明 |
| `birthco-local/backend/adapters/orch_bridge.py` | **新增**：桥接夹具+真实入口（CreateTask 构造、指纹校验、ID 映射、失败映射、记忆检索注入） |
| `birthco-local/backend/memory/operator_memory.py` | **新增**：memories 表读写（Create/Read/Decision/withdraw/history）+ 三轮迭代检索 |
| `birthco-local/tests/adapters/test_orch_bridge.py` | **新增** 10 用例 |
| `birthco-local/tests/memory/test_operator_memory.py` | **新增** 8 用例 |
| `birthco-local/tests/agents/test_operator.py` | +3 用例（严格需求/冻结子集/未知冻结字段） |
| `backend/workflow/five_agent/contracts.py` | opt: 输入类型、Requirement[]/EditScope\|null、`_check_prepare_brief` 语义闸 |
| `backend/workflow/five_agent/resources/agent-interface-seven.json` | prepare_brief 输入 +requirements/+edit_scope（**契约变更待 owner 追认**） |
| `backend/workflow/five_agent/projection.py` | build_prepare_brief_input 可选 requirements/edit_scope |
| `backend/workflow/five_agent/nodes.py` | node_brief：pr 要求结构化（原 id）+ edit_scope 通道 |
| `backend/workflow/five_agent/adapters.py` | gen_brief 对齐（需求透传/旧稿缺 scope→needs_input/scope 透传）+ AdapterRouter `reals` 注入 |
| `tests/five_agent/test_operator_entry.py` | **新增** 4 用例（真实入口集成×2 + 语义闸×2） |
| `docs/experts/operations-officer/02~07` | 阶段文档 |

## 2. 需求映射

- 任务书整理保真（不改用户目标/要求）→ D2/D5 + 冻结比对 + 语义闸（F-O1/F-O5）
- 旧稿定向修改保护 → edit_scope 通道 + preserve 归一（F-O3）
- 素材引用可溯源 → 指纹校验 + ID 映射（F-O4）
- 补件问答 → needs_input 语义唯一化（F-O2）+ 三轮检索补上下文（05）
- 确认工作流指纹 → CAS 权威声明（F-O6，D6）

## 3. 验证命令与结果（2026-11-07）

```
cd birthco-local && python -m pytest tests/ -q        → 413 passed
cd .. && python -m pytest tests/ -q                    → 79 passed + 2 failed（并行会话 reviewer F-04 在办，非本链）
python tools/eval_operator.py --repeat 3               → mock pass^3 = 100%（8/8）
python tools/eval_operator.py --live --repeat 3        → U-6 后：pass@1 0.875 / pass@3 1.000 / pass^3 0.750
```
证据分级：[接口检查]✅　[Mock 流程]✅　**[真实 Adapter 联调]✅**　**[真实模型]✅（评测集 live 三轮，见 09-eval）**　[真实用户]❌（G-03）

## 4. 交付路径

- 代码：本仓库工作树（未提交；与并行 traffic_scout 改动同树，集成时按区域合并）
- 文档：`docs/experts/operations-officer/02`~`08`
- 设计冻结：06-rfc-1（D1~D9）；待派发单元：07-rfc-2（U-1~U-5）

## 5. 设计偏差

1. 桥接流的 objective/audience/platform/length_rule **不冻结**（推断字段，confirm 闸门确认）——与独立运行全字段冻结不同，理由见 04 §2。
2. 错误路径 usage 记 `unknown`（本体 DomainError 不携带 usage）——不伪造 0，符合记账纪律。
3. 旧稿素材识别暂用「首素材启发式」+ kind 归一（枚举外→source_text），语义上收排 U-2。
4. `requirements` 冻结收紧为集合相等（禁增发）——如需「允许运营官补充建议要求」，走 RFC 变更。

## 6. 剩余问题

- **U-6 已合并**（用户拍板重映射+prompt，live 指标大幅改善）；**U-3/U-4 已合并**。
- 待做：**U-1**（补件轮次限额，用户拍板维持默认限 3 轮；注意 nodes.py 与并行会话的冲突面，下个工作单元实施）、U-2（素材 kind 上收，跨模块协调）、U-5 形式验收签字（live 证据已集齐：24+ 真实调用、真实 usage、不变量全过，见 09-eval §5）。
- 契约变更已由用户**追认**；MiMo Key **暂不轮换**（历史泄漏 615464d，风险已知）；「预算无上限」=**成本授权**（不必逐次询问费用）。
- 测试未运行项：无；mock/真实标记纪律见 §3。
