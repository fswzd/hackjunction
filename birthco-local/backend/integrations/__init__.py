"""现有账号接入（perf-data adapters）：注册既有平台账号并导入其历史数据。

参考迁移自 cheat-on-content 的 perf-data adapter 模式：
- 抖音 douyin-session（Playwright 扫码登录创作者中心）为首个平台
- 人工粘贴（manual）为永久降级通道
- 导入失败不阻塞；会话凭据只存受限本地目录，数据库只存引用与指纹

本包的表为增量幂等 DDL（storage.ensure_integration_tables），不改动
schema_migrations 核心版本；待存储 owner 收编进 002 迁移。
"""
