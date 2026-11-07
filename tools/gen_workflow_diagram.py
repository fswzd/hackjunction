# -*- coding: utf-8 -*-
"""生成 docs/orchestration/seven-agent-workflow.svg（全中文 · 扁平图标风格）。

七角色编排工作图：主链 + 可选试映/局部改稿分支 + 统一交互通道 + 图例。
"""
import html

W, H = 1520, 1280
FONT = "'Microsoft YaHei', 'PingFang SC', 'Helvetica Neue', Arial, sans-serif"

ROLE = {  # 七角色按次序：红 橙 黄 绿 青 蓝 紫
    "pr": ("#fecaca", "#ef4444"),   # 红 商单需求分析员
    "op": ("#fed7aa", "#f97316"),   # 橙 运营官
    "cc": ("#fef08a", "#eab308"),   # 黄 内容主创
    "er": ("#bbf7d0", "#22c55e"),   # 绿 审稿员
    "ts": ("#a5f3fc", "#06b6d4"),   # 青 流量捕捉者
    "da": ("#bfdbfe", "#3b82f6"),   # 蓝 数据分析师
    "sa": ("#ddd6fe", "#8b5cf6"),   # 紫 模拟观众
}
GRAYF, GRAYS = "#ffffff", "#d1d5db"   # 其他：白盒
GATEF, GATES = "#e5e7eb", "#9ca3af"   # 闸门：灰
ARROW_COLORS = {"blue": "#64748b", "orange": "#64748b", "purple": "#64748b", "gray": "#94a3b8"}

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


# ---------------- 标题 ----------------
add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
add(f'  <style>text {{ font-family: {FONT}; }}</style>')
add('  <defs>')
for name, col in ARROW_COLORS.items():
    add(f'    <marker id="arrow-{name}" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">')
    add(f'      <polygon points="0 0, 10 3.5, 0 7" fill="{col}"/>')
    add('    </marker>')
add('  </defs>')
add(f'  <rect width="{W}" height="{H}" fill="#ffffff"/>')
label(760, 42, "多智能体自媒体内容系统 · 七角色编排工作图（契约版本 v0.1）", 20, "#111827", "middle", "600")
label(760, 66, "编排层 = LangGraph 状态图（确定性控制器）· 业务角色固定七个 · 模拟实现已接通，真实入口待接入", 12, "#6b7280")

# ---------------- 左侧：七角色色卡 ----------------
add('  <rect x="24" y="88" width="230" height="472" rx="10" fill="#ffffff" stroke="#d1d5db" stroke-width="1.5"/>')
label(139, 112, "七角色 × 职责动作", 14, "#111827", "middle", "600")
rows = [
    ("pr", "商单需求分析员", "商单需求分析"),
    ("op", "运营官", "整理简报"),
    ("cc", "内容主创", "写初稿 / 定向修订"),
    ("er", "审稿员", "独立审校"),
    ("ts", "流量捕捉者", "发现选题"),
    ("da", "数据分析师", "试映诊断"),
    ("sa", "模拟观众", "逐段阅读"),
]
for i, (k, name, act) in enumerate(rows):
    y = 128 + i * 60
    f, s = ROLE[k]
    add(f'  <rect x="38" y="{y}" width="202" height="50" rx="8" fill="{f}" stroke="{s}" stroke-width="1.5"/>')
    label(139, y + 21, name, 12, "#111827", "middle", "600")
    label(139, y + 38, act, 10, "#6b7280")
label(139, 572, "统一经适配器调用交互", 9.5, "#9ca3af")

# ---------------- 中间：内容交付主链 ----------------
add('  <circle cx="520" cy="100" r="11" fill="#ffffff" stroke="#374151" stroke-width="1.6"/>')
add('  <path d="M520,111 V138 M502,122 H538 M520,138 L507,158 M520,138 L533,158" fill="none" stroke="#374151" stroke-width="1.6"/>')
label(520, 176, "用户：目标 / 素材 / 旧稿 / 商单", 12, "#111827", "middle", "600")
arrow("M520,186 V204")

box(405, 208, 230, 44, "程序路由", "不看模型输出的跳转指令", GRAYF, GRAYS, fs1=13)
arrow("M520,252 V276 H355 V296")
arrow("M520,276 V296")
arrow("M520,276 H685 V296")
label(345, 289, "商单需求", 10, "#6b7280", "end")
label(532, 289, "需要捕捉", 10, "#6b7280", "start")
label(695, 289, "明确目标/旧稿", 10, "#6b7280", "start")

f, s = ROLE["pr"]
box(280, 300, 150, 66, "商单需求分析员", "商单需求分析", f, s, fs1=11.5)
label(355, 378, "需求分析独立预算", 9, "#6b7280")
f, s = ROLE["ts"]
box(445, 300, 150, 66, "流量捕捉者", "发现选题（可选）", f, s, fs1=11.5)
label(520, 378, "选题发现独立预算", 9, "#6b7280")
box(610, 300, 150, 66, "跳过", "记录跳过原因", GRAYF, GRAYS, fs1=12)

