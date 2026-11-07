# 内容导演 Agent

输入已确认的任务书、冻结规则及正式 Brief 哈希、表达风格、授权素材和预留段落编号。输出三条标题、一份封面文案、正文候选；旧稿修改时输出完整新稿与逐项 change_log。

```powershell
python tools/run_director.py --input examples/director-task.json --output director-result.json
python tools/run_director.py --input examples/director-revision-task.json --output director-revision.json
```

默认 Mock 是零网络、零模型费用的机械模板，明确包含 Mock 标记。它演示输入输出和改稿边界，不代表真正的写作质量。内容生成后运行程序规则：缺标题、缺封面、重复编号或长度不符会保留候选与失败原因，next_action=repair_content，不能自动进入通过状态。

真实模式需要配置 DASHSCOPE_API_KEY、QWEN_MODEL_ID，显式加 --live，单次最多一个请求且不自动重试。真实调用和内容效果尚未验收。

新稿只能使用预留段落ID；事实来源只能引用本次素材ID。旧稿的替换、新增、删除、移动及标题/封面改动必须有对应的授权 issue_id 与修改记录，保留段落的类型、文本、来源与编号逐字不变。程序验证的是引用和修改边界，事实是否真正得到支持、文案质量仍由独立审稿与用户核对。

旧稿素材填写当前基线版本的正文（不含标题封面），按空白行分段后必须与 base_content 的段落原文逐字一致。同一位置的多条修改意见先合并为一条 edit_request；每条选定请求都必须有实际修改记录，做不到应返回 needs_input。

输入 confirmed=true 只代表可信调用方提供了确认快照，正式数据库确认与归属仍要由后续 Runner 核对。brief_hash 使用 backend/domain/hashing.py 的 brief_hash(brief, frozen_rules) 计算；修改任务书或规则后要重新确认并计算。示例中的哈希已经配好。不得用运营官的 proposal_hash 代替正式 brief_hash。

version_id 是本地候选编号，当前不写数据库；输出 automatic_acceptance=false、editorial_review_completed=false。结构合格只会建议 editorial_review，不会自签审稿通过或发布。

三个角色现在均可单独运行。测试已验证新稿输出可以传给审稿员输入契约，持久化自动交接和完整 P0 Runner 尚未实现。
