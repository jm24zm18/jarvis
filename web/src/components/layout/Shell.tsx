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
  ShieldCheck,
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
  GitBranch,
  Map,
  Rocket,
} from "lucide-react";
import { useThemeStore } from "../../stores/theme";
import { useAuthStore } from "../../stores/auth";
import { logout } from "../../api/endpoints";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "../ui/tooltip";

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
      { label: "Repo", to: "/admin/repo", icon: GitBranch },
      { label: "Roadmap", to: "/admin/roadmap", icon: Map },
      { label: "Swarm", to: "/admin/swarm", icon: Rocket },
      { label: "Memory", to: "/admin/memory", icon: Brain },
      { label: "Schedules", to: "/admin/schedules", icon: Clock },
      { label: "Self-Update", to: "/admin/selfupdate", icon: RefreshCw },
      { label: "Approvals", to: "/admin/approvals", icon: ShieldCheck },
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
  const handleLogout = async () => {
    try {
      await logout();
    } catch {
      // Always clear local auth state even if API logout fails.
    } finally {
      clearAuth();
    }
  };

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex min-h-screen bg-bg">
        <aside
          className={`sticky top-0 flex h-screen flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)] transition-all duration-200 ${collapsed ? "w-14" : "w-52"}`}
        >
          {/* Logo / header */}
          <div className="flex items-center gap-2 border-b border-[var(--color-border)] px-3 py-4">
            {!collapsed && (
              <div className="flex-1 min-w-0">
                <h1 className="font-mono text-xs font-semibold tracking-widest uppercase text-text2">
                  JARVIS<span className="cursor-blink text-accent">_</span>
                </h1>
                <p className="text-[10px] text-text4 font-mono">control center</p>
              </div>
            )}
            <button
              onClick={() => setCollapsed((v) => !v)}
              className="rounded-md p-1.5 text-text3 hover:bg-surface-2"
            >
              {collapsed ? <PanelLeft size={18} /> : <PanelLeftClose size={18} />}
            </button>
          </div>

          {/* Nav */}
          <nav className="flex-1 overflow-y-auto px-2 py-3">
            {navGroups.map((group) => (
              <div key={group.label} className="mb-4">
                {!collapsed && (
                  <div className="mb-1 px-2 text-[9px] font-medium uppercase tracking-[0.15em] text-text4">
                    {group.label}
                  </div>
                )}
                <div className="space-y-0.5">
                  {group.items.map((item) => {
                    const active = location.pathname.startsWith(item.to);
                    const Icon = item.icon;
                    const linkEl = (
                      <Link
                        key={item.to}
                        to={item.to}
                        className={`flex items-center gap-2.5 border-l-2 px-2 py-2 text-sm transition-colors duration-150 ${
                          active
                            ? "border-accent bg-surface-2 text-text"
                            : "border-transparent text-text3 hover:bg-surface-2 hover:text-text2"
                        } ${collapsed ? "justify-center" : ""}`}
                      >
                        <Icon size={17} />
                        {!collapsed && (
                          <span className={active ? "font-medium" : ""}>{item.label}</span>
                        )}
                      </Link>
                    );
                    if (collapsed) {
                      return (
                        <Tooltip key={item.to}>
                          <TooltipTrigger asChild>{linkEl}</TooltipTrigger>
                          <TooltipContent side="right">{item.label}</TooltipContent>
                        </Tooltip>
                      );
                    }
                    return linkEl;
                  })}
                </div>
              </div>
            ))}
          </nav>

          {/* Bottom actions */}
          <div className="border-t border-[var(--color-border)] px-2 py-3 space-y-0.5">
            {collapsed ? (
              <>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      onClick={cycleTheme}
                      className="flex w-full items-center justify-center rounded-md p-2 text-text3 hover:bg-surface-2"
                    >
                      <ThemeIcon size={17} />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="right">Theme: {theme}</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      onClick={handleLogout}
                      className="flex w-full items-center justify-center rounded-md p-2 text-text3 hover:bg-surface-2 hover:text-danger"
                    >
                      <LogOut size={17} />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="right">Logout</TooltipContent>
                </Tooltip>
              </>
            ) : (
              <>
                <button
                  onClick={cycleTheme}
                  className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-text3 hover:bg-surface-2 hover:text-text2"
                >
                  <ThemeIcon size={17} />
                  <span className="capitalize">{theme}</span>
                </button>
                <button
                  onClick={handleLogout}
                  className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-text3 hover:bg-surface-2 hover:text-danger"
                >
                  <LogOut size={17} />
                  <span>Logout</span>
                </button>
              </>
            )}
          </div>
        </aside>

        <main className="flex-1 overflow-auto p-6 bg-bg">
          <div className="mx-auto max-w-7xl">{children}</div>
        </main>
      </div>
    </TooltipProvider>
  );
}
