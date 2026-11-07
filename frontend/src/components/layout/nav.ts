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
  en: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/workspace/overview", label: "工作台总览", en: "Overview", icon: LayoutDashboard },
  { to: "/workspace/workforce", label: "AI 员工", en: "AI Workforce", icon: Users },
  { to: "/workspace/projects", label: "内容项目", en: "Projects", icon: FolderKanban },
  { to: "/workspace/tasks", label: "任务中心", en: "Tasks", icon: ListChecks },
  { to: "/workspace/calendar", label: "创作日历", en: "Calendar", icon: CalendarDays },
  { to: "/workspace/assets", label: "素材库", en: "Assets", icon: Library },
  { to: "/workspace/analytics", label: "运营分析", en: "Analytics", icon: BarChart3 },
  { to: "/workspace/settings", label: "设置", en: "Settings", icon: Settings },
];

export function pageTitle(pathname: string): { title: string; en: string } {
  if (pathname.startsWith("/workspace/tasks/")) {
    return { title: "任务详情", en: "Task detail" };
  }
  const match = NAV_ITEMS.find((item) => pathname.startsWith(item.to));
  return match
    ? { title: match.label, en: match.en }
    : { title: "工作台", en: "Workspace" };
}
