"use client";

import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Topbar } from "@/components/layout/Topbar";
import { LeadScoreBadge } from "@/components/leads/LeadScoreBadge";
import { ArrowLeft, ExternalLink, ChevronRight } from "lucide-react";
import api from "@/lib/api/client";
import type { Lead, ResearchBrief } from "@/types";
import Link from "next/link";

async function fetchLead(id: string) {
  const { data } = await api.get<Lead>(`/leads/${id}`);
  return data;
}
async function fetchResearch(id: string) {
  const { data } = await api.get<ResearchBrief[]>(`/leads/${id}/research`);
  return data?.[0] ?? null;
}
async function fetchScore(id: string) {
  const { data } = await api.get(`/scores/${id}/latest`);
  return data;
}
async function fetchActivity(id: string) {
  const { data } = await api.get(`/leads/${id}/activity`);
  return data as any[];
}

export default function LeadDetailPage() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const { data: lead } = useQuery({ queryKey: ["leads", id], queryFn: () => fetchLead(id) });
  const { data: research } = useQuery({ queryKey: ["research", id], queryFn: () => fetchResearch(id) });
  const { data: score } = useQuery({ queryKey: ["score", id], queryFn: () => fetchScore(id) });
  const { data: activity = [] } = useQuery({ queryKey: ["activity", id], queryFn: () => fetchActivity(id) });

  const advanceMutation = useMutation({
    mutationFn: () => api.post(`/leads/${id}/advance`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["leads", id] }),
  });

  const generateCommentMutation = useMutation({
    mutationFn: () => api.post("/comment-drafts/generate", { lead_id: id }),
  });

  if (!lead) {
    return (
      <div>
        <Topbar title="Lead" />
        <div className="p-6">
          <div className="h-64 rounded-lg bg-gray-100 animate-pulse" />
        </div>
      </div>
    );
  }

  return (
    <div>
      <Topbar title={lead.author?.displayName ?? lead.author?.handle ?? "Lead"} />
      <div className="p-6 max-w-4xl space-y-6">

        {/* Back + header */}
        <div>
          <Link href="/leads" className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 mb-3">
            <ArrowLeft className="h-4 w-4" />
            Back to leads
          </Link>

          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-xl font-bold text-gray-900">
                {lead.author?.displayName ?? lead.author?.handle ?? "Unknown"}
              </h2>
              {lead.author?.handle && (
                <p className="text-sm text-gray-500 mt-0.5">
                  @{lead.author.handle}
                  {lead.author.platform && <span className="ml-1 capitalize">· {lead.author.platform}</span>}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              {score && <LeadScoreBadge score={score.score} bucket={score.bucket} />}
              <span className="text-sm text-gray-500 capitalize bg-gray-100 rounded-full px-2.5 py-0.5">
                {lead.pipelineStage}
              </span>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => advanceMutation.mutate()}
            disabled={advanceMutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            Advance stage
            <ChevronRight className="h-4 w-4" />
          </button>
          <button
            onClick={() => generateCommentMutation.mutate()}
            disabled={generateCommentMutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            {generateCommentMutation.isPending ? "Generating..." : "Generate comment"}
          </button>
          {generateCommentMutation.isSuccess && (
            <Link href="/comments/approval" className="text-sm text-brand-600 hover:underline self-center">
              → Review in approval queue
            </Link>
          )}
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Research brief */}
          <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Research Brief</h3>
            {research ? (
              <div className="space-y-3 text-sm">
                <p className="text-gray-700 leading-relaxed">{research.briefText}</p>
                {research.painPoints.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Pain points</p>
                    <ul className="list-disc list-inside space-y-0.5 text-gray-600">
                      {research.painPoints.map((p, i) => <li key={i}>{p}</li>)}
                    </ul>
                  </div>
                )}
                {research.serviceFit.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Service fit</p>
                    <div className="flex flex-wrap gap-1.5">
                      {research.serviceFit.map((s, i) => (
                        <span key={i} className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">{s}</span>
                      ))}
                    </div>
                  </div>
                )}
                {research.engagementAngle && (
                  <div>
                    <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Best angle</p>
                    <p className="text-gray-700 italic">"{research.engagementAngle}"</p>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-gray-400">Research in progress or not available yet.</p>
            )}
          </div>

          {/* Score breakdown */}
          <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Lead Score</h3>
            {score ? (
              <div className="space-y-3">
                <p className="text-sm text-gray-600">{score.explanation}</p>
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">Top signals</p>
                  <ul className="space-y-1">
                    {(score.topSignals ?? score.top_signals ?? []).map((signal: string, i: number) => (
                      <li key={i} className="flex items-center gap-2 text-sm text-gray-700">
                        <span className="h-1.5 w-1.5 rounded-full bg-brand-500 flex-shrink-0" />
                        {signal}
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="rounded-md bg-gray-50 px-3 py-2 text-sm">
                  <span className="font-medium text-gray-700">Next action: </span>
                  <span className="text-gray-600 capitalize">{(score.recommendedAction ?? score.recommended_action ?? "").replace(/_/g, " ")}</span>
                </div>
              </div>
            ) : (
              <p className="text-sm text-gray-400">Score pending.</p>
            )}
          </div>
        </div>

        {/* Original post */}
        {lead.postId && (
          <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-gray-900 mb-2">Original Post</h3>
            <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
              {(lead as any).post?.text ?? "Post text not available."}
            </p>
            {(lead as any).post?.url && (
              <a
                href={(lead as any).post.url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-2 inline-flex items-center gap-1 text-xs text-brand-600 hover:underline"
              >
                <ExternalLink className="h-3 w-3" />
                View original post
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
