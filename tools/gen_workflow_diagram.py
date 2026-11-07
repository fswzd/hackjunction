# -*- coding: utf-8 -*-
"""Generate docs/orchestration/seven-agent-workflow.svg (flat-icon style).

Seven-agent orchestration workflow: main chain + optional preview/scoped-revision
branch + unified AgentAdapter/Gateway channel + legend.
"""
import html

W, H = 1520, 1280
FONT = "'Helvetica Neue', Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif"

ROLE = {
    "pr": ("#ede9fe", "#c4b5fd"),
    "op": ("#dbeafe", "#93c5fd"),
    "cc": ("#dcfce7", "#86efac"),
    "er": ("#fee2e2", "#fca5a5"),
    "ts": ("#ccfbf1", "#5eead4"),
    "da": ("#fef9c3", "#fde047"),
    "sa": ("#e0e7ff", "#a5b4fc"),
}
GRAYF, GRAYS = "#f9fafb", "#d1d5db"
GATEF, GATES = "#fed7aa", "#fdba74"
ARROW_COLORS = {"blue": "#2563eb", "orange": "#ea580c", "purple": "#9333ea", "gray": "#6b7280"}

L = []


def add(s):
    L.append(s)


def esc(t):
    return html.escape(t, quote=True)


def box(x, y, w, h, l1, l2=None, fill=GRAYF, stroke=GRAYS, rx=8, fs1=13, fs2=11,
        bold=True, dark="#111827", sub="#6b7280"):
    add(f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
    cx = x + w / 2
    weight = "600" if bold else "400"
    if l2 is not None:
        add(f'  <text x="{cx}" y="{y + h/2 - 4}" text-anchor="middle" font-size="{fs1}" font-weight="{weight}" fill="{dark}">{esc(l1)}</text>')
        add(f'  <text x="{cx}" y="{y + h/2 + 14}" text-anchor="middle" font-size="{fs2}" fill="{sub}">{esc(l2)}</text>')
    else:
        add(f'  <text x="{cx}" y="{y + h/2 + 5}" text-anchor="middle" font-size="{fs1}" font-weight="{weight}" fill="{dark}">{esc(l1)}</text>')


def diamond(cx, cy, w, h, l1, l2):
    hw, hh = w / 2, h / 2
    add(f'  <polygon points="{cx-hw},{cy} {cx},{cy-hh} {cx+hw},{cy} {cx},{cy+hh}" fill="{GATEF}" stroke="{GATES}" stroke-width="1.5"/>')
    add(f'  <text x="{cx}" y="{cy - 2}" text-anchor="middle" font-size="12" font-weight="600" fill="#111827">{esc(l1)}</text>')
    add(f'  <text x="{cx}" y="{cy + 15}" text-anchor="middle" font-size="10" fill="#6b7280">{esc(l2)}</text>')


def arrow(d, color="blue", dash=None):
    mk = f"arrow-{color}"
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'  <path d="{d}" fill="none" stroke="{ARROW_COLORS[color]}" stroke-width="1.6" marker-end="url(#{mk})"{dash_attr}/>')


def label(x, y, t, size=10, fill="#6b7280", anchor="middle", weight="400"):
    add(f'  <text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" font-weight="{weight}" fill="{fill}">{esc(t)}</text>')


# ---------------- header ----------------
add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
add(f'  <style>text {{ font-family: {FONT}; }}</style>')
add('  <defs>')
for name, col in ARROW_COLORS.items():
    add(f'    <marker id="arrow-{name}" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">')
    add(f'      <polygon points="0 0, 10 3.5, 0 7" fill="{col}"/>')
    add('    </marker>')
add('  </defs>')
add(f'  <rect width="{W}" height="{H}" fill="#ffffff"/>')
label(760, 42, "多 Agent 自媒体内容系统 · 七角色编排 workflow（seven-agent.v0.1）", 20, "#111827", "middle", "600")
label(760, 66, "编排层 = LangGraph StateGraph（确定性控制器）· 业务角色固定七个 · Mock 已接通，真实入口待接入", 12, "#6b7280")

# ---------------- left card: seven roles ----------------
add('  <rect x="24" y="88" width="230" height="472" rx="10" fill="#ffffff" stroke="#d1d5db" stroke-width="1.5"/>')
label(139, 112, "七角色 × action", 14, "#111827", "middle", "600")
rows = [
    ("pr", "pr_analyst 商单需求分析员", "analyze_request"),
    ("op", "operations_officer 运营官", "prepare_brief"),
    ("cc", "content_creator 内容主创", "draft / revise"),
    ("er", "editorial_reviewer 审稿员", "assess_content"),
    ("ts", "traffic_scout 流量捕捉者", "capture_opportunities"),
    ("da", "data_analyst 数据分析师", "diagnose_preview"),
    ("sa", "simulated_audience 模拟观众", "read_segment"),
]
for i, (k, name, act) in enumerate(rows):
    y = 128 + i * 60
    f, s = ROLE[k]
    add(f'  <rect x="38" y="{y}" width="202" height="50" rx="8" fill="{f}" stroke="{s}" stroke-width="1.5"/>')
    label(139, y + 21, name, 11.5, "#111827", "middle", "600")
    label(139, y + 38, act, 10, "#6b7280")
