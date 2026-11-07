# 交接｜数据分析师 架构审计 + critical 修复 + MiMo live 首次联调（2026-11-07）

工作包：S1 架构审计（12 层栈）→ 审计产出的 critical 修复 F-A1/F-A3 → live 联调暴露的 F-A9/F-A10/F-A11 → [真实模型] 首次通过。
证据分级推进：分析师角色 [真实模型] 由 ❌ → ✅（mock/真实分列，见下）。

## 改动文件

| 文件 | 改动 |
|---|---|
| `docs/experts/data-analyst/02-architecture-audit.md` | 新增：12 层审计报告（F-A1..F-A8 + 联调阶段 F-A9..F-A11），含架构诊断与有序修复计划 |
| `birthco-local/tools/run_analyst.py` | 抽出 `run_live()`：adapter 构造 + model_id 解析整体纳入配置失败域（缺失即 `configuration_failure` 保统计，不再 exit 2 丢产物）；live 后端改走 `factory.create_live_adapter()/live_model_id()`（MiMo） |
| `birthco-local/backend/agents/analyst.py` | ① 失败映射透传 `response.error_code`（不再笼统 MODEL_UNAVAILABLE）；② `max_completion_tokens` 800→3500；③ SYSTEM 增补 schema 不可见硬规则清单（envelope 三态、finding 约束、evidence_refs 精确并集） |
| `backend/workflow/five_agent/adapters.py` | `gen_analysis`（mock）比较边界归位：`conditions_match=False`、reason 逐字=业务单版本分支、finding 文案改描述性（共享文件，已留跨层契约测试防再漂） |
| `birthco-local/tests/agents/test_analyst.py` | +4 用例：`run_live` 配置失败保统计×2、单版本 reason 冻结钉住、`ok_with_questions` 拒收；1 个既有用例补错误码透传断言 |
| `tests/five_agent/test_analysis_contract.py` | 新增：跨层契约 2 用例（mock 产物不得宣称同条件/因果、finding 描述性+引用真实观察） |
| `birthco-local/ANALYST.md` | live 段更新：MiMo 环境变量/工厂、3500 token（附实测依据）、错误码透传语义 |

## 需求映射

| 需求 | 落点 |
|---|---|
| S1 架构体检（agent-architecture-audit） | `02-architecture-audit.md`：11 项发现、证据 file:line、置信度、有序修复计划 |
| F-A1 配置失败丢统计 | `run_live()` 失败域 + 2 个复现用例 |
| F-A3 mock 因果越权 | gen_analysis 归位 + 2 个跨层契约用例 |
| F-A2 live 后端统一 MiMo | run_analyst 走工厂（其余六 CLI 由 traffic_scout 交付包完成）；`.env` 配置 `MIMO_API_KEY`/`MIMO_MODEL_ID=mimo-v2.6-pro` |
| F-A9/F-A10/F-A11（联调暴露） | 错误码透传 / token 上限 3500 / 硬规则显式化，各带回归 |
| [真实模型] 首证 | live 两次真实调用通过（见下） |

## 验证命令及结果

- `cd birthco-local && python -m pytest tests/ -q` → **388 passed**（基线 384 + 新增 4）
- `python -m pytest tests/five_agent -q`（编排层）→ **70 passed**（含新增 2 个跨层契约用例）
- `python tools/run_analyst.py --input examples/analyst-task.json --output analyst-result-mock.json` → 退出码 0【mock 输出】N=2、1 finding
- `python tools/run_analyst.py --input examples/analyst-task.json --output analyst-result-live.json --live` → 退出码 0【真实调用 MiMo】`needs_input`，usage input 2569 / output 2789（真实计费值）
- `python tools/run_analyst.py --input examples/analyst-incomplete-task.json --output analyst-result-live-incomplete.json --live` → 退出码 0【真实调用 MiMo】`completed`，3 findings 引真实 event_id、比较边界正确，usage 3155 / 2522；手算指标 N=4/S=3/C=1/U=2/Z=1/exited=1 复核一致【模型生成产物，质量未验收，仅作联调证据】
- 产物文件（`birthco-local/` 下）：`analyst-result-mock.json`【mock】、`analyst-result-live.json`、`analyst-result-live-incomplete.json`、`probe-raw-output.json`（F-A11 诊断用原始模型输出【模型生成】）

## 设计偏差（相对改动前）

1. **token 上限 800→3500**：800/1500 两档实测必然截断（单 finding≈1300、三 finding≈2500-3500 输出 token）；3500 仍在协议硬顶 4000 内。属实现参数，但与旧文档口径不同，已在 `ANALYST.md` 同步。
2. **SYSTEM 增补硬规则清单**：pydantic `model_validator` 语义不进 JSON schema，模型不可见即必踩；显式化后 live 首次通过。副作用：prompt hash 变更（申报值见下）。
3. **错误码透传**：失败分类从「一律 MODEL_UNAVAILABLE」改为透传适配器已分类错误码，失败语义更准确。
4. **run_analyst live 由 Qwen/QWEN_MODEL_ID → MiMo 工厂**：与统一后端决策一致（`factory.py` 单点）。
5. **gen_analysis（ORCH mock）文案与比较值变更**：从「conditions_match=True + 反馈集中在理解成本」改为描述性 + `conditions_match=False`；影响 ORCH mock 流程演示文案，已用跨层契约测试钉住。

## 剩余问题（下一工作包）

- **A2 ORCH 真实入口桥接**（未动）：替换 `RealAdapterStub("data_analyst")`、F-A4 指标口径单点（ORCH `compute_metrics` vs 业务 `summarize` 三处分歧）、F-A6 校验单点与降级细分、F-A5 step_key 纳入 prompt hash。
- **A4 记忆台账**（未动）：finding/编辑试验/重测台账 + 盲测隔离（F-A8 前瞻防线）。
- **A5 评测集**（未动）：金标（rubric 标注）+ 对抗样本 + 手算回归扩展；两次 live 输出可作首批种子样本。
- **A6 契约导出**（未动）：AnalystInput/SimulationReport 进 `contracts/schemas.json`（共管，走 RFC）。
- **prompt/schema hash 申报冻结**（G-06）：PROMPT_SHA256 `248bc92d1f53b80265e4ca4d8bf3a86359569e463c30029825057e95daf205ad`、SCHEMA_SHA256 `740d44df7e66e2826c243cbffcb359a77bf3d38260d984fface87b6e0a6fa584`；SYSTEM 再改动需重新申报。
- 其余六个角色 CLI 的「配置失败丢产物」同型问题（F-A1 类）：非本工作包，未动。
- Key 在聊天中暴露过，建议轮换后仅更新 `.env`（`.env` 已被 .gitignore 覆盖）。
- 开发期共发 5 次计费模型调用（诊断探针 3 + 验收 2），均为 mimo-v2.6-pro，已如上标记。
