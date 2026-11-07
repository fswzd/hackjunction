import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  type CSSProperties,
  type PointerEvent,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowRight, ArrowUpRight } from "lucide-react";
import { AGENT_META, AGENT_ORDER, PIPELINE } from "@/domain/agents";
import type { BackendStep } from "@/domain/types";
import { useWorkspace } from "@/store/workspace";
import { cn } from "@/lib/format";
import "./landing.css";

// three.js is heavy. Keep it out of the initial bundle; the CSS orb renders
// immediately while the shader chunk loads (and stays if WebGL is missing).
const IridescentOrb = lazy(() =>
  import("@/components/landing/IridescentOrb").then((module) => ({
    default: module.IridescentOrb,
  })),
);

interface FlowRow {
  key: string;
  index: string;
  label: string;
  description: string;
  agent?: string;
  action?: string;
  optional?: boolean;
  gate?: boolean;
  note?: string;
}

const stepOf = (id: BackendStep) => PIPELINE.find((step) => step.backendStep === id)!;

function flowRow(id: BackendStep, index: string, note?: string): FlowRow {
  const step = stepOf(id);
  const agent = AGENT_META[step.agentId];
  return {
    key: step.backendStep,
    index,
    label: step.label,
    description: step.description,
    agent: agent.name,
    action: agent.actions.join(" · "),
    optional: step.optional,
    note,
  };
}

const FLOW: FlowRow[] = [
  flowRow("pr_intake", "01"),
  flowRow("planning", "02"),
  {
    key: "gate-brief",
    index: "GATE 01",
    label: "确认任务书",
    description:
      "检查目标、受众、要求与预算。确认之前不会进入生成；退回会保存为新的任务书版本，原决定与原因都有记录。",
    gate: true,
    note: "WAITING_CONFIRMATION",
  },
  flowRow("scout", "03"),
  flowRow("draft", "04"),
  flowRow("review", "05", "审稿后最多执行一轮限定自动修复"),
  flowRow("preview", "06"),
  flowRow("analysis", "07", "诊断只解释已保存事件，不替换程序统计"),
  {
    key: "gate-accept",
    index: "GATE 02",
    label: "接收并导出",
    description:
      "按冻结的 READY 版本与内容哈希验收，写入接收记录。未经过哈希确认的内容不会被当作已交付。",
    gate: true,
    note: "READY → ACCEPTED",
  },
];

const STATUS = [
  {
    label: "编排",
    title: "LangGraph",
    text: "七角色路由、暂停与恢复、预算与调用收据。人工闸门由程序强制执行。",
    tag: "已实现 · 离线验证",
  },
  {
    label: "角色",
    title: "7 × 8",
    text: "七个业务角色共用统一输入输出；Mock 与 live 严格分离，不互相冒充。",
    tag: "部分真实调用证据",
  },
  {
    label: "本地服务",
    title: "Flask + SQLite",
    text: "账号、任务、版本、接收与事件；单 worker 队列、幂等键与行版本校验。",
    tag: "基础服务已具备",
  },
  {
    label: "工作台",
    title: "React",
    text: "新建任务、任务书确认、版本验收、反馈与可点击的 3D 工位。",
    tag: "原型已可用 · 全链路接入中",
  },
];

const MARQUEE =
  "需求整理 · 任务书 · 内容创作 · 独立审稿 · 观众试映 · 片段诊断 · 局部改稿 · 版本接收 · 导出交付 · ";

function MagneticLink({
  to,
  children,
  className,
}: {
  to: string;
  children: ReactNode;
  className?: string;
}) {
  const onMove = (event: PointerEvent<HTMLAnchorElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left - rect.width / 2;
    const y = event.clientY - rect.top - rect.height / 2;
    event.currentTarget.style.setProperty("--mx", `${x * 0.14}px`);
    event.currentTarget.style.setProperty("--my", `${y * 0.18}px`);
  };
  const onLeave = (event: PointerEvent<HTMLAnchorElement>) => {
    event.currentTarget.style.setProperty("--mx", "0px");
    event.currentTarget.style.setProperty("--my", "0px");
  };

  return (
    <Link
      to={to}
      className={cn("landing-magnetic", className)}
      onPointerMove={onMove}
      onPointerLeave={onLeave}
    >
      {children}
    </Link>
  );
}