label(139, 572, "统一经 AgentAdapter.invoke 交互", 9.5, "#9ca3af")

# ---------------- center main chain ----------------
add('  <circle cx="520" cy="100" r="11" fill="#ffffff" stroke="#374151" stroke-width="1.6"/>')
add('  <path d="M520,111 V138 M502,122 H538 M520,138 L507,158 M520,138 L533,158" fill="none" stroke="#374151" stroke-width="1.6"/>')
label(520, 176, "用户：目标 / 素材 / 旧稿 / 商单", 12, "#111827", "middle", "600")
arrow("M520,186 V204")

box(405, 208, 230, 44, "route · 程序路由", "不看模型输出的 next_agent/goto", GRAYF, GRAYS, fs1=12.5)
arrow("M520,252 V276 H355 V296")
arrow("M520,276 V296")
arrow("M520,276 H685 V296")
label(345, 289, "商单", 10, "#6b7280", "end")
label(532, 289, "需捕捉", 10, "#6b7280", "start")
label(695, 289, "明确目标/旧稿", 10, "#6b7280", "start")

f, s = ROLE["pr"]
box(280, 300, 150, 66, "pr_analyst", "analyze_request", f, s, fs1=12)
label(355, 384, "pr_intake 子预算", 9, "#6b7280")
f, s = ROLE["ts"]
box(445, 300, 150, 66, "traffic_scout", "capture_opportunities", f, s, fs1=12)
label(520, 384, "scout 子预算 · 可选", 9, "#6b7280")
box(610, 300, 150, 66, "跳过", "记录 traffic_skipped", GRAYF, GRAYS, fs1=12)

arrow("M355,366 V388 H520 V408")
arrow("M520,366 V408")
arrow("M685,366 V388 H520")

f, s = ROLE["op"]
box(405, 412, 230, 52, "operations_officer · prepare_brief", "整理 Brief（open_questions 空才可确认）", f, s, fs1=12)
diamond(520, 540, 270, 76, "闸门 confirm_brief", "确认 Brief 版本 + hash")
arrow("M520,464 V498", "orange")
label(534, 486, "信息齐全", 10)
arrow("M385,540 H356 V438 H401", "purple", dash="5,3")
label(348, 486, "缺信息→补料", 10, "#9333ea", "end")
label(348, 500, "wait_input·同预算", 9, "#9ca3af", "end")

arrow("M520,578 V608", "orange")
label(534, 598, "批准", 10)
f, s = ROLE["cc"]
box(405, 612, 230, 52, "content_creator · draft", "初稿（未确认零主创）", f, s, fs1=12)
arrow("M520,664 V696")
label(534, 684, "初稿", 10)
box(405, 700, 230, 44, "rules · 程序规则校验", "content-rules-v1（0 模型）", GRAYF, GRAYS, fs1=12)
arrow("M520,744 V782")
label(534, 768, "通过", 10)
f, s = ROLE["er"]
box(405, 786, 230, 52, "editorial_reviewer · assess_content", "独立上下文审校（无主创自评）", f, s, fs1=12)

f, s = ROLE["cc"]
box(700, 694, 190, 52, "content_creator · revise", "定向修订（业务修订 ≤1 次）", f, s, fs1=11.5)
arrow("M635,716 H696", "purple")
label(665, 708, "可修复且未修过", 9.5, "#9333ea")
arrow("M795,746 V770 H535 V748", "purple")
label(660, 784, "修复后重走规则", 9.5, "#9333ea")
arrow("M635,806 H920 V720 H894", "purple")
label(770, 820, "需改且未修过", 9.5, "#9333ea")
label(838, 752, "已修过仍阻断 → 人工", 9, "#9ca3af")

arrow("M520,838 V868")
label(534, 858, "通过", 10)
box(405, 872, 230, 44, "export · 程序导出", "MD/TXT 就绪 · 0 模型调用", GRAYF, GRAYS, fs1=12)
diamond(520, 990, 270, 76, "闸门 accept_delivery", "接受交付？")
arrow("M520,916 V948", "orange")
label(534, 938, "导出完成", 10)
add('  <rect x="405" y="1060" width="230" height="52" rx="6" fill="#111827" stroke="#374151" stroke-width="1.5"/>')
label(520, 1082, "READY · 版本 accepted", 12, "#ffffff", "middle", "600")
label(520, 1100, "拒绝 → 保持 ready 可下载", 10, "#d1d5db")
arrow("M520,1028 V1056", "orange")
label(534, 1046, "接受", 10)

# ---------------- right column: preview & scoped revision ----------------
add('  <rect x="980" y="180" width="340" height="800" rx="12" fill="#fafafa" stroke="#d1d5db" stroke-width="1.5" stroke-dasharray="6,4"/>')
label(1150, 208, "可选 · 试映与局部改稿", 13, "#111827", "middle", "600")
label(1150, 226, "独立 preview run / revision run · 未选建议零改稿", 9.5, "#6b7280")

