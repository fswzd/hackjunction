众幕 AI · 内容工作台（桌面版）
================================

启动：双击桌面上的「众幕 AI 工作台」快捷方式。
停止：双击「众幕 AI 工作台 - 停止」快捷方式，或关闭窗口后运行停止。

桌面版包含三个本地进程，全部只监听 127.0.0.1：
  - Flask API        127.0.0.1:5210
  - 后台任务 worker  （无端口）
  - 工作台静态服务   127.0.0.1:4273  （同时代理 /api 到 Flask）
浏览器以 Edge / Chrome 的 --app 无边框窗口打开 http://127.0.0.1:4273/。

启动器可靠性
  - 重复双击是幂等的：先探测 5210 的 /api/v1/health 和 4273 的
    /__desktop/ping，确认是本应用就直接复用，不会起重复进程。
  - /__desktop/ping 是归属探测：若 4273 上是别的程序（旧 Vite、代理、
    其它服务），启动器不会误复用，而是自动在 4274~4292 里挑空闲端口，
    并用真实地址打开窗口。
  - 所有本地探测都绕过 HTTP_PROXY / HTTPS_PROXY；浏览器窗口带
    --no-proxy-server。某些系统代理会把 127.0.0.1 也拦下来并返回
    「502 upstream connect failed」，看起来像后端崩了，实际是代理问题。
    外部模型调用仍然可以走代理（HTTP_PROXY / HTTPS_PROXY 保持有效）。
  - API / worker / 静态服务均以独立脱离进程启动，启动器退出后继续运行；
    停止脚本按 PID 精确结束，且会校验命令行确实属于本应用，不会误杀。
    即使 PID 文件因崩溃或手动结束进程而失效，停止脚本仍会通过 4273/5210
    的端口占用者与命令行扫描找到并结束残留实例，不会留下半死进程。

数据与日志
  - 数据库/产物：app\birthco-local\data\
  - 运行日志：    app\.run\desktop.log、api.err.log、worker.err.log、web.err.log
  - 浏览器配置：  app\.run\browser-profile\  （独立配置，不污染日常浏览器）

默认模式：离线 Mock（零联网、零费用、零密钥），七个 Agent 接口全部走本地
确定性实现，可直接创建任务、确认 Brief、试映、验收、下载 Markdown。

交付物与篇幅口径
  - 交付的是文字脚本 / 文章（Markdown），不生成视频文件；「脚本用途」只描述
    这份文字稿打算用在什么场景。
  - 新建任务里选的「30 秒 / 60 秒 / 3 分钟 / 800 字」是一等契约：会同时写入
    结构化 length_rule、生成约束和校验规则，正文按对应字数生成并硬性校验，
    不会再出现「要 800 字却只给 100 多字」。
  - 标题或创作想法里写了与所选目标冲突的数字（例如选 30 秒却写「60 秒看懂」），
    弹窗会提醒并可一键修正，提交时还会自动纠正一次；后端另有
    RULE_TARGET_DURATION 校验标题/封面，RULE_TIMELINE 校验正文时间轴末段
    是否正好落在所选秒数、文章类目标是否误混入秒数时间轴。
  - 演示模式与真实接口模式的口径一致：短脚本按所选秒数生成时间轴，
    字数类文章不带秒数时间轴。

接入真实模型（可选，按需设置进程环境变量后重新启动）
  AGENT_PROVIDER   auto | mock | openai | mimo | qwen      默认 auto
  AGENT_API_KEY    通用密钥（也可用 OPENAI_API_KEY / MIMO_API_KEY / DASHSCOPE_API_KEY）
  AGENT_BASE_URL   通用端点（也可用 OPENAI_BASE_URL）
  OPENAI_MODEL_ID  通用模型（默认 gpt-4o-mini）
  BIRTHCO_MODEL_MODE=live   打开真实模型调用；mock 为离线模式
  单角色覆盖：<PREFIX>_API_KEY / _BASE_URL / _MODEL_ID / _PROVIDER
              PREFIX 取 PR_ANALYST / OPERATOR / DIRECTOR / REVIEWER /
              SCOUT / ANALYST / AUDIENCE
  例：设置 AGENT_API_KEY 与 AGENT_BASE_URL 指向本机 OpenAI 兼容网关即可。
  注意：本机访问境外模型可走 Clash 代理（HTTP_PROXY / HTTPS_PROXY 已被信任）。
  凭据只经进程环境变量注入，绝不写入任何文件；「设置 → 七角色 Agent 接口」
  可随时查看每个 Agent 实际解析到的服务商、模型和端点（不显示密钥）。

重新构建前端（仅改动前端源码时需要）
  cd app\frontend && npm install && npm run build
  桌面版运行时不需要 Node.js，直接读取 app\frontend\dist。

常见问题
  - 端口被占用：4273 会自动换到 4274~4292 的空闲端口；5210 若被非本应用
    占用会明确报错，可设置 BIRTHCO_PORT 换端口。也可手动指定
    BIRTHCO_PORT / BIRTHCO_FRONTEND_PORT 后重新启动。
  - 后端未就绪：查看 app\.run\api.err.log；新版会把完整异常堆栈写入该日志。
  - 日志里出现 "WARNING: This is a development server" 属正常提示：
    桌面版只监听 127.0.0.1、单用户本机使用，不对外暴露服务。
  - 会话失效：前端已自动重新建立会话并重放请求，无需手动刷新。
  - 想用真实模型：先在 Windows 的系统环境变量里设置好密钥与端点，
    再双击启动（进程环境变量会被启动器继承）；切到 live 模式需要
    BIRTHCO_MODEL_MODE=live，缺少配置会明确报错，不会静默回退 Mock。
