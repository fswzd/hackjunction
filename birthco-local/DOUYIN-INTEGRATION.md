# 抖音现有账号接入（douyin-session adapter）

> 迁移自 cheat-on-content 的 perf-data adapter 接入模式：**不新建账号**，
> 把用户已有的抖音账号接入系统做管理与历史数据导入。manual 通道为永久降级。

## 能做什么

1. **注册接入**：把已有抖音账号（抖音号/主页标识）登记到系统，绑定本地业务分区
2. **历史导入**：抓取已发作品的实绩数据（播放/点赞/评论/转发/收藏/top 评论），
   派生 `baseline_plays`（播放中位数），作为后续选题/预测/复盘的历史上下文
3. **会话管理**：扫码登录创作者中心；凭据只存受限本地目录
   （`BIRTHCO_SESSION_DIR`，默认 `birthco-local/data/sessions/`），数据库只存引用与指纹

## 快速用（CLI，birthco-local/ 下）

```powershell
# ① 注册已有账号（不创建新账号）
python tools/run_douyin_intake.py register --account-id a_xxx --handle 你的抖音号 --name 昵称

# ② 登录（需 playwright：pip install playwright && python -m playwright install chromium）
#    打开创作者中心后用抖音 App 扫码，登录成功自动保存会话
python tools/run_douyin_intake.py login --external-id ext_xxx

# ③ 抓取导入最近 N 条（真实平台调用）
python tools/run_douyin_intake.py import-adapter --external-id ext_xxx --count 10

# 或 manual 降级（任何情况下可用）：videos.json 见下
python tools/run_douyin_intake.py import-manual --external-id ext_xxx --file videos.json

# 查看状态
python tools/run_douyin_intake.py status
```

`videos.json`：

```json
{"source": "manual", "videos": [
  {"platform_video_id": "v1", "title": "教程一", "plays": 1000, "likes": 10,
   "comments": 2, "shares": 1, "top_comments": [{"text": "讲得清楚", "likes": 5}]}
]}
```

## API（前端/编排可调用）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/accounts/external` | 注册已有账号（platform=handle 唯一，重复注册返回同一登记） |
| GET | `/api/v1/accounts/external` | 列出接入账号与会话状态 |
| POST | `/api/v1/accounts/external/{id}/login` | 启动扫码登录（后台线程弹出浏览器窗口），成功后自动抓取实绩写入经验库 |
| GET | `/api/v1/accounts/external/{id}/status` | 登录/导入状态与可操作错误（前端轮询用） |
| GET | `/api/v1/accounts/external/{id}/experience` | 经验库聚合：实绩汇总、baseline、热评与最近作品 |
| POST | `/api/v1/accounts/external/{id}/import` | 导入历史：`{source:"manual", videos:[...]}` 或 `{source:"adapter", count:10}` |
| GET | `/api/v1/accounts/external/{id}/videos` | 已导入作品实绩（含 top 评论） |

## 前端登录入口

- 引导页（Onboarding）第 1 步选择「已在做账号 / 已是成熟账号」后出现「平台账号 · 经验库」面板
- 设置页 →「平台账号 · 经验库」：抖音 / 小红书 二选一 → 填账号标识 →「登录并导入实绩」
  （弹出浏览器窗口扫码，成功自动抓最近作品实绩入库）；也可「手动导入 JSON」补录
- 登录后可在面板查看经验库聚合（总播放/点赞/评论/转发/收藏、热评、最近作品），
  供后续选题、审稿与数据分析引用

## 行为约定（与 cheat-on-content 对齐）

- **导入失败不阻塞**：adapter 抓取失败 → 账号标记 `pending_adapter_setup`，manual 通道立即可用
- **不伪造数据**：抓不到的字段为 null；top 评论抓取失败不阻断作品数据
- **幂等导入**：同（账号, 平台作品 ID）不重复入库；`baseline_plays` = 全部已导入作品播放中位数
- **凭据安全**：storage_state 只落受限目录；API 不传输、数据库不存 cookie 内容
- **会话状态机**：`none → logging_in → logged_in`（抓取失败置 `pending_adapter_setup`，失效置 `expired` 重登即可）

## 诚实边界

- 抓取层走创作者中心网页接口，**平台接口形状可能变化**：归一化逻辑有夹具测试兜底，
  真实抓取失败时错误信息会明确指向 manual 通道；本仓库未做真实扫码/抓取验证（需账号持有者操作）
- 只读接入：不发布、不改账号设置、不做平台写操作
- 已知合规姿态：仅访问用户本人账号的创作者中心数据（与 cheat-on-content 相同前提）
