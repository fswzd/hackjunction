# 审稿员 Agent

输入已确认的任务书、冻结稿件及其内容哈希、任务书引用的原始材料。输出逐项要求检查、事实依据检查和定位到段落的修改意见；不会改稿或自动接受/发布。

```powershell
python tools/run_reviewer.py --input examples/reviewer-task.json --output reviewer-result.json
```

默认 Mock 零网络、零模型费用。程序先检查三条标题、封面、正文、段落编号和长度；结构不合格直接给出修改意见，不调用模型。结构合格的 Mock 结果明确返回“内容与事实尚待核实”，不会假装审稿通过。

`examples/reviewer-missing-cover.json` 是缺少封面的反例，可用相同命令输入，查看定位到 cover 的修改意见。

真实模式配置 MIMO_API_KEY 和 MIMO_MODEL_ID 后显式加 --live，最多一次模型请求，无自动重试。模型必须逐项检查全部要求，引用当前段落和真实材料编号；“全部通过”与缺依据、未满足或 blocking 问题相矛盾时拒绝结果。未知远程结果停止以避免盲目重复计费。

confirmed=true 是调用方提供的已确认快照声明，不是身份认证或数据库确认记录。后续持久化 Runner 必须从数据库核对正式确认状态；当前为可独立测试的角色组件，未接入完整多 Agent 编排。本轮不做真实模型内容质量验收。