arrow("M635,894 H940 V292 H1004", "gray", dash="6,4")
label(790, 882, "合格冻结版本（可选试映）", 10, "#6b7280")

diamond(1150, 290, 280, 76, "闸门 preview_conditions", "冻结场景 + 预算确认")
arrow("M1150,328 V356")
label(1162, 348, "逐段执行", 10)

add('  <rect x="1000" y="360" width="300" height="160" rx="10" fill="#ffffff" stroke="#c7d2fe" stroke-width="1.2" stroke-dasharray="4,3"/>')
f, s = ROLE["sa"]
box(1025, 385, 200, 56, "simulated_audience", "read_segment（逐段 · 只见四字段）", f, s, fs1=11.5)
arrow("M1225,398 C1288,378 1288,448 1225,432", "purple")
label(1150, 472, "循环：投影 → read_segment → 提交事件 → 推进", 9.5, "#6b7280")
label(1150, 490, "exit 结束本会话 · 超时 incomplete（不伪造 exit）", 9.5, "#9ca3af")

arrow("M1150,520 V541")
label(1162, 536, "全部会话结束", 10)
box(1030, 545, 240, 40, "程序指标 Metrics（0 模型）", None, GRAYF, GRAYS, fs1=11.5)
arrow("M1150,585 V606")
f, s = ROLE["da"]
box(1030, 610, 240, 54, "data_analyst · diagnose_preview", "片段诊断（finding 引用真实事件）", f, s, fs1=11.5)
arrow("M1150,664 V703")
label(1162, 688, "建议展示（模板渲染 0 模型）", 9.5)
diamond(1150, 745, 280, 76, "闸门 select_findings", "选择 finding / 范围 / 预算")
arrow("M1150,783 V811", "orange")
label(1162, 800, "选中 finding", 10)
f, s = ROLE["cc"]
box(1030, 815, 240, 52, "content_creator · revise（局部）", "scope 校验 · 未选片段不变", f, s, fs1=11.5)
arrow("M1150,867 V881")
box(1030, 885, 240, 48, "rules → assess_content → export v2", "保留旧 ready/accepted 版本", GRAYF, GRAYS, fs1=10.5)
arrow("M1290,745 H1372", "purple", dash="5,3")
label(1380, 740, "未选择 → 零改稿", 10, "#9333ea", "start")
arrow("M1270,909 H1372", "purple", dash="5,3")
label(1380, 904, "重测：新 run + 新预算", 10, "#9333ea", "start")

# ---------------- bottom strip: unified channel ----------------
label(770, 1150, "统一交互通道 · 七个 Agent 互不直接调用 —— 模型输出 next_agent / goto /「已获批准」不参与调度", 13, "#111827", "middle", "600")
strip = [
    ("LangGraph 节点", "StateGraph + 条件边"),
    ("AgentAdapter.invoke", "AgentCall → AgentResult"),
    ("Gateway", "预算 · 回执重放 · 取消 fence"),
    ("Repository（SQLite）", "领域事实源 · 版本/闸门/账本"),
    ("七角色 Mock / 真实", "live 不回退 Mock"),
]
for i, (a, b) in enumerate(strip):
    x = 76 + i * 290
    box(x, 1166, 230, 46, a, b, GRAYF, GRAYS, fs1=11.5, fs2=9.5)
    if i < 4:
        arrow(f"M{x+230},1189 H{x+286}", "purple")

# ---------------- legend ----------------
ly = 1252
add(f'  <line x1="76" y1="{ly}" x2="116" y2="{ly}" stroke="#2563eb" stroke-width="1.6" marker-end="url(#arrow-blue)"/>')
label(122, ly + 4, "主链数据流", 10, "#6b7280", "start")
add(f'  <line x1="256" y1="{ly}" x2="296" y2="{ly}" stroke="#ea580c" stroke-width="1.6" marker-end="url(#arrow-orange)"/>')
label(302, ly + 4, "用户闸门/决策", 10, "#6b7280", "start")
add(f'  <line x1="456" y1="{ly}" x2="496" y2="{ly}" stroke="#9333ea" stroke-width="1.6" marker-end="url(#arrow-purple)"/>')
label(502, ly + 4, "循环/修订/协议调用", 10, "#6b7280", "start")
add(f'  <line x1="676" y1="{ly}" x2="716" y2="{ly}" stroke="#6b7280" stroke-width="1.6" stroke-dasharray="6,4" marker-end="url(#arrow-gray)"/>')
label(722, ly + 4, "可选分支/记录", 10, "#6b7280", "start")
label(1466, ly + 4, "证据分级：接口检查 ✓ · Mock 流程 ✓ · 真实联调/模型/用户 ✗ 待接入", 10, "#9ca3af", "end")

add('</svg>')

out = "docs/orchestration/seven-agent-workflow.svg"
with open(out, "w", encoding="utf-8") as fh:
    fh.write("\n".join(L))
print("SVG written:", out, len(L), "lines")
