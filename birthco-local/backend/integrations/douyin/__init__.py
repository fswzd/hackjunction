"""douyin-session perf-data adapter（迁移自 cheat-on-content 的接入模式）。

登录：Playwright 打开抖音创作者中心扫码；会话 storage_state 只存受限本地
目录（BIRTHCO_SESSION_DIR，默认 birthco-local/data/sessions/），数据库只存
引用与指纹。抓取：创作者中心作品接口 → 归一化 PerfVideo（播放/点赞/评论/
转发/收藏/top 评论）。manual 通道为永久降级。
"""