arrow("M355,366 V388 H520 V408")
arrow("M520,366 V408")
arrow("M685,366 V388 H520")

f, s = ROLE["op"]
box(405, 412, 230, 52, "运营官 · 整理简报", "开放问题为空才可确认", f, s, fs1=12.5)
diamond(520, 540, 270, 76, "闸门 · 确认简报", "绑定版本 + 内容指纹")
arrow("M520,464 V498", "orange")
label(534, 486, "信息齐全", 10)
arrow("M385,540 H356 V438 H401", "purple", dash="5,3")
label(348, 486, "缺信息 → 补料", 10, "#475569", "end")
label(348, 500, "补料闸门 · 同预算", 9, "#9ca3af", "end")

arrow("M520,578 V608", "orange")
label(534, 598, "批准", 10)
f, s = ROLE["cc"]
box(405, 612, 230, 52, "内容主创 · 写初稿", "未确认不写一字", f, s, fs1=12.5)
arrow("M520,664 V696")
label(534, 684, "初稿", 10)
box(405, 700, 230, 44, "程序规则校验", "规则集 v1 · 零模型调用", GRAYF, GRAYS, fs1=12.5)
arrow("M520,744 V782")
label(534, 768, "通过", 10)
f, s = ROLE["er"]
box(405, 786, 230, 52, "审稿员 · 独立审校", "看不到主创自评与聊天", f, s, fs1=12.5)

f, s = ROLE["cc"]
box(700, 694, 190, 52, "内容主创 · 定向修订", "业务修订 ≤ 1 次", f, s, fs1=11.5)
arrow("M635,716 H696", "purple")
label(665, 708, "可修复且未修过", 9.5, "#475569")
arrow("M795,746 V770 H535 V748", "purple")
label(660, 784, "修复后重走规则", 9.5, "#475569")
arrow("M635,806 H920 V720 H894", "purple")
label(770, 820, "需改且未修过", 9.5, "#475569")
label(712, 858, "已修过仍阻断 → 转人工处理", 9.5, "#9ca3af")

arrow("M520,838 V868")
label(534, 858, "通过", 10)
box(405, 872, 230, 44, "程序导出", "MD/TXT 文件就绪 · 零模型", GRAYF, GRAYS, fs1=12.5)
diamond(520, 990, 270, 76, "闸门 · 接受交付", "接受交付？")
arrow("M520,916 V948", "orange")
label(534, 938, "导出完成", 10)
add('  <rect x="405" y="1060" width="230" height="52" rx="4" fill="#ffffff" stroke="#374151" stroke-width="1.8"/>')
label(520, 1082, "完成 · 版本已接受", 12.5, "#111827", "middle", "600")
label(520, 1100, "拒绝 → 版本保持可下载", 10, "#6b7280")
arrow("M520,1028 V1056", "orange")
label(534, 1046, "接受", 10)

# ---------------- 右侧：可选试映与局部改稿 ----------------
add('  <rect x="980" y="180" width="340" height="800" rx="12" fill="#ffffff" stroke="#d1d5db" stroke-width="1.5" stroke-dasharray="6,4"/>')
label(1150, 208, "可选 · 试映与局部改稿", 13, "#111827", "middle", "600")
label(1150, 226, "独立的试映运行与修订运行 · 未选建议零改稿", 9.5, "#6b7280")

arrow("M635,894 H940 V292 H1004", "gray", dash="6,4")
label(790, 882, "合格冻结版本（可选试映）", 10, "#6b7280")

diamond(1150, 290, 280, 76, "闸门 · 确认试映条件", "冻结场景 + 确认预算")
arrow("M1150,328 V356")
label(1162, 348, "逐段执行", 10)

add('  <rect x="1000" y="360" width="300" height="160" rx="10" fill="#ffffff" stroke="#c7d2fe" stroke-width="1.2" stroke-dasharray="4,3"/>')
f, s = ROLE["sa"]
box(1025, 385, 200, 56, "模拟观众 · 逐段阅读", "只见四类字段", f, s, fs1=11.5)
arrow("M1225,398 C1288,378 1288,448 1225,432", "purple")
label(1150, 472, "循环：切片投影 → 逐段阅读 → 提交反应 → 推进", 9.5, "#6b7280")
label(1150, 490, "选择退出 = 结束本会话 · 超时 = 未完成（不伪造退出）", 9.5, "#9ca3af")

