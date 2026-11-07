# 交接｜内容主创线会话交付：五专家包合并 + 全面去 Key 化（2026-11-07）

本交接由内容主创（content_creator）线会话产出，覆盖当日跨线交付与本线状态。
验证基线：`main@7847e6e`（含 P0-A 七角色桥接 e95bfa0 与本会话 79bca65）。

## 工作包时间线

| # | 工作包 | 产出 |
| --- | --- | --- |
| 1 | 方案与决策 | 内容主创提案（方向/数据集/额外内容）；四项拍板：统一 MiMo、主创+审稿成对、新能力先行、记忆完整落地；后续追加「不要用 key」决策 |
| 2 | MiMo 统一核验包 | 统一接入核验 + `test_redaction.py` 移植 MiMoAdapter（凭据脱敏守卫不丢） |
| 3 | 五专家后续包合并 | 源包 `hackjunction-five-agent-followup`（基于 main@a8c0aec）优化入库；143 个差异文件过符号守卫；program.py 人工合并 |
| 4 | 全面去 Key 化 | 删根 `.env`（泄漏 Key 8 处副本）；移除 mimo/factory/start.ps1 的 .env 自动加载；文档口径统一 |
| 5 | 提交推送 | `7fa24b0`（备注归位本线）、`79bca65`（合并收尾+去 Key 化），均已上 GitHub |

## 需求映射

| 用户要求 | 落点 |
| --- | --- |
| 后续开发包优化内容写入项目 | 采纳源版 142 文件 + 新增 7：experiment_ledger、live_adapters、output_contract、material_retrieval、test_specialist_handoffs、content-creator/02-审计、five-agent-followup 交接 |
| 保留项目接口相关内容 | 符号守卫逐文件比对 def/class/导出符号/JSON 键；唯一缺口 program.py 人工合并 |
| 冲突优先优化合并 | program.py = 规则单一来源重构（validate_content_rules / validate_scoped_revision 共用）+ 回补 RuleFailure/_non_whitespace_len 兼容面 |
| 不要用 key（去 Key 化） | 树内真实 Key 残留 0；代码不读任何配置文件；凭据只经运行时进程环境变量注入（`$env:MIMO_API_KEY`），用完即弃 |

## 验证命令及结果（2026-11-07 19:2x 实测）

| 命令 | 结果 | 证据级 |
| --- | --- | --- |
| `python -m pytest tests/ -q` | **136 passed**（含 P0-A 桥接用例） | [Mock 流程] |
| `cd birthco-local && python -m pytest tests/ -q` | **482 passed** | [Mock 流程] |
| `python tools/check_review_prompt_hash.py` | OK | [接口检查] |
| `python tools/export_contracts.py --check` | PASS | [接口检查] |
| `python run_mock_demo.py --include-scout --output evidence/mock-flow-with-scout.json` | 跑通（选题→两次稿件确认→试映→定向改稿→接受） | [Mock 流程] |
| 去 Key 扫描（_load_env_file 引用 / 真实 Key 残留 / .env 存在） | 0 / 0 / 不存在 | [接口检查] |

模型生成内容未用于本轮交付；真实 MiMo 调用证据见 evidence/operator-eval-live-*.json（运营官线，运行时凭据注入方式产生）。

## 交付路径

- 五专家优化清单与验收范围：[five-agent-followup.md](five-agent-followup.md)
- 内容主创架构审计（基线 fa48ea5）：[02-architecture-audit.md](02-architecture-audit.md)
- 合并+去 Key 提交：`79bca65`；本线备注归位提交：`7fa24b0`
- 带 Scout 离线演示证据：`evidence/mock-flow-with-scout.json`

## 设计偏差

1. **program.py**：采纳「规则单一来源」重构，同时回补 `RuleFailure`/`_non_whitespace_len`（项目接口保留边界；已验证全仓库无消费者，纯兼容）。
2. **evidence/\* 12 件保留项目侧**：并行线真实运行凭据与审计锚点，不用源包副本覆盖；源包证据在其交付包内可查。
3. **qwen.py/check_qwen.py** 按并行线决策 deprecated 保留（其注明删除需契约 owner 确认）。
4. **历史改写仅一次**（c55dc00 备注归位 → 7fa24b0）；其余并行提交仅哈希随之变化、内容未动。

## 剩余问题（下一手）

1. **MiMo 控制台作废旧 Key**（用户侧一步，唯一根治）：git 历史 `615464d` 明文仍在；新 Key 只经运行时环境注入。
2. **内容主创线六阶段**：阶段 1 已有源包审计基线；注意 `e95bfa0`（P0-A 七角色真实入口桥接全通）可能已预完成阶段 3 的大半——**先对表再动手**。阶段 2（harness）/4（记忆+检索）/5（RFC/WP）/6（评测集）可参照运营官线 03/05/06-07/09 产物模式。
3. 真实 MiMo 内容质量验收、真实用户试用、Flask 队列自动编排 worker（F-01 边界）待做。
4. 多会话并行写同一工作树是常态：改共享文件前先 `git status` 避让在途改动；提交前跑双套件 + 密钥扫描。
