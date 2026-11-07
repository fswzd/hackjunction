# 数据分析师 Analyst

读取第五个 Audience 的原始输入 source 和完整输出 simulation，先校验冻结版本、输入哈希、每个persona、连续事件、调用与事件对应、用量汇总和停止状态，再用程序计算统计。模型只解释观察，不能替换统计或自动改稿。

```powershell
python tools/run_analyst.py --input examples/analyst-task.json --output analyst-result.json
```

每个 finding 引用当前版本真实 event_id，segment_id 必须与这些事件一致，同时给出可能解释、另一种解释和具体编辑试验。建议等待用户选择，不会直接交给导演执行。

默认 Mock 零网络、零模型费用；Mock 诊断是模板，不能证明内容缺陷。Viewer 的 Mock 退出可能来自机械 fixture，不应当作真实流失或内容因果证据。模型 persona 也不是独立人类样本。

## 程序统计

- N：冻结的模拟会话数；S：有首段事件的会话数。
- C：正常完成数；U：未完成数；Z：零事件数；exited：明确退出数。
- coverage=S/N；completion=C/S。分母为0时 value=null，同时保留分子和分母。
- 每段退出率=X/E，E只数真正见过该段的有效事件；失败不算exit。
- like/comment/save每会话每类只计一次，分母S；原始评论另行保留，不把多条评论当多人。

手算回归包含 N=4、S=3、C=1、U=2、Z=1、exited=1；三个片段的E/X为3/0、2/1、1/0。失败和零事件会话都在报告里。

Z可能是U的一部分，不能再加成额外人数。examples/analyst-incomplete-task.json 是带失败的合成Mock手算样例；analyst-task.json 直接衔接第五个的Mock输出；analyst-no-events.json 验证零事件；analyst-comparison-task.json 演示明确授权的描述比较。

## 比较边界

可选 comparison_source + comparison_simulation，但必须显式 allow_descriptive_comparison=true，且每版独立会话/事件/调用、版本不同。程序展示双方完整统计和已知差异。

当前 Audience 报告没有完整记录可核验的模型/提示词条件和片段谱系，因此 conditions_match 固定false，含义是“未证实可作同条件实验”，不是已经证明所有条件不同。即使正文ID或顺序相同，也不自动认定可靠对齐。模型必须复制程序的条件结论与reason，不能改成true或宣称因果改善。findings只允许引用左侧当前版本的事件，右侧只能作描述比较。

## 失败与范围

真实模式需配置百炼环境变量并显式加 --live，最多一个分析调用，输出最多800 Token，无自动重试。分析失败/格式无效/结果未知时，程序统计仍保留；输出文件保存，CLI退出码3。没有有效事件时先提问且零分析调用。完整模型上下文超过256 KiB时请用户选择较小场景，不自动截断失败事件。

模型配置缺失也会保留有效统计，返回failed和call_id=null，表示没有发出分析请求；不会偷偷改用Mock冒充真实分析。

输入 analysis_requested=true 是可信调用方的分析授权声明，报告一致性校验不等于数据库来源认证。当前只分析内部模拟，不接受真实平台反馈或混合人类样本，也不生成视频秒数/完播率/播放量/收入预测。真实模型解释质量未验收；持久化Runner、数据库归属、实验排队/随机顺序和自动选段改稿仍待后续集成。
