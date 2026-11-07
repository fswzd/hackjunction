# 流量捕捉者 Scout

从提供的经验、读者问题与来源正文中找选题。每个机会包括具体切口、受众问题、账号适配理由、材料编号和待验证假设，最多三条。

```powershell
python tools/run_scout.py --input examples/scout-task.json --output scout-result.json
```

默认 Mock 零网络、零模型费用，按材料标签生成明确标记的机会卡模板。重复材料不会被用来硬凑三个机会。缺少材料或缺少 Brief 引用的来源时先提问，不调用模型。

research_requested=true、authorized=true 是可信调用方的明确请求和素材授权声明，不是数据库身份认证。材料正文最大每份20,000字符、共20份和80,000字符；机会的来源编号必须真实存在，标题切口/编号不得重复，账号定位和假设不得为空。

组件只接收本次快照，不会自行读取其他账号。account_id 与素材的实际归属仍需未来 Runner 从数据库核对。

本组件只做材料内分析，没有浏览器或任意 URL 抓取。source_url 是用户提供的未核实元数据，不会被访问。所有 evidence_date 必须 null，结果固定标记 live_search_performed=false、currentness_verified=false；程序验证引用与数据边界，选题与材料是否真正相符仍需用户/真实模型质量验收。

真实模式配置 DASHSCOPE_API_KEY、QWEN_MODEL_ID 后显式加 --live：只将本次材料发给百炼分析，单次一个请求、输出上限2000 Token、没有自动重试。这里 live 只表示真实模型调用，不表示联网搜热点。真实模型效果和计费尚未测试。

输出只是建议，等待用户选择；不会修改账号、记忆或 Brief，也不会写正文、发布或预测流量。用户选定后需由运营官整理新的待确认 Brief。当前没有持久化自动交接、A06 三轮检索或记忆系统。