arrow("M1150,520 V541")
label(1162, 536, "全部会话结束", 10)
box(1030, 545, 240, 40, "程序指标统计（零模型）", None, GRAYF, GRAYS, fs1=11.5)
arrow("M1150,585 V606")
f, s = ROLE["da"]
box(1030, 610, 240, 54, "数据分析师 · 试映诊断", "建议须引用真实反应记录", f, s, fs1=11.5)
arrow("M1150,664 V703")
label(1162, 688, "建议展示（模板渲染 · 零模型）", 9.5)
diamond(1150, 745, 280, 76, "闸门 · 选择修改建议", "选择建议 / 范围 / 预算")
arrow("M1150,783 V811", "orange")
label(1162, 800, "选中建议", 10)
f, s = ROLE["cc"]
box(1030, 815, 240, 52, "内容主创 · 局部修订", "范围校验 · 未选片段不变", f, s, fs1=11.5)
arrow("M1150,867 V881")
box(1030, 885, 240, 48, "规则 → 审校 → 导出新版本", "保留旧的可下载/已接受版本", GRAYF, GRAYS, fs1=11)
arrow("M1290,745 H1372", "purple", dash="5,3")
label(1380, 740, "未选择 → 零改稿", 10, "#475569", "start")
arrow("M1270,909 H1372", "purple", dash="5,3")
label(1380, 904, "重测：新运行 + 新预算", 10, "#475569", "start")

# ---------------- 底部：统一交互通道 ----------------
label(770, 1150, "统一交互通道 · 七个智能体互不直接调用 —— 模型输出的“下一个智能体 / 跳转 / 已获批准”不参与调度", 13, "#111827", "middle", "600")
strip = [
    ("LangGraph 节点", "状态图 + 条件分支"),
    ("适配器统一调用", "调用请求 → 调用结果"),
    ("网关", "预算 · 回执重放 · 取消护栏"),
    ("领域数据库（SQLite）", "事实源 · 版本/闸门/账本"),
    ("七角色：模拟 / 真实", "正式模式不回退模拟"),
]
for i, (a, b) in enumerate(strip):
    x = 76 + i * 290
    box(x, 1166, 230, 46, a, b, GRAYF, GRAYS, fs1=11.5, fs2=9.5)
    if i < 4:
        arrow(f"M{x+230},1189 H{x+286}", "purple")

# ---------------- 图例 ----------------
ly = 1252
add(f'  <rect x="76" y="{ly - 9}" width="18" height="14" rx="3" fill="#fecaca" stroke="#ef4444" stroke-width="1.2"/>')
add(f'  <rect x="98" y="{ly - 9}" width="18" height="14" rx="3" fill="#fed7aa" stroke="#f97316" stroke-width="1.2"/>')
add(f'  <rect x="120" y="{ly - 9}" width="18" height="14" rx="3" fill="#fef08a" stroke="#eab308" stroke-width="1.2"/>')
add(f'  <rect x="142" y="{ly - 9}" width="18" height="14" rx="3" fill="#bbf7d0" stroke="#22c55e" stroke-width="1.2"/>')
add(f'  <rect x="164" y="{ly - 9}" width="18" height="14" rx="3" fill="#a5f3fc" stroke="#06b6d4" stroke-width="1.2"/>')
add(f'  <rect x="186" y="{ly - 9}" width="18" height="14" rx="3" fill="#bfdbfe" stroke="#3b82f6" stroke-width="1.2"/>')
add(f'  <rect x="208" y="{ly - 9}" width="18" height="14" rx="3" fill="#ddd6fe" stroke="#8b5cf6" stroke-width="1.2"/>')
label(236, ly + 4, "七角色：红橙黄绿青蓝紫", 10, "#6b7280", "start")
add(f'  <polygon points="420,{ly - 10} 432,{ly - 2} 420,{ly + 6} 408,{ly - 2}" fill="#e5e7eb" stroke="#9ca3af" stroke-width="1.2"/>')
label(440, ly + 4, "用户闸门（灰）", 10, "#6b7280", "start")
add(f'  <rect x="580" y="{ly - 9}" width="18" height="14" rx="3" fill="#ffffff" stroke="#d1d5db" stroke-width="1.2"/>')
label(606, ly + 4, "程序步骤/其他（白）", 10, "#6b7280", "start")
add(f'  <line x1="780" y1="{ly}" x2="820" y2="{ly}" stroke="#94a3b8" stroke-width="1.6" stroke-dasharray="5,3" marker-end="url(#arrow-gray)"/>')
label(828, ly + 4, "可选分支/循环", 10, "#6b7280", "start")
label(1466, ly + 4, "证据分级：接口检查 √ · 模拟流程 √ · 真实联调/模型/用户 × 待接入", 10, "#9ca3af", "end")

add('</svg>')

out = "docs/orchestration/seven-agent-workflow.svg"
with open(out, "w", encoding="utf-8") as fh:
    fh.write("\n".join(L))
print("中文工作图已生成:", out, len(L), "行")
