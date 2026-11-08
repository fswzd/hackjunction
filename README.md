# 众幕 AI — 多 Agent 自媒体内容工作台

七个业务 Agent 协同，把一个内容需求从选题到成稿全流程跑通：
**选题捕捉 → 商单分析 → Brief 确认 → 创作 → 规则/审校 → 试映 → 定向改稿 → 导出**。

最终交付物是一份**人工验收通过的图文内容包**（Markdown/TXT），包含三条标题、封面文案、分段正文（改稿附变化记录）。不做发布、收款、视频成片。

默认离线 Mock 模式（零联网、零费用、零密钥），可按需切换真实模型（OpenAI / MiMo / 通义千问等 OpenAI 兼容接口）。

---

## 目录

- [项目架构](#项目架构)
- [七角色说明](#七角色说明)
- [快速开始](#快速开始)
- [配置 API Key（接入真实模型）](#配置-api-key接入真实模型)
- [使用教程](#使用教程)
- [命令行参数](#命令行参数)
- [测试与验证](#测试与验证)
- [目录结构](#目录结构)
- [安全提示](#安全提示)
- [常见问题](#常见问题)

---

## 项目架构

```
┌─────────────────────────────────────────────────────────┐
│                     前端工作台 (frontend/)                │
│              Vite + React · 演示适配器可独立运行           │
│         任务中心 · 素材库 · 设置 · 试映 · 导出下载          │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP (127.0.0.1)
┌────────────────────────┴────────────────────────────────┐
│                   业务服务层 (birthco-local/backend/)     │
│  Flask API · SQLite 持久化 · 试映模拟 · 平台账号接入       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐ │
│  │ 七角色    │ │ 模型适配 │ │ 后台 Worker│ │ 安全/会话   │ │
│  │ agents/  │ │ adapters/│ │ worker/   │ │ security/   │ │
│  └──────────┘ └──────────┘ └──────────┘ └─────────────┘ │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────┐
│               编排统筹层 (backend/workflow/five_agent/)   │
│  契约 · 状态机(LangGraph) · 条件路由 · 预算 · 人工闸门     │
│  版本/哈希 · 恢复与收据 · AdapterRouter                    │
└─────────────────────────────────────────────────────────┘
```

| 层 | 路径 | 职责 |
| --- | --- | --- |
| 编排统筹层 | `backend/workflow/five_agent/` | 契约、状态机、条件路由、预算、人工闸门、版本/哈希、恢复与收据 |
| 业务角色本体 | `birthco-local/backend/agents/` | 七角色实现（输入冻结、范围校验、输出契约），Mock/live 同一 schema |
| 业务服务 | `birthco-local/backend/` | Flask API、SQLite 持久化与台账、试映模拟、平台账号接入（抖音/小红书） |
| 模型接入 | `birthco-local/backend/adapters/model/` | 统一模型适配器（OpenAI 兼容 / MiMo / 通义）+ 按 agent 解析的工厂 |
| 后台执行 | `birthco-local/backend/worker/` | 任务队列执行、内容生成、预览、改稿 |
| 前端工作台 | `frontend/` | Vite + React 工作台（演示适配器可脱离后端独立体验） |
| 桌面版 | `desktop/` | 一键桌面启动器（无边框浏览器窗口 + 本地三进程管理） |
| 契约与证据 | `birthco-local/contracts/`、`evidence/` | 机器可读契约（OpenAPI/schemas）与分级验证证据 |

## 七角色说明

| 角色 | 标识 | 职责 |
| --- | --- | --- |
| 商单需求分析员 | `pr_analyst` | 解析商单需求，提取品牌/产品/约束 |
| 流量捕捉者 | `traffic_scout` | 捕捉热点选题，提供创作方向 |
| 运营官 | `operations_officer` | 制定运营策略，确认 Brief |
| 内容主创 | `content_creator` | 产出标题、封面文案、分段正文 |
| 审稿员 | `editorial_reviewer` | 规则/合规审校，发现问题并提出修改意见 |
| 数据分析师 | `data_analyst` | 试映数据分析，给出定向改稿建议 |
| 模拟观众 | `simulated_audience` | 模拟目标受众反馈，辅助试映评估 |

---

## 快速开始

### 方式一：桌面版一键启动（推荐）

适合最终用户。双击即用，无需命令行。

> **首次使用**：需先构建前端（仅一次）：
> ```bash
> cd frontend && npm install && npm run build
> ```
> 桌面版运行时读取 `frontend/dist` 静态产物，不需要 Node.js。

```
双击「启动.vbs」  →  自动启动三个本地进程 + 打开工作台窗口
双击「停止.vbs」  →  一键停止所有进程
```

- 自动探测端口，重复双击幂等（不会起重复进程）
- 浏览器以无边框应用窗口打开，不污染日常浏览器
- 数据存储在 `birthco-local/data/`，日志在 `.run/`
- 默认离线 Mock 模式，无需任何 API Key 即可体验全流程

### 方式二：命令行启动

适合开发者。需要 Python 3.10+ 和 Node.js。

```bash
# 一键启动（自动安装依赖 + 迁移数据库 + 启动 API + Worker + 前端）
python run.py

# 后台启动（立即返回命令行）
python run.py --detach

# 停止
.\stop.ps1          # Windows PowerShell
```

- 前端工作台：http://127.0.0.1:4173
- 后端 API：http://127.0.0.1:5001
- 缺依赖自动安装（Python 依赖 + npm install，失败自动换国内镜像）

---

## 配置 API Key（接入真实模型）

默认 Mock 模式不需要 API Key。要使用真实模型，按以下步骤操作：

### 1. 获取 API Key

支持任意 OpenAI 兼容接口，常见选项：

| 服务商 | 环境变量 | 获取地址 |
| --- | --- | --- |
| 通义千问（百炼） | `DASHSCOPE_API_KEY` | https://bailian.console.aliyun.com |
| MiMo | `MIMO_API_KEY` | MiMo 控制台 |
| OpenAI | `OPENAI_API_KEY` | https://platform.openai.com |
| 其他兼容接口 | `AGENT_API_KEY` + `AGENT_BASE_URL` | 自行部署/第三方网关 |

### 2. 设置环境变量

**方式 A：Windows 系统环境变量（推荐，一次设置永久生效）**

```powershell
# 打开「系统属性 → 高级 → 环境变量」，添加以下用户变量：
BIRTHCO_MODEL_MODE = live
DASHSCOPE_API_KEY  = sk-你的密钥
# 可选：指定模型（默认 qwen3.8-flash）
QWEN_MODEL_ID      = qwen3.8-flash
```

设置后**重新启动**工作台，环境变量自动生效。

**方式 B：命令行临时设置（当前终端有效）**

```powershell
$env:BIRTHCO_MODEL_MODE = 'live'
$env:DASHSCOPE_API_KEY  = 'sk-你的密钥'
python run.py
```

**方式 C：`.env` 文件（仅放非敏感配置）**

在仓库根目录创建 `.env`：

```env
BIRTHCO_MODEL_MODE=live
QWEN_MODEL_ID=qwen3.8-flash
```

> **安全提示**：API Key 建议放系统环境变量，不要写入 `.env` 或任何会入库的文件。代码不读取 `.env` 中的密钥字段，真实凭据只经运行时进程环境变量注入。

### 3. 按角色精细控制（可选）

可以只让部分角色走真实模型，其余保持 Mock：

| 角色 | 环境变量前缀 | 示例 |
| --- | --- | --- |
| 商单需求分析员 | `PR_ANALYST_` | `PR_ANALYST_MODEL_ID` |
| 运营官 | `OPERATOR_` | `OPERATOR_API_KEY` |
| 内容主创 | `DIRECTOR_` | `DIRECTOR_BASE_URL` |
| 审稿员 | `REVIEWER_` | `REVIEWER_PROVIDER` |
| 流量捕捉者 | `SCOUT_` | `SCOUT_MODEL_ID` |
| 数据分析师 | `ANALYST_` | `ANALYST_API_KEY` |
| 模拟观众 | `AUDIENCE_` | `AUDIENCE_PROVIDER` |

每个前缀支持 `_API_KEY` / `_BASE_URL` / `_MODEL_ID` / `_PROVIDER` 四个后缀覆盖。

**通用配置**：

| 环境变量 | 说明 | 默认值 |
| --- | --- | --- |
| `BIRTHCO_MODEL_MODE` | `mock` 或 `live` | `mock` |
| `AGENT_PROVIDER` | `auto` / `mock` / `openai` / `mimo` / `qwen` | `auto` |
| `AGENT_API_KEY` | 通用密钥（也可用 `OPENAI_API_KEY` / `MIMO_API_KEY` / `DASHSCOPE_API_KEY`） | — |
| `AGENT_BASE_URL` | 通用端点（也可用 `OPENAI_BASE_URL`） | — |
| `OPENAI_MODEL_ID` | 通用模型 | `gpt-4o-mini` |

### 4. 验证配置

启动后进入 **设置 → 七角色 Agent 接口**，可查看每个 Agent 实际解析到的服务商、模型和端点（不显示密钥）。配置缺失会明确报错，不会静默回退 Mock。

---

## 使用教程

### 第一步：启动工作台

双击「启动.vbs」或运行 `python run.py`，浏览器自动打开工作台。

### 第二步：初始设置

首次进入可用示例身份完成四步本地设置（选平台、填偏好等）。

### 第三步：创建任务

进入 **任务中心**，点击「新建任务」：

- 填写**简报**（分行填写）：
  ```
  品牌：城市脚步
  产品：周末步行指南
  ```
- 填写**正文需求**（想要什么内容）
- 选择**篇幅**：30 秒 / 60 秒 / 3 分钟 / 800 字（一等契约，生成时硬性校验）
- 勾选**商单**（走七角色完整链路）和**试映**（模拟观众反馈）
- 提供已授权的参考资料（可选）

### 第四步：确认任务书

等待七角色工作，生成任务书后确认。可查看各角色的中间产出。

### 第五步：审阅候选稿

查看候选稿（三条标题 + 封面文案 + 分段正文）。不满意可**退回修改**，系统生成下一版并附变化记录。

### 第六步：试映（可选）

勾选试映后可查看模拟观众反馈和数据分析结果，根据建议定向改稿。

### 第七步：验收导出

满意后点击**验收**，到「素材库」下载 Markdown 文件。交付物包含：

- `article.md` / `article.txt`
- 三条标题
- 封面文案
- 分段正文（改稿附变化记录）

---

## 命令行参数

```bash
python run.py                    # 完整启动（API + Worker + 前端）
python run.py --detach           # 后台启动后立即返回
python run.py --skip-frontend    # 只起后端 API
python run.py --skip-api         # 只起前端
python run.py --skip-worker      # 不启动后台任务执行进程
python run.py --data-dir X:\data # 自定义数据目录
```

**运行端口**：

| 服务 | 桌面版 | 命令行版 |
| --- | --- | --- |
| Flask API | 127.0.0.1:5210 | 127.0.0.1:5001 |
| 工作台前端 | 127.0.0.1:4273 | 127.0.0.1:4173 |

---

## 测试与验证

```powershell
# 编排层测试
python -m pytest tests/ -q

# 业务层测试
cd birthco-local; python -m pytest tests/ -q

# 端到端 Mock 演示（主链→试映→局部改稿→导出）
cd ..; python run_mock_demo.py --include-scout --output evidence/mock-flow-with-scout.json

# 审稿提示词指纹
python tools/check_review_prompt_hash.py

# 契约导出一致性
cd birthco-local; python tools/export_contracts.py --check
```

---

## 目录结构

| 路径 | 内容 |
| --- | --- |
| `backend/workflow/five_agent/` | 契约、Repository、Gateway、状态机、Adapter、Driver |
| `birthco-local/backend/` | 七角色本体、Flask API、存储/台账、试映模拟、Worker |
| `birthco-local/contracts/` | 机器可读契约（OpenAPI / JSON Schema） |
| `birthco-local/tests/` | 业务层测试 |
| `tests/` | 编排层测试 |
| `frontend/` | Vite + React 工作台 |
| `desktop/` | 桌面版启动器（launch.py / server.py / stop.py） |
| `docs/orchestration/` | 编排交付文档（流程图、契约、验证） |
| `docs/experts/` | 五专家开发链产物 |
| `evidence/` | 分级验证证据 |
| `run.py` | 跨平台一键启动器 |
| `start.ps1` / `stop.ps1` | Windows PowerShell 启停脚本 |
| `启动.vbs` / `停止.vbs` | 桌面双击快捷入口 |
| `run_mock_demo.py` | 端到端 Mock 演示脚本 |

---

## 安全提示

- 本仓库**不使用、不保存任何 Key**：真实调用凭据只经运行时进程环境变量注入，用完即弃，不落盘、不入库。
- 历史模型密钥曾暴露且仍留在 git 历史中：请在对应平台**作废旧 Key**。
- 禁止把真实凭据写入需求材料、聊天、源码、备份包或任何会入库的文件。

---

## 常见问题

**Q: 双击「启动.vbs」没反应？**
- 检查 `frontend/dist/index.html` 是否存在。桌面版读取预构建产物，不存在会静默退出。
- 解决：`cd frontend && npm install && npm run build`，然后重新双击。
- 查看 `.run/web.err.log` 可确认原因。

**Q: 端口被占用怎么办？**
- 桌面版：前端端口自动换到 4274~4292 的空闲端口；API 端口（5210）被占会明确报错，可设置 `BIRTHCO_PORT` 换端口。
- 命令行版：运行 `.\stop.ps1` 清理残留进程和端口占用。

**Q: 模型调用报错 / 不生效？**
- 检查 `BIRTHCO_MODEL_MODE=live` 是否设置。
- 到 **设置 → 七角色 Agent 接口** 查看各 Agent 实际解析的服务商/模型/端点。
- 配置缺失会明确报错，不会静默回退 Mock。

**Q: 生成字数不对（如选 800 字只给 100 字）？**
- 篇幅选择是一等契约，会写入生成约束并硬性校验。如果标题/想法里有与所选篇幅冲突的数字，弹窗会提醒并可一键修正。

**Q: 如何用境外模型？**
- 本机可走 Clash 等代理（`HTTP_PROXY` / `HTTPS_PROXY` 已被信任）。外部模型调用走代理，本地进程探测自动绕过代理。

**Q: 日志在哪？**
- 桌面版：`.run/desktop.log`、`api.err.log`、`worker.err.log`、`web.err.log`
- 命令行版：`.run/worker.err.log` 等
- 排查顺序：先看任务事件 → 再核对数据库 `runs`、`model_calls`、`checkpoints`。
