"use client";

import { useState } from "react";
import { Topbar } from "@/components/layout/Topbar";
import { useLeads } from "@/lib/hooks/useLeads";
import { LeadScoreBadge } from "@/components/leads/LeadScoreBadge";
import { StatusPill } from "@/components/shared/StatusPill";
import { EmptyState } from "@/components/shared/EmptyState";
import { Users, RefreshCw } from "lucide-react";
import { PIPELINE_STAGES } from "@/types";
import type { Lead } from "@/types";

const BUCKETS = ["", "hot", "warm", "cold", "ignore"] as const;

export default function LeadsPage() {
  const [stage, setStage] = useState("");
  const [bucket, setBucket] = useState("");
  const [q, setQ] = useState("");

  const { data, isLoading, refetch } = useLeads({ stage, bucket, q, limit: 100 });
  const leads = data?.data ?? [];

  return (
    <div>
      <Topbar title="Leads" />
      <div className="p-6 space-y-4">
        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search leads..."
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
          <select
            value={stage}
            onChange={(e) => setStage(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand-500"
          >
            <option value="">All stages</option>
            {PIPELINE_STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select
            value={bucket}
            onChange={(e) => setBucket(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand-500"
          >
            {BUCKETS.map((b) => <option key={b} value={b}>{b === "" ? "All buckets" : b.charAt(0).toUpperCase() + b.slice(1)}</option>)}
          </select>
          <button onClick={() => refetch()} className="rounded-md border border-gray-300 p-1.5 text-gray-500 hover:bg-gray-50">
            <RefreshCw className="h-4 w-4" />
          </button>
          <span className="ml-auto text-sm text-gray-500">{data?.total ?? 0} leads</span>
        </div>

        {/* Table */}
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="h-14 rounded-lg bg-gray-100 animate-pulse" />
            ))}
          </div>
        ) : leads.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No leads yet"
            description="Discover leads from Hacker News, Reddit, and other sources to get started."
            action={{ label: "Go to Discover", onClick: () => window.location.href = "/discover" }}
          />
        ) : (
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Author</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Source</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Stage</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Score</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Added</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {leads.map((lead) => (
                  <LeadRow key={lead.id} lead={lead} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function LeadRow({ lead }: { lead: Lead }) {
  return (
    <tr
      className="hover:bg-gray-50 cursor-pointer"
      onClick={() => window.location.href = `/leads/${lead.id}`}
    >
      <td className="px-4 py-3">
        <div>
          <p className="text-sm font-medium text-gray-900">
            {lead.author?.displayName ?? lead.author?.handle ?? "Unknown"}
          </p>
          {lead.author?.handle && (
            <p className="text-xs text-gray-500">@{lead.author.handle}</p>
          )}
        </div>
      </td>
      <td className="px-4 py-3">
        <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 capitalize">
          {lead.source}
        </span>
      </td>
      <td className="px-4 py-3">
        <StatusPill status={lead.pipelineStage.toLowerCase().replace(/ /g, "_")} size="sm" />
      </td>
      <td className="px-4 py-3">
        {lead.latestScore ? (
          <LeadScoreBadge score={lead.latestScore.score} bucket={lead.latestScore.bucket as any} />
        ) : (
          <span className="text-xs text-gray-400">Pending</span>
        )}
      </td>
      <td className="px-4 py-3 text-xs text-gray-500">
        {new Date(lead.createdAt).toLocaleDateString()}
      </td>
    </tr>
  );
}
