# 商单／PR 需求分析员

第七个独立角色。放在运营官之前，整理品牌／公关文案的客户资料：品牌、产品、目标、受众、平台、风格、明确要求、冲突和待问问题。输出可追溯分析报告；交接条件具备时另给运营官的待确认输入。只支持新文字／图文任务。

## 先跑完整例子

在 `birthco-local` 目录，依照完整使用说明安装依赖后执行。以下三个输出文件必须尚不存在，`results` 目录要先存在。

```powershell
$py = Join-Path (Get-Location) '.venv\Scripts\python.exe'
New-Item -ItemType Directory -Path results -Force | Out-Null
& $py tools/run_pr_analyst.py --input examples/pr-analysis-task.json --output results/pr-analysis.json --handoff-output results/pr-operator-input.json
```

先看 `results/pr-analysis.json`，人工核对原话是否真的代表客户需求、是否遗漏条件或冲突。确认提取结果适合作为运营官输入后运行：

```powershell
& $py tools/run_operator.py --input results/pr-operator-input.json --output results/pr-operator-proposal.json
```

这两步仍不会确认任务书。随后按完整使用说明确认 Brief、计算正式 `brief_hash`，交给导演、独立审稿。商单有固定选题时不需要 Scout。预算、排期和审核人即便已记录，也不会自动触发业务动作。

## 输入怎么填

复制 `examples/pr-analysis-task.json` 并另存为新文件：

- `analysis_requested=true`：调用方明确请求本次分析。`account_id` 由调用方提供。
- `client_brief`：客户简报，包含 `label/text/authorized=true`；可以为 null。链接和微信截图不会被自动读取，请由有权限的人提供准确文字。
- `intake`：你已经明确知道的品牌 `brand`、产品／服务 `product`、传播目标 `objective`、读者 `audience`、渠道 `platform`、风格 `style`。不知道填 null，不用空格占位。
- `budget/deadline/approver`：可选原话记录，可填 null；缺失时列入 `unprovided_business_fields`，不阻止交给运营官，但也不代表完整商业条件已经具备。
- `requirements`：客户已经明确的硬性要求，稳定 ID＋原文，最多 30 条。至少一条才能交接。原有要求不可被模型删除、换 ID 或改写。
- `materials`：其他授权资料，最多 18 份，每份最多 20,000 字符；不接受旧稿材料。亲历才标 `user_supplied_experience`，普通客户资料用 `source_text`。
- `length_rule`：确认的正文长度上下限；不限制填 null，最小值不能大于最大值。

brand/product 提取字段不会自动成为导演必须写入正文的硬性要求。如果客户要求文案必须出现品牌名或产品名，请把这一点明确写入 requirements，样例已这样处理。

每次输入最大 1 MiB；交接材料合计上限 80,000 字符。完整模型上下文上限 256 KiB，因为包含来源映射与原输入，可能先触及这一上限；超限会停止，不静默截取。自由文本中引用的链接不会被打开。

## 输出怎么看

`envelope.data.fields` 恰好覆盖九项字段。非空字段及要求都附 `source_id/quote`，程序检查引文确实在提供的来源中，且字段值／要求文字与引文逐字一致。`source_index` 记录每个来源的内容指纹，复核时保留本次原始输入。

六项必需字段缺失、没有要求、发现冲突或还有待问问题时：

- `envelope.status=needs_input`，具体问题在 `envelope.questions`。
- `task_draft=null`，不生成 `--handoff-output` 文件。
- 补充或解决问题后，保存新的输入，使用新的输出文件重新分析；不会自动替你决定。

交接格式具备时，`ready_for_operator=true`，`task_draft` 符合 `CreateTask`。`--handoff-output` 可选，给出时写成 `{"task": ...}`，直接适配运营官命令。它包含结构化字段资料、原简报及其他材料；运营官再生成自己的 `material_id`。PR 分析的 `source_id` 和运营官的材料编号是不同层的引用，保留各自映射，不要混用。

`ready_for_operator` 只表示可交给运营官，**不表示客户需求完整或正确**。固定标记 `user_confirmed=false`、`commercial_approval=false`、`external_facts_verified=false`、`completeness_verified=false`、`conflict_detection_exhaustive=false`。逐字引用只能证明资料出现过这句话；否定句中的片段也可能被误提取，语义仍需人核对。

## Mock 与真实模型

默认 Mock 不联网、不产生模型费用，只搬运明确填写的 intake 和 requirements。它不理解自由文本，也不保证发现其中的遗漏和矛盾；有完整客户简报但 intake 留空，仍会要求补齐。

缺资料样例：

```powershell
& $py tools/run_pr_analyst.py --input examples/pr-analysis-missing.json --output results/pr-gaps.json --handoff-output results/pr-gaps-operator.json
```

会保存问题报告，不创建 `pr-gaps-operator.json`。进程返回 0 只是成功生成报告，不是需求已通过。

真实模型可从自由文本提取带引文的字段、要求、冲突和问题。先按完整使用说明配置百炼环境变量，再在本角色命令加 `--live`，最多一次请求、输出最多 4000 Token、超时上限 90 秒，无自动重试。真实质量未验收。本次交付没有真实调用。

模型响应失败、截断、格式错误或引用无效时，保存 `envelope.status=error` 的分析报告，保留 call_id 和已知用量，不交接，返回码 3；结果未知或适配器异常会标 `INTERRUPTED`，先核对远端费用再决定新请求。输入／配置／输出路径错误返回 2；模型配置缺失不会创建分析结果或发送请求。现有文件一律不覆盖；分析与交接文件必须不同，也不能指向输入文件。

## 能力范围

会整理客户提供的条件，不核实商品事实、真实版权授权、合同效力或客户身份，不报价、收款、自动排期、获客户批准、发布、写正文或生成视频。`authorized=true` 是调用方声明。预算和价格可以记录原话，但不是专业商业或法律判断。

当前为独立组件和文件交接，未接正式数据库确认、持久化调度器或统一调用预算账本。人工修改提取报告不构成自动授权；有变化时保留来源并重新复核。后续局部改稿复用导演的旧稿流程，不由本角色绕过修改范围。
