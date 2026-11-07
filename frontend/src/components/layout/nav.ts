import {
  BarChart3,
  CalendarDays,
  FolderKanban,
  LayoutDashboard,
  Library,
  ListChecks,
  Settings,
  Users,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  sub: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/workspace/overview", label: "工作台总览", sub: "今天的工作台", icon: LayoutDashboard },
  { to: "/workspace/workforce", label: "协作团队", sub: "七位角色的分工与状态", icon: Users },
  { to: "/workspace/projects", label: "内容项目", sub: "持续创作的主题", icon: FolderKanban },
  { to: "/workspace/tasks", label: "任务中心", sub: "从任务书到交付", icon: ListChecks },
  { to: "/workspace/calendar", label: "创作日历", sub: "排期与节奏", icon: CalendarDays },
  { to: "/workspace/assets", label: "素材库", sub: "已验收的内容资产", icon: Library },
  { to: "/workspace/analytics", label: "运营分析", sub: "内容表现与诊断", icon: BarChart3 },
  { to: "/workspace/settings", label: "设置", sub: "本地工作区与接口", icon: Settings },
];

export function pageTitle(pathname: string): { title: string; sub: string } {
  if (pathname.startsWith("/workspace/tasks/")) {
    return { title: "任务详情", sub: "任务书、版本与审批记录" };
  }
  const match = NAV_ITEMS.find((item) => pathname.startsWith(item.to));
  return match
    ? { title: match.label, sub: match.sub }
    : { title: "工作台", sub: "内容工作室" };
}
