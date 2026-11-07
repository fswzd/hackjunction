# Creator OS · 一人公司 AI 工作台

前端原型，位于 `hackjunction/frontend`。默认使用本地演示适配器，不依赖后端即可完整体验 onboarding、任务闭环和 3D 总部。

## 启动

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:4173
```

其他命令：

```bash
npm run typecheck  # tsc --noEmit
npm run build      # tsc -b && vite build
npm run preview    # 预览生产构建
```

首次打开会进入 onboarding；点击「使用示例身份」可快速填入示例画像。引导第一步会要求选择账号阶段（正在起号 / 已在做账号 / 已是成熟账号），这个选择会进入画像并影响团队提示。画像、任务和审批记录保存在浏览器 `localStorage`；真实接口模式下账号阶段会同步到本地后端。

## 两种数据模式

| 模式 | 数据来源 | 说明 |
| --- | --- | --- |
| 演示模式（默认） | `src/adapters/mock.ts` + `localStorage` | 按后端 15 个任务状态与两条人工闸门建模：Brief 确认（`WAITING_CONFIRMATION`）与内容验收（`READY`）。自动推进会在闸门处停止 |
| 真实接口模式 | `src/adapters/api.ts` | 接入 session、accounts、任务列表/详情、事件、Brief、版本与 feedback。可创建任务（含 `preview_requested`）、确认 Brief、编辑 Brief、验收内容、取消任务，并把内容修订意见记录为 `feedback`（`edit_request`）。账号阶段通过 `POST/PUT /api/v1/accounts` 写入 `accounts.creator_stage`；资产下载与修订运行仍未接入 |

切换入口：设置 → 数据与连接。默认使用 Vite 同源代理 `/api` → `http://127.0.0.1:5001`（macOS 的 AirPlay 接收器占用 5000）。代理会移除 `Origin` / `Referer` / `Sec-Fetch-Site`，以满足后端 session 校验。后端不可用时会出现错误页，可直接切回演示模式。

后端端口可通过同一个环境变量调整：

```bash
cd birthco-local && BIRTHCO_PORT=5001 python -m backend.app
cd frontend && BIRTHCO_PORT=5001 npm run dev
```

或分别设置 `BIRTHCO_PORT`（后端）与 `VITE_API_PROXY_TARGET`（前端代理目标）。后端仍只允许回环地址，并校验 `BIRTHCO_ALLOWED_ORIGINS`（逗号分隔的额外来源）。

## 主要路由

- `/onboarding` 四步工作空间画像
- `/workspace/overview` 总览 + 3D 总部
- `/workspace/workforce` AI 员工
- `/workspace/projects` 内容项目
- `/workspace/tasks` 任务中心
- `/workspace/tasks/:taskId` 任务详情（审批 / 退回 / 事件记录）
- `/workspace/calendar` 内容日历
- `/workspace/assets` 素材库
- `/workspace/analytics` 运营分析
- `/workspace/settings` 设置

## 3D 与降级

- R3F 正交等距场景：六名专业员工工位 + 运营官总部，共 7 个可点击工位，对应后端七个角色。
- 标签使用 CanvasTexture 精灵，不使用 Drei `<Html>`（React 19 下 DOM portal 会导致 Canvas 渲染循环失效）。
- 相机按容器宽高自动适配；移动端保持完整场景，宽屏会略微收紧构图。
- WebGL 不可用或场景异常时自动切换 2D 员工视图。
- 场景代码按需加载，three.js 不进入首屏主包。

## 后端边界

为关闭人工闸门，`birthco-local/backend/api/task_actions.py` 实现了契约中已记录但此前缺失的端点：`GET /brief`、`PUT /brief`、`GET /versions`、`GET /versions/{id}`、`POST /confirm`、`POST /accept`、`POST /cancel`、`POST /feedback`、`GET /feedback`。账号阶段使用 `GET /api/v1/accounts`、`POST /api/v1/accounts` 与 `PUT /api/v1/accounts/{id}`，写入 `accounts.creator_stage`。所有写操作沿用 session + CSRF + Idempotency-Key 与 row-version CAS，不修改既有代理/worker 代码。

前端严格对齐后端契约 `seven-agent.v0.1` 的 7 个角色：

| 角色 ID | 员工 | 动作 |
| --- | --- | --- |
| `pr_analyst` | 商单需求分析员 | `analyze_request` |
| `operations_officer` | 运营官 | `prepare_brief` |
| `traffic_scout` | 流量捕捉者 | `capture_opportunities` |
| `content_creator` | 内容主创 | `draft` / `revise` |
| `editorial_reviewer` | 独立审稿员 | `assess_content` |
| `simulated_audience` | 模拟观众 | `read_segment` |
| `data_analyst` | 数据分析师 | `diagnose_preview` |

任务路由由后端决定：商单（PR）与选题捕捉、模拟观众试映均为可选阶段。人工闸门只有两个——`WAITING_CONFIRMATION` 确认 Brief，`READY` 验收内容。真实模式下界面状态只来自后端任务与事件，不由动画伪造完成。

## 已知限制

- 真实接口已接通读取、创建、Brief 确认/编辑、内容验收、取消与 feedback 记录；内容修订运行（消费 feedback 生成新版本）仍需后端 worker，当前未接入。
- 真实接口模式每 10 秒轮询一次任务快照（仅页面可见时），并在窗口重新聚焦时刷新；没有 SSE / 增量事件推送。轮询失败会保留上一次可用快照，不弹出错误页。
- 后端持久化自动化编排（从 DRAFT 推进到两个人工闸门）仍未实现，可用测试数据或后续 worker 让任务到达 `WAITING_CONFIRMATION` / `READY`。
- 日历按任务的 `updatedAt` 分组，尚未接入真实排期字段。
- 3D 为程序化风格化场景，无外部模型资产与后处理；移动端 3D 标签较小，可用底部员工标签操作。
- 仓库内暂无自动化测试；本次验证使用 typecheck、build 和无头 Chrome 手动巡检。
