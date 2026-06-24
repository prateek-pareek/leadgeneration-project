"use client";

import { useQuery } from "@tanstack/react-query";
import { Topbar } from "@/components/layout/Topbar";
import { LeadScoreBadge } from "@/components/leads/LeadScoreBadge";
import { EmptyState } from "@/components/shared/EmptyState";
import { KanbanSquare } from "lucide-react";
import { PIPELINE_STAGES } from "@/types";
import type { Lead } from "@/types";
import api from "@/lib/api/client";

async function fetchPipeline(): Promise<Record<string, Lead[]>> {
  const { data } = await api.get("/crm/pipeline");
  return data;
}

const VISIBLE_STAGES = [
  "Discovered", "Researched", "Comment Posted",
  "Replied", "Email Sent", "Meeting Booked", "Won",
];

export default function CRMPage() {
  const { data: pipeline = {}, isLoading } = useQuery({
    queryKey: ["crm", "pipeline"],
    queryFn: fetchPipeline,
    refetchInterval: 60_000,
  });

  return (
    <div className="flex h-full flex-col">
      <Topbar title="CRM Pipeline" />
      <div className="flex-1 overflow-x-auto p-6">
        {isLoading ? (
          <div className="flex gap-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-96 w-60 flex-shrink-0 rounded-lg bg-gray-100 animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="flex gap-4 h-full">
            {VISIBLE_STAGES.map((stage) => {
              const leads = pipeline[stage] ?? [];
              return (
                <KanbanColumn key={stage} stage={stage} leads={leads} />
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function KanbanColumn({ stage, leads }: { stage: string; leads: Lead[] }) {
  const stageColors: Record<string, string> = {
    "Discovered":     "bg-gray-200 text-gray-700",
    "Researched":     "bg-blue-100 text-blue-700",
    "Comment Posted": "bg-indigo-100 text-indigo-700",
    "Replied":        "bg-purple-100 text-purple-700",
    "Email Sent":     "bg-amber-100 text-amber-700",
    "Meeting Booked": "bg-green-100 text-green-700",
    "Won":            "bg-emerald-100 text-emerald-700",
  };

  return (
    <div className="flex w-60 flex-shrink-0 flex-col rounded-lg border border-gray-200 bg-gray-50">
      {/* Column header */}
      <div className="flex items-center justify-between border-b border-gray-200 px-3 py-2.5">
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${stageColors[stage] ?? "bg-gray-100 text-gray-600"}`}>
          {stage}
        </span>
        <span className="text-xs text-gray-400">{leads.length}</span>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-y-auto space-y-2 p-2 scrollbar-thin">
        {leads.length === 0 ? (
          <div className="py-8 text-center text-xs text-gray-400">No leads</div>
        ) : (
          leads.map((lead) => <KanbanCard key={lead.id} lead={lead} />)
        )}
      </div>
    </div>
  );
}

function KanbanCard({ lead }: { lead: Lead }) {
  return (
    <a
      href={`/leads/${lead.id}`}
      className="block rounded-md border border-gray-200 bg-white p-3 shadow-sm hover:shadow-md transition-shadow"
    >
      <p className="text-sm font-medium text-gray-900 truncate">
        {lead.author?.displayName ?? lead.author?.handle ?? "Unknown"}
      </p>
      {lead.author?.handle && (
        <p className="text-xs text-gray-500 truncate mt-0.5">@{lead.author.handle}</p>
      )}
      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs text-gray-400 capitalize">{lead.source}</span>
        {lead.latestScore && (
          <LeadScoreBadge
            score={lead.latestScore.score}
            bucket={lead.latestScore.bucket as any}
            showLabel={false}
          />
        )}
      </div>
    </a>
  );
}
