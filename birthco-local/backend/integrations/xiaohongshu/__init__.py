"""xiaohongshu-session perf-data adapter（与 douyin-session 同法迁移）。

登录：Playwright 打开小红书创作服务平台（creator.xiaohongshu.com）扫码；
会话 storage_state 只存受限本地目录，数据库只存引用与指纹。抓取：创作服务
后台笔记接口 → 归一化 PerfVideo（阅读/点赞/评论/分享/收藏/top 评论）。
manual 通道为永久降级。平台字段命名差异由 normalize_* 吸收并夹具测试锁定。
"""
