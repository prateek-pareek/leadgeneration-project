"use client";

import { Bell, Search } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api/client";

async function fetchPendingCount(): Promise<number> {
  try {
    const { data } = await api.get<{ pending: number }>("/approvals/count");
    return data.pending;
  } catch {
    return 0;
  }
}

interface Props {
  title: string;
}

export function Topbar({ title }: Props) {
  const { data: pendingCount = 0 } = useQuery({
    queryKey: ["approvals", "count"],
    queryFn: fetchPendingCount,
    refetchInterval: 60_000,
  });

  return (
    <header className="flex h-14 items-center justify-between border-b border-gray-200 bg-white px-6">
      <h1 className="text-base font-semibold text-gray-900">{title}</h1>

      <div className="flex items-center gap-3">
        {/* Search trigger (placeholder) */}
        <button className="flex items-center gap-2 rounded-md border border-gray-200 px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-50">
          <Search className="h-4 w-4" />
          <span className="hidden sm:inline">Search...</span>
          <kbd className="hidden sm:inline rounded bg-gray-100 px-1.5 text-xs text-gray-400">⌘K</kbd>
        </button>

        {/* Approval queue bell */}
        <a href="/comments/approval" className="relative rounded-md p-1.5 text-gray-500 hover:bg-gray-100">
          <Bell className="h-5 w-5" />
          {pendingCount > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-xs font-bold text-white">
              {pendingCount > 9 ? "9+" : pendingCount}
            </span>
          )}
        </a>
      </div>
    </header>
  );
}
