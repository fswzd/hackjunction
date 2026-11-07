# 运营官 Agent

输入账号目标、受众、风格、要求与授权素材，输出待用户确认的 Brief。已有稿件缺稿或未选择修改范围时，先提出补充问题；不会自动写正文或接受任务书。

从 birthco-local 运行：

```powershell
python tools/run_operator.py --input examples/operator-task.json --output operator-result.json
```

默认 Mock：零网络、零模型费用，按输入确定性整理任务书；结果明确标记 mode=mock，不能作为真实模型内容质量证明。

真实模式需在本机配置 DASHSCOPE_API_KEY 和 QWEN_MODEL_ID，并显式加 --live，最多一次调用、无自动重试。素材始终作为 JSON 数据传入，结果经过严格 schema、引用和用户要求校验；结果未知会停止，避免重复计费。

输出 proposal_hash 仅标识本次建议内容，不是后续冻结规则与确认 CAS 使用的正式 brief_hash。缺材料时 requires_user_confirmation=false，应先补充输入。

这是可独立运行的角色组件。持久化 Runner、预算账本和用户确认工作流尚未接入，不能作为完整 P0 交付。