function AgentCard({
  id,
  index,
}: {
  id: (typeof AGENT_ORDER)[number];
  index: number;
}) {
  const agent = AGENT_META[id];

  const onMove = (event: PointerEvent<HTMLElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;
    event.currentTarget.style.setProperty("--ry", `${(x - 0.5) * 7}deg`);
    event.currentTarget.style.setProperty("--rx", `${(0.5 - y) * 6}deg`);
    event.currentTarget.style.setProperty("--gx", `${x * 100}%`);
    event.currentTarget.style.setProperty("--gy", `${y * 100}%`);
  };

  const onLeave = (event: PointerEvent<HTMLElement>) => {
    event.currentTarget.style.setProperty("--ry", "0deg");
    event.currentTarget.style.setProperty("--rx", "0deg");
    event.currentTarget.style.setProperty("--gx", "50%");
    event.currentTarget.style.setProperty("--gy", "0%");
  };

  return (
    <article
      className="agent-card"
      data-reveal
      style={{ "--agent-accent": agent.accent } as CSSProperties}
      onPointerMove={onMove}
      onPointerLeave={onLeave}
    >
      <div className="agent-card-head">
        <span className="agent-index">{String(index + 1).padStart(2, "0")}</span>
        <span className="agent-role">{agent.role}</span>
      </div>
      <h3>{agent.name}</h3>
      <p>{agent.description}</p>
      <div className="agent-tags">
        {agent.actions.map((action) => (
          <code key={action}>{action}</code>
        ))}
      </div>
      <span className="agent-glow" aria-hidden="true" />
    </article>
  );
}

