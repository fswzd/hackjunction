# 小红书现有账号接入（xiaohongshu-session adapter）

> 与 [DOUYIN-INTEGRATION.md](DOUYIN-INTEGRATION.md) 同法迁移（cheat-on-content
> perf-data adapter 模式）：**不新建账号**，接入已有账号做管理与历史数据导入。
> 共有语义（幂等导入 / baseline 中位数 / 凭据安全 / manual 永久降级 / 不伪造数据）见抖音文档。

## 平台差异（唯一需要关心的部分）

| 项 | 小红书 |
|---|---|
| 登录入口 | 创作服务平台 `creator.xiaohongshu.com`，扫码登录 |
| 内容形态 | 笔记（图文 + 视频） |
| 指标映射 | 阅读/观看→plays、点赞→likes、评论→comments、分享→shares、**收藏→favorites**（核心指标）、top 评论同抓 |
| 抓取入口 | 创作服务平台笔记管理接口 + 评论接口（字段变体由 normalize_note/normalize_comments 吸收） |

## 快速用（birthco-local/ 下）

```powershell
python tools/run_account_intake.py register --platform xiaohongshu --account-id a_xxx --handle 你的小红书号 --name 昵称
python tools/run_account_intake.py login --external-id ext_xxx        # 扫码（需 playwright）
python tools/run_account_intake.py import-adapter --external-id ext_xxx --count 10
# 或 manual：python tools/run_account_intake.py import-manual --external-id ext_xxx --file notes.json
python tools/run_account_intake.py status
```

`notes.json` 格式与抖音 `videos.json` 相同（`platform_video_id` 填笔记 ID）。

API 同一套：`POST /api/v1/accounts/external`（`platform: "xiaohongshu"`）、`POST .../login`（扫码登录后自动抓实绩入经验库）、
`GET .../status` / `GET .../experience`（登录状态与经验库聚合）、`.../import`、`GET .../videos`。
前端入口同抖音：引导页选「已在做账号 / 已是成熟账号」后出现接入面板，或设置页 →「平台账号 · 经验库」。

## 诚实边界

与抖音一致：真实扫码/抓取未验证（需账号持有者操作）；平台接口漂移时 fetch 层报错指向 manual 通道；只读接入，不做平台写操作。
