import { Link, useLocation } from "react-router-dom";
import { useState, type PropsWithChildren } from "react";
import {
  MessageSquare,
  LayoutDashboard,
  Bot,
  Activity,
  Brain,
  Clock,
  MessagesSquare,
  RefreshCw,
  Shield,
  Scale,
  Server,
  Bug,
  Sun,
  Moon,
  Monitor,
  Smartphone,
  LogOut,
  PanelLeftClose,
  PanelLeft,
} from "lucide-react";
import { useThemeStore } from "../../stores/theme";
import { useAuthStore } from "../../stores/auth";

const navGroups = [
  {
    label: "Conversations",
    items: [
      { label: "Chat", to: "/chat", icon: MessageSquare },
      { label: "Threads", to: "/admin/threads", icon: MessagesSquare },
    ],
  },
  {
    label: "System",
    items: [
      { label: "Dashboard", to: "/admin/dashboard", icon: LayoutDashboard },
      { label: "Agents", to: "/admin/agents", icon: Bot },
      { label: "Providers", to: "/admin/providers", icon: Server },
      { label: "Channels", to: "/admin/channels", icon: Smartphone },
      { label: "Memory", to: "/admin/memory", icon: Brain },
      { label: "Schedules", to: "/admin/schedules", icon: Clock },
      { label: "Self-Update", to: "/admin/selfupdate", icon: RefreshCw },
      { label: "Governance", to: "/admin/governance", icon: Scale },
      { label: "Permissions", to: "/admin/permissions", icon: Shield },
    ],
  },
  {
    label: "Tracking",
    items: [
      { label: "Events", to: "/admin/events", icon: Activity },
      { label: "Bugs", to: "/admin/bugs", icon: Bug },
    ],
  },
] as const;

const themeIcons = { light: Sun, dark: Moon, system: Monitor } as const;
const themeOrder: Array<"light" | "dark" | "system"> = ["light", "dark", "system"];

export default function Shell({ children }: PropsWithChildren) {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const theme = useThemeStore((s) => s.theme);
  const setTheme = useThemeStore((s) => s.setTheme);
  const clearAuth = useAuthStore((s) => s.clearAuth);

  const cycleTheme = () => {
    const idx = themeOrder.indexOf(theme);
    setTheme(themeOrder[(idx + 1) % themeOrder.length]);
  };
  const ThemeIcon = themeIcons[theme];

  return (
    <div className="flex min-h-screen">
      <aside
        className={`sticky top-0 flex h-screen flex-col border-r border-[var(--border-default)] bg-surface transition-all ${collapsed ? "w-16" : "w-60"}`}
      >
        <div className="flex items-center gap-2 border-b border-[var(--border-default)] px-3 py-4">
          {!collapsed && (
            <div className="flex-1">
              <h1 className="font-display text-lg text-[var(--text-primary)]">Jarvis</h1>
              <p className="text-[11px] text-[var(--text-muted)]">Control Center</p>
            </div>
          )}
          <button
            onClick={() => setCollapsed((v) => !v)}
            className="rounded-md p-1.5 text-[var(--text-muted)] hover:bg-mist"
          >
            {collapsed ? <PanelLeft size={18} /> : <PanelLeftClose size={18} />}
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {navGroups.map((group) => (
            <div key={group.label} className="mb-4">
              {!collapsed && (
                <div className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  {group.label}
                </div>
              )}
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const active = location.pathname.startsWith(item.to);
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.to}
                      to={item.to}
                      title={collapsed ? item.label : undefined}
                      className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition ${
                        active
                          ? "bg-[#13293d] text-white dark:bg-slate-200 dark:text-slate-900"
                          : "text-[var(--text-secondary)] hover:bg-mist hover:text-[var(--text-primary)]"
                      } ${collapsed ? "justify-center" : ""}`}
                    >
                      <Icon size={18} />
                      {!collapsed && <span>{item.label}</span>}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-t border-[var(--border-default)] px-2 py-3 space-y-1">
          <button
            onClick={cycleTheme}
            title={`Theme: ${theme}`}
            className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-[var(--text-secondary)] hover:bg-mist ${collapsed ? "justify-center" : ""}`}
          >
            <ThemeIcon size={18} />
            {!collapsed && <span className="capitalize">{theme}</span>}
          </button>
          <button
            onClick={clearAuth}
            className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-[var(--text-secondary)] hover:bg-mist hover:text-red-500 ${collapsed ? "justify-center" : ""}`}
          >
            <LogOut size={18} />
            {!collapsed && <span>Logout</span>}
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-auto p-4 md:p-6">
        <div className="mx-auto max-w-7xl">{children}</div>
      </main>
    </div>
  );
}