export function Landing() {
  const rootRef = useRef<HTMLDivElement>(null);
  const heroRef = useRef<HTMLElement>(null);
  const hasProfile = useWorkspace((state) =>
    Boolean(state.snapshot?.profile?.completedAt),
  );
  const enterPath = hasProfile ? "/workspace/overview" : "/onboarding";

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const items = Array.from(
      root.querySelectorAll<HTMLElement>("[data-reveal]"),
    );
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !("IntersectionObserver" in window)) {
      items.forEach((item) => item.classList.add("is-visible"));
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -6% 0px" },
    );
    items.forEach((item) => observer.observe(item));
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    let frame = 0;

    const update = () => {
      frame = 0;
      const height = Math.max(window.innerHeight, 1);
      const max = document.documentElement.scrollHeight - height;
      root.style.setProperty(
        "--page-progress",
        String(max > 0 ? Math.min(window.scrollY / max, 1) : 0),
      );
      root.style.setProperty(
        "--hero-lift",
        `${Math.min(window.scrollY * 0.14, 120)}px`,
      );
      root.style.setProperty(
        "--hero-fade",
        String(Math.max(1 - window.scrollY / (height * 0.82), 0)),
      );
    };

    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    update();
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  const onHeroPointer = (event: PointerEvent<HTMLElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    event.currentTarget.style.setProperty(
      "--pointer-x",
      `${event.clientX - rect.left}px`,
    );
    event.currentTarget.style.setProperty(
      "--pointer-y",
      `${event.clientY - rect.top}px`,
    );
  };

  return (
    <div className="landing" id="top" ref={rootRef}>
      <div className="landing-progress" aria-hidden="true" />
      <Suspense
        fallback={
          <div className="landing-orb" aria-hidden="true">
            <div className="landing-orb-fallback" />
          </div>
        }
      >
        <IridescentOrb />
      </Suspense>
      <div className="landing-grain" aria-hidden="true" />

      <header className="landing-nav">
        <Link to="/" className="landing-brand" aria-label="众幕 AI 首页">
          <span className="landing-mark" aria-hidden="true">
            幕
          </span>
          <span className="landing-brand-copy">
            <strong>众幕 AI</strong>
            <small>A STUDIO OF YOUR OWN</small>
          </span>
        </Link>
        <nav className="landing-links" aria-label="落地页导航">
          <a href="#team">团队</a>
          <a href="#workflow">流程</a>
          <a href="#status">现状</a>
        </nav>
        <MagneticLink to={enterPath} className="landing-nav-cta">
          {hasProfile ? "进入工作台" : "开始使用"}
          <ArrowUpRight size={14} />
        </MagneticLink>
      </header>

      <main>
        <section
          className="landing-hero"
          ref={heroRef}
          onPointerMove={onHeroPointer}
        >
          <div className="landing-hero-glow" aria-hidden="true" />
          <div className="landing-hero-inner">
            <p className="landing-eyebrow" data-reveal>
              众幕 AI — 面向一人内容工作室的多 Agent 协作平台
            </p>
            <h1 className="landing-title" data-reveal>
              一个人，
              <br />
              <span className="landing-title-serif">一支内容团队。</span>
            </h1>
            <p className="landing-title-en" data-reveal>
              <em>One person. A whole studio.</em>
            </p>
            <p className="landing-lead" data-reveal>
              把目标、素材与旧稿交给七个分工明确的 AI 角色。它们整理任务书、
              创作、独立审稿、模拟试映，并在关键节点停下来等你决定。
            </p>
            <div className="landing-actions" data-reveal>
              <MagneticLink to={enterPath} className="landing-btn landing-btn-primary">
                {hasProfile ? "进入工作台" : "开始创建工作室"}
                <ArrowUpRight size={16} />
              </MagneticLink>
              <a className="landing-btn landing-btn-ghost" href="#team">
                看看团队怎么工作
                <ArrowDown size={15} />
              </a>
            </div>
            <dl className="landing-meta" data-reveal>
              <div>
                <dt>业务角色</dt>
                <dd>7</dd>
              </div>
              <div>
                <dt>业务动作</dt>
                <dd>8</dd>
              </div>
              <div>
                <dt>人工闸门</dt>
                <dd>2</dd>
              </div>
              <div>
                <dt>任务状态</dt>
                <dd>15</dd>
              </div>
            </dl>
          </div>
          <div className="landing-scroll" aria-hidden="true">
            <span>SCROLL TO ENTER</span>
            <i>↓</i>
          </div>
          <div className="landing-hero-foot" aria-hidden="true">
            PROJECT v2.0 · LOCAL-FIRST · MIMO × LANGGRAPH
          </div>
        </section>

        <section className="landing-statement">
          <div className="landing-statement-inner">
            <p className="landing-kicker" data-reveal>
              THE PREMISE / 为什么是团队
            </p>
            <h2 className="landing-h2" data-reveal>
              不是让 AI 替你写完，
              <br />
              <span>而是让每一步都有人负责。</span>
            </h2>
            <p className="landing-body" data-reveal>
              创作、审稿与试映使用隔离的上下文。程序负责状态、预算、版本与幂等，
              模型负责理解、创作与诊断。你保留事实表达、商业承诺与最终发布的决定权。
            </p>
            <ul className="landing-principles">
              <li data-reveal>
                <span>01</span>
                <strong>分工，而不是一把万能钥匙</strong>
                <p>审稿员不改稿，创作者不自签，观众看不到未来片段。</p>
              </li>
              <li data-reveal>
                <span>02</span>
                <strong>留痕，而不是只给结果</strong>
                <p>任务书、版本、接收决定与修改依据都可以被重新检查。</p>
              </li>
              <li data-reveal>
                <span>03</span>
                <strong>人决定，而不是自动放行</strong>
                <p>两个人工闸门由程序强制等待，重复提交也有幂等记录。</p>
              </li>
            </ul>
          </div>
        </section>

        <section id="team" className="landing-section landing-team">
          <div className="landing-section-head">
            <p className="landing-kicker" data-reveal>
              THE TEAM / 七个角色
            </p>
            <h2 className="landing-h2" data-reveal>
              每个角色，
              <br />
              <span>只做自己该做的事。</span>
            </h2>
            <p className="landing-body" data-reveal>
              角色之间不互相冒充。七种职责、八类业务动作，共同围绕同一份任务书工作；
              流程调度由应用执行，关键决定由创作者作出。
            </p>
          </div>
          <div className="landing-agents">
            {AGENT_ORDER.map((id, index) => (
              <AgentCard key={id} id={id} index={index} />
            ))}
          </div>
        </section>

        <div className="landing-marquee" aria-hidden="true">
          <div className="landing-marquee-track">
            <span>{MARQUEE}</span>
            <span>{MARQUEE}</span>
          </div>
        </div>

        <section id="workflow" className="landing-section landing-flow">
          <div className="landing-section-head">
            <p className="landing-kicker" data-reveal>
              THE WORKFLOW / 从目标到交付
            </p>
            <h2 className="landing-h2" data-reveal>
              两个人工闸门，
              <br />
              <span>把决定权留在你手里。</span>
            </h2>
            <p className="landing-body" data-reveal>
              普通任务按需启用选题捕捉与观众试映；商单需求分析只在商单入口触发。
              每一步的产物、状态与用量都写入同一条任务记录。
            </p>
          </div>

          <div className="landing-flow-grid">
            <ol className="flow-list">
              {FLOW.map((row) => (
                <li
                  key={row.key}
                  className={cn("flow-row", row.gate && "flow-gate")}
                  data-reveal
                >
                  <span className="flow-index">{row.index}</span>
                  <div className="flow-copy">
                    <h3>
                      {row.label}
                      {row.optional ? <em>可选</em> : null}
                      {row.gate ? <strong>人工闸门</strong> : null}
                    </h3>
                    <p>{row.description}</p>
                    {row.note ? <small>{row.note}</small> : null}
                  </div>
                  {row.agent ? (
                    <div className="flow-agent">
                      <span>{row.agent}</span>
                      <code>{row.action}</code>
                    </div>
                  ) : null}
                </li>
              ))}
            </ol>

            <aside className="flow-aside">
              <div className="gate-card" data-reveal>
                <p className="landing-kicker">GATE 01</p>
                <h3>确认任务书</h3>
                <p>
                  目标、受众、硬要求与预算绑定到某个任务书版本与指纹。
                  你确认的是一份可检查的版本，而不是一段模糊描述。
                </p>
                <code>WAITING_CONFIRMATION</code>
              </div>
              <div className="gate-card" data-reveal>
                <p className="landing-kicker">GATE 02</p>
                <h3>接收内容</h3>
                <p>
                  只有 READY 版本可以被验收；接收记录包含版本、内容哈希与会话。
                  退回意见进入 feedback，不会伪装成已经改稿。
                </p>
                <code>READY → ACCEPTED</code>
              </div>
              <p className="flow-note" data-reveal>
                试映运行前冻结人设、片段与预算。超时、未知结果与未完成单独统计，
                不自动归为退出或已完成。
              </p>
            </aside>
          </div>
        </section>

        <section id="status" className="landing-section landing-status">
          <div className="landing-section-head">
            <p className="landing-kicker" data-reveal>
              BUILD STATUS / 现在进行到哪
            </p>
            <h2 className="landing-h2" data-reveal>
              工程原型已经跑通离线链路。
              <br />
              <span>真实任务验收仍在继续。</span>
            </h2>
            <p className="landing-body" data-reveal>
              当前阶段：七角色工程原型已建立，完成离线流程验证；MiMo 已有接入和
              部分角色真实调用证据，正在推进完整工作流集成与用户工作台。
            </p>
          </div>

          <div className="status-grid">
            {STATUS.map((item) => (
              <article key={item.label} className="status-card" data-reveal>
                <p className="landing-kicker">{item.label}</p>
                <h3>{item.title}</h3>
                <p>{item.text}</p>
                <span>{item.tag}</span>
              </article>
            ))}
          </div>

          <div className="status-notes">
            <blockquote data-reveal>
              “核心交付是可用内容与可靠流程；
              <br />
              核心验证是用户采用、交付效率和真实付费。”
            </blockquote>
            <p data-reveal>
              我们不把 Mock 写成已完成。界面明确区分演示模式与真实接口：
              真实模式失败时返回错误，不静默替代；未接入的下载与修订运行也会标注出来。
            </p>
          </div>
        </section>

        <section className="landing-cta">
          <p className="landing-kicker" data-reveal>
            START A TASK / 从一份真实需求开始
          </p>
          <h2 className="landing-h2" data-reveal>
            把下一份内容，
            <br />
            <span>交给一支能解释修改原因的团队。</span>
          </h2>
          <p className="landing-body" data-reveal>
            本地优先，数据留在你的设备。先完成一个可比较的任务，再决定这支团队值不值得留下。
          </p>
          <div className="landing-cta-actions" data-reveal>
            <MagneticLink to={enterPath} className="landing-btn landing-btn-primary">
              {hasProfile ? "进入工作台" : "创建你的工作室"}
              <ArrowRight size={16} />
            </MagneticLink>
            <a className="landing-btn landing-btn-ghost" href="#top">
              回到顶部
              <ArrowUpRight size={15} />
            </a>
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-footer-brand">
          <span className="landing-mark" aria-hidden="true">
            幕
          </span>
          <div>
            <strong>众幕 AI</strong>
            <p>面向一人内容工作室的多 Agent 协作平台</p>
          </div>
        </div>
        <p className="landing-footer-meta">
          项目书 v2.0 · 2026-11-07 · React / Flask / LangGraph / MiMo
        </p>
        <div className="landing-footer-links">
          <a href="#team">团队</a>
          <a href="#workflow">流程</a>
          <a href="#status">现状</a>
          <Link to={enterPath}>工作台</Link>
        </div>
      </footer>
    </div>
  );
}
