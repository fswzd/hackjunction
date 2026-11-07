# 模拟观众 Audience

输入一份冻结图文和一至六个模拟观众画像；程序先展示第一条标题与封面文案，再按原顺序逐段展示正文。每次模型请求严格只含 persona、current_segment、visible_history、own_previous_reactions 四个字段。

```powershell
python tools/run_audience.py --input examples/audience-task.json --output audience-result.json
python tools/run_audience.py --input examples/audience-task.json --mock-exit-after 1 --output audience-exit-result.json
```

默认 Mock 是机械继续/退出的流程样例，不代表真实观众体验。--mock-exit-after 1 表示读完封面和首段后退出（封面编号0）；只允许 Mock，且会在结果中披露。退出后不发送后文，不同观众的历史和反应不共享。

程序输出每个观众的连续事件、退出/完成/未完成结果、已读 cursor、调用记录和已知/未知用量。COMPLETED 表示调度已结束（包括正常退出），不表示所有人读完或喜欢内容。失败不伪装退出，远程结果未知时全局停止为 INTERRUPTED，未访问会话仍保留为 incomplete。

输入 confirmed=true 是可信调用方提供的冻结快照声明。正式数据库版本、授权与会话归属仍需后续 Runner 核验。version_id 使用 v_ 加32位小写hex，content_hash 与正文实际内容一致；封面ID由程序生成。最多8个片段（包含封面），超限直接拒绝，不偷偷截断。

max_calls 必须显式设置，最多48；max_active_seconds 最多1200，每次模型输出最多800 Token、传输超时参数最多90秒。活动时长在调用前检查，剩余时长传入适配器；这里没有能强杀网络请求的进程级看门狗。真实模式配置 MiMo 环境变量后加 --live，可产生最多 min(片段数×观众数, max_calls) 次模型费用。无自动重试，不支持未知计费下的自动恢复。失败或预算不足仍保存输出，CLI 退出码3；正常结束退出码0。

这里只控制调用次数和活动时长，尚未接入持久化 Token 预留账本、进程恢复、HTTP试映 API 和完整 A07b。已知 Token 只统计提供的usage，未知用量不当成0。模拟人数不是人类样本，读图文的进度不能当成视频秒数、真实完播率或播放量预测。真实模型模拟质量尚未验收。

usage_not_reported_calls 表示响应没有提供 Token 用量；Mock 也属于这种情况，但没有真实模型费用。remote_outcome_unknown_calls 才表示结果不明的调用，两者不混为一谈。
