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
import { BrandMark } from "@/components/brand/BrandMark";
import { FlowLines } from "@/components/landing/FlowLines";
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
    index: "闸门一",
    label: "确认任务书",
    description:
      "检查目标、受众、要求与预算。确认之前不会进入生成；退回会保存为新的任务书版本，原决定与原因都有记录。",
    gate: true,
  },
  flowRow("scout", "03"),
  flowRow("draft", "04"),
  flowRow("review", "05", "审稿后最多执行一轮限定自动修复"),
  flowRow("preview", "06"),
  flowRow("analysis", "07", "诊断只解释已保存事件，不替换程序统计"),
  {
    key: "gate-accept",
    index: "闸门二",
    label: "接收并导出",
    description:
      "验收时锁定当前版本并记录你确认的内容；未经确认的版本不会被当作已交付。退回意见会保留在下一次修改里。",
    gate: true,
  },
];

interface PricingPlan {
  id: string;
  name: string;
  kicker: string;
  price: string;
  period: string;
  description: string;
  features: string[];
  cta: string;
  featured?: boolean;
}

const PRICING: PricingPlan[] = [
  {
    id: "starter",
    name: "起号版",
    kicker: "从零开始",
    price: "¥0",
    period: "/ 月",
    description: "先把第一轮内容跑顺，找到自己的表达节奏。",
    features: [
      "1 个工作空间",
      "每月 3 个创作任务",
      "七位 AI 角色协作",
      "Brief 确认与内容验收",
    ],
    cta: "免费开始",
  },
  {
    id: "creator",
    name: "创作者版",
    kicker: "稳定更新",
    price: "¥99",
    period: "/ 月",
    description: "给持续更新的创作者，一套能稳定交付的内容团队。",
    features: [
      "每月 30 个创作任务",
      "模拟观众试映",
      "版本对比与修改记录",
      "内容资产库",
    ],
    cta: "选择创作者版",
    featured: true,
  },
  {
    id: "studio",
    name: "工作室版",
    kicker: "成熟账号",
    price: "¥299",
    period: "/ 月",
    description: "给成熟账号与小团队，更多并行任务与优先支持。",
    features: [
      "每月 100 个创作任务",
      "多账号工作区",
      "优先任务队列",
      "专属支持",
    ],
    cta: "选择工作室版",
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
        <span className="agent-role">{agent.capabilities[0]}</span>
      </div>
      <h3>{agent.name}</h3>
      <p>{agent.description}</p>
      <div className="agent-tags">
        {agent.capabilities.slice(0, 2).map((capability) => (
          <span key={capability}>{capability}</span>
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
      root.style.setProperty(
        "--flow-fade",
        String(Math.max(0, 1 - window.scrollY / (height * 1.9))),
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
      <FlowLines />
      <div className="landing-grain" aria-hidden="true" />

      <header className="landing-nav">
        <Link to="/" className="landing-brand" aria-label="众幕 AI 首页">
          <BrandMark size={30} />
          <span className="landing-brand-copy">
            <strong>众幕 AI</strong>
            <small>自媒体创作者工作室</small>
          </span>
        </Link>
        <nav className="landing-links" aria-label="落地页导航">
          <a href="#team">团队</a>
          <a href="#workflow">流程</a>
          <a href="#pricing">定价</a>
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
              众幕 AI · 自媒体创作者工作室
            </p>
            <h1 className="landing-title">
              <span className="landing-title-line">
                <span className="landing-title-copy">
                  <span className="glyph glyph-one">一</span>
                  <span className="glyph">个</span>
                  <span className="glyph glyph-kai">人</span>
                  <span className="glyph glyph-punct">，</span>
                </span>
              </span>
              <span className="landing-title-line">
                <span className="landing-title-copy">
                  <span className="glyph glyph-one glyph-one-second">一</span>
                  <span className="glyph glyph-serif">支</span>
                  <span className="glyph">内容</span>
                  <span className="glyph glyph-outline">
                    团队
                    <span className="glyph-outline-echo" aria-hidden="true">
                      团队
                    </span>
                  </span>
                  <span className="glyph glyph-ring">。</span>
                </span>
              </span>
            </h1>
            <p className="landing-title-en" data-reveal>
              <em>One person. A whole studio.</em>
            </p>
            <p className="landing-lead" data-reveal>
              <span>一个想法，几份散落的材料。</span>
              <span>
                七位角色分头接手：写成任务书，落笔成稿，挑出毛病，再替陌生的读者读一遍。
              </span>
              <span>你不必写完所有东西，只需要在每一个路口做决定。</span>
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
                <dt>内容环节</dt>
                <dd>8</dd>
              </div>
              <div>
                <dt>人工闸门</dt>
                <dd>2</dd>
              </div>
              <div>
                <dt>版本留痕</dt>
                <dd>100%</dd>
              </div>
            </dl>
          </div>
          <div className="landing-scroll" aria-hidden="true">
            <span>向下浏览</span>
            <i>↓</i>
          </div>
          <div className="landing-hero-foot" aria-hidden="true">
            七位角色 · 一份任务书 · 你的决定
          </div>
        </section>

        <section className="landing-statement">
          <div className="landing-statement-inner">
            <p className="landing-kicker" data-reveal>
              为什么是团队
            </p>
            <h2 className="landing-h2" data-reveal>
              不是让 AI 替你写完，
              <br />
              <span>而是让每一步都有人负责。</span>
            </h2>
            <p className="landing-body" data-reveal>
              创作、审稿与试映使用隔离的上下文。程序负责流程、版本与记录，
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
                <p>两个人工闸门会真正停下来等你，重复提交也不会重复执行。</p>
              </li>
            </ul>
          </div>
        </section>

        <section id="team" className="landing-section landing-team">
          <div className="landing-section-head">
            <p className="landing-kicker" data-reveal>
              七个角色
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
              从目标到交付
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
                    </div>
                  ) : null}
                </li>
              ))}
            </ol>

            <aside className="flow-aside">
              <div className="gate-card" data-reveal>
                <p className="landing-kicker">人工闸门 · 一</p>
                <h3>确认任务书</h3>
                <p>
                  目标、受众与硬要求会固定在一份任务书版本里。
                  你确认的是一份可检查的版本，而不是一段模糊描述。
                </p>
              </div>
              <div className="gate-card" data-reveal>
                <p className="landing-kicker">人工闸门 · 二</p>
                <h3>接收内容</h3>
                <p>
                  验收时锁定当前版本并记录你确认的内容；未经确认的版本不会被当作已交付。
                  退回意见会保留在下一次修改里。
                </p>
              </div>
              <p className="flow-note" data-reveal>
                试映前会锁定人设与片段，结果按真实状态记录，
                不把未完成伪装成已完成。
              </p>
            </aside>
          </div>
        </section>

        <section className="landing-cta">
          <p className="landing-kicker" data-reveal>
            从一份真实需求开始
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

        <section id="pricing" className="landing-section landing-pricing">
          <div className="landing-section-head">
            <p className="landing-kicker" data-reveal>
              定价
            </p>
            <h2 className="landing-h2" data-reveal>
              先让一支团队，
              <br />
              <span>替你跑完下一轮内容。</span>
            </h2>
            <p className="landing-body" data-reveal>
              按月订阅，随时取消。每个方案都包含七位 AI 角色、两个人工闸门与完整的版本记录。
            </p>
          </div>

          <div className="pricing-grid">
            {PRICING.map((plan) => (
              <article
                key={plan.id}
                className={cn("pricing-card", plan.featured && "is-featured")}
                data-reveal
              >
                <div className="pricing-card-head">
                  <p className="landing-kicker">{plan.kicker}</p>
                  {plan.featured ? (
                    <span className="pricing-badge">推荐</span>
                  ) : null}
                </div>
                <h3>{plan.name}</h3>
                <p className="pricing-price">
                  <strong>{plan.price}</strong>
                  <span>{plan.period}</span>
                </p>
                <p className="pricing-copy">{plan.description}</p>
                <ul className="pricing-features">
                  {plan.features.map((feature) => (
                    <li key={feature}>{feature}</li>
                  ))}
                </ul>
                <MagneticLink
                  to={enterPath}
                  className={cn(
                    "landing-btn pricing-cta",
                    plan.featured
                      ? "landing-btn-primary"
                      : "landing-btn-ghost",
                  )}
                >
                  {plan.cta}
                  <ArrowRight size={15} />
                </MagneticLink>
              </article>
            ))}
          </div>

          <p className="pricing-note" data-reveal>
            年付 8 折 · 随时取消 · 价格以人民币计
          </p>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-footer-brand">
          <BrandMark size={34} />
          <div>
            <strong>众幕 AI</strong>
            <p>自媒体创作者工作室 · 七个角色协同创作</p>
          </div>
        </div>
        <p className="landing-footer-meta">
          © 2026 众幕 AI · 自媒体创作者工作室
        </p>
        <div className="landing-footer-links">
          <a href="#team">团队</a>
          <a href="#workflow">流程</a>
          <a href="#pricing">定价</a>
          <Link to={enterPath}>工作台</Link>
        </div>
      </footer>
    </div>
  );
}
