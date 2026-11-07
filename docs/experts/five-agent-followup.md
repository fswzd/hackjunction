# 五专家后续开发交接

从 `fswzd/hackjunction` 的 `main@fa48ea5` 开发，交付前合入 `main@a8c0aec` 的模拟观众与契约更新。参考 LangGraph 的条件路由和人工闸门，以及 Pydantic Evals 的用例和评分分离。沿用仓库已有 LangGraph、Pydantic 和 SQLite，适配代码在本仓库实现。[LangGraph](https://github.com/langchain-ai/langgraph) · [Pydantic Evals](https://github.com/pydantic/pydantic-ai/tree/main/docs/evals)

| 角色 | 本轮实现 | 验证 |
| --- | --- | --- |
| 运营官 | 业务入口接到编排。补件默认三轮，重复提交不重复落库。旧稿只接受显式 `existing_draft` 素材。补件可以使用剩余调用槽，内容 run 的总上限仍是七次 | 第四轮拦截、三轮后成功交付、显式素材类型 |
| 流量捕捉者 | 基于任务授权素材作三轮内检索。真实入口验来源、保留选题确认，按角色路由。重建带 Scout 的离线流程 | 选题进入 Brief、伪造引用拒绝、原用量保留、无重试 |
| 内容主创 | 冻结 Brief、素材和版本。按步骤预留段落 ID。初稿及已入库版本的定向修订调用业务入口。修订检查和审稿规则共用 | 基线保留、改稿引用原 finding、未经授权不能改 |
| 审稿员 | 解引用实际稿件、规则报告与授权素材，检查一致后才进入业务审稿。素材检索保留全部来源，提示词变更使旧收据失效 | 规则单一来源、离线真实入口、输出 schema 比对 |
| 数据分析师 | 共享统计和引用校验。按冻结事件前缀接入本体。收据绑定试映事件和提示词。增加建议、用户选择、候选修订及重测台账 | 手算统计、六人八段上限、盲测零读取历史、失败保留指标 |

## 使用

在仓库根目录使用 Python 3.13。

```powershell
python -m pip install -r birthco-local/requirements-dev.lock langgraph==1.1.10
python -m pytest tests/five_agent -q
python run_mock_demo.py --include-scout --output evidence/mock-flow-with-scout.json
python tools/check_review_prompt_hash.py
Push-Location birthco-local
python -m pytest tests -q
python tools/export_contracts.py --check
Pop-Location
```

运行离线联调测试时，五个业务入口由程序注入确定性的传输夹具。用户确认与选题仍由工作流闸门绑定。用下列方式为单个角色启用真实模式，使用运行时进程环境变量注入的 MiMo 凭据（不落盘、不读文件；`.env.example` 仅是变量名参考）。

```python
from backend.workflow.five_agent.adapters import AdapterRouter
from backend.workflow.five_agent.driver import OrchestrationDriver
from backend.workflow.five_agent.repository import Repository

repo = Repository("workflow.sqlite")
router = AdapterRouter(repo, agent_modes={"traffic_scout": "live"})
driver = OrchestrationDriver(repo, router=router, max_input_rounds=3)
```

可选角色是 `operations_officer`、`traffic_scout`、`content_creator`、`editorial_reviewer`、`data_analyst`。商单需求分析与模拟观众维持已有 Mock 路径。配置缺失会给出错误。未知的远端结果进入中断，需显式处理后才能重发。

## 契约与记录

工作流继续使用 `seven-agent.v0.1` 的引用型输入、结果和 Metrics DTO。独立分析工具的 `AnalystInput/SimulationReport` 保持兼容。新导出的 `PreviewAnalysisInput` 只承载工作流实际持久化的会话与事件，不合成未发生的供应商回执。两个入口使用相同的统计定义和输出核验。

程序强制版本归属、输入指纹、前缀、引用、用量、段落范围和包络形状。写作质量、机会价值、建议是否有用仍靠提示词及实际评测判断。模拟数据保留模拟标签。

把 `blind: true` 与可选的 `retest_of` 放进已批准的试映场景。重测可引用本任务的同一版本或直接父版本的试映。分析模型只看本轮事件。回看台账用 `driver.preview_history(preview_id)`，盲测预览调用这个入口会被拒绝。

合并后编排 99 项、业务 478 项测试通过，契约导出和审稿提示词指纹检查通过。带 Scout 的离线演示覆盖选题、两次稿件确认、试映和定向改稿。真实 MiMo 质量、真实用户试用，以及 Flask 队列自动启动编排 worker 仍需单独验收。
