"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard, Search, Users, MessageSquare,
  Globe, BarChart2, Settings, KanbanSquare, CheckSquare,
  Shield, Radio, LogOut,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { useAuthStore } from "@/lib/stores/authStore";
import api from "@/lib/api/client";

const NAV_SECTIONS = [
  {
    label: "Prospecting",
    items: [
      { label: "Dashboard",    href: "/dashboard",    icon: LayoutDashboard },
      { label: "Discover",     href: "/discover",     icon: Search },
      { label: "Leads",        href: "/leads",        icon: Users },
      { label: "CRM Pipeline", href: "/crm",          icon: KanbanSquare },
      { label: "Sources",      href: "/sources",      icon: Radio },
    ],
  },
  {
    label: "Engagement",
    items: [
      { label: "Comments",     href: "/comments",     icon: MessageSquare },
      { label: "Email Health", href: "/email-health", icon: Globe },
      { label: "Tasks",        href: "/tasks",        icon: CheckSquare },
    ],
  },
  {
    label: "Insights",
    items: [
      { label: "Analytics",    href: "/analytics",    icon: BarChart2 },
      { label: "Audit Log",    href: "/audit-log",    icon: Shield },
      { label: "Settings",     href: "/settings",     icon: Settings },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const user = useAuthStore((s: any) => s.user);
  const clearAuth = useAuthStore((s: any) => s.clearAuth);

  async function handleLogout() {
    try { await api.post("/auth/logout"); } catch {}
    clearAuth();
    router.push("/login");
  }

  const initials = user?.name
    ? user.name.split(" ").map((n: string) => n[0]).join("").slice(0, 2).toUpperCase()
    : "P";

  return (
    <aside className="flex h-full w-56 flex-col border-r border-gray-200 bg-white">
      {/* Logo */}
      <div className="flex h-14 items-center border-b border-gray-200 px-4">
        <span className="text-lg font-bold text-brand-600">ProspectOS</span>
        <span className="ml-1.5 rounded bg-brand-100 px-1.5 py-0.5 text-[10px] font-semibold text-brand-700">BETA</span>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-3 py-3 space-y-4 scrollbar-thin">
        {NAV_SECTIONS.map(({ label, items }) => (
          <div key={label}>
            <p className="mb-1 px-2.5 text-[10px] font-semibold uppercase tracking-wider text-gray-400">{label}</p>
            <div className="space-y-0.5">
              {items.map(({ label: itemLabel, href, icon: Icon }) => {
                const active = pathname === href || (href !== "/dashboard" && pathname.startsWith(href));
                return (
                  <Link
                    key={href}
                    href={href}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
                      active
                        ? "bg-brand-50 text-brand-700"
                        : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                    )}
                  >
                    <Icon className={cn("h-4 w-4 flex-shrink-0", active ? "text-brand-600" : "text-gray-400")} />
                    {itemLabel}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* User info + logout */}
      <div className="border-t border-gray-200 p-3 space-y-1">
        <div className="flex items-center gap-2.5 rounded-md px-2 py-2">
          <div className="h-7 w-7 rounded-full bg-brand-100 flex items-center justify-center text-xs font-semibold text-brand-700 flex-shrink-0">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-gray-900">{user?.name ?? "User"}</p>
            <p className="truncate text-xs text-gray-400">{user?.email ?? ""}</p>
          </div>
        </div>
        <button
          onClick={handleLogout}
          className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-xs text-gray-500 hover:bg-red-50 hover:text-red-600 transition-colors"
        >
          <LogOut className="h-3.5 w-3.5" />
          Sign out
        </button>
      </div>
    </aside>
  );
}
