"use client";

import { useQuery } from "@tanstack/react-query";
import { Topbar } from "@/components/layout/Topbar";
import { EmptyState } from "@/components/shared/EmptyState";
import { ShieldCheck } from "lucide-react";
import api from "@/lib/api/client";

async function fetchAuditLog() {
  const { data } = await api.get("/audit-log");
  return data as any[];
}

const EVENT_COLOR: Record<string, string> = {
  "comment.approved":          "bg-green-100 text-green-700",
  "comment.rejected":          "bg-red-100 text-red-700",
  "comment.posted":            "bg-blue-100 text-blue-700",
  "comment.generate_requested":"bg-indigo-100 text-indigo-700",
  "lead.created":              "bg-gray-100 text-gray-600",
  "lead.deleted":              "bg-red-100 text-red-600",
  "lead.suppressed":           "bg-orange-100 text-orange-700",
  "lead.stage_advanced":       "bg-teal-100 text-teal-700",
  "auth.login":                "bg-gray-100 text-gray-500",
  "auth.logout":               "bg-gray-100 text-gray-500",
};

export default function AuditLogPage() {
  const { data: events = [], isLoading, refetch } = useQuery({
    queryKey: ["audit-log"],
    queryFn: fetchAuditLog,
    refetchInterval: 60_000,
  });

  return (
    <div>
      <Topbar title="Audit Log" />
      <div className="p-6 max-w-4xl space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-sm text-gray-500">
            Append-only record of every action taken in ProspectOS. All approvals and AI-generated content are logged here.
          </p>
          <button
            onClick={() => refetch()}
            className="text-xs text-gray-500 hover:text-gray-700 underline"
          >
            Refresh
          </button>
        </div>

        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} className="h-12 rounded-lg bg-gray-100 animate-pulse" />
            ))}
          </div>
        ) : events.length === 0 ? (
          <EmptyState
            icon={ShieldCheck}
            title="No audit events yet"
            description="Actions like approving comments, advancing leads, and logins will appear here."
          />
        ) : (
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
            <table className="min-w-full divide-y divide-gray-100">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Event</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Resource</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Actor</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {events.map((event: any) => (
                  <tr key={event.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${EVENT_COLOR[event.event_type] ?? "bg-gray-100 text-gray-600"}`}>
                        {event.event_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-700">
                      {event.resource_type && (
                        <span className="capitalize">{event.resource_type}</span>
                      )}
                      {event.resource_id && (
                        <span className="ml-1 font-mono text-gray-400 text-[10px]">{event.resource_id.slice(0, 8)}…</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600">
                      {event.actor_name ?? event.actor_id?.slice(0, 8) ?? "system"}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400 whitespace-nowrap">
                      {event.created_at
                        ? new Date(event.created_at).toLocaleString()
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
