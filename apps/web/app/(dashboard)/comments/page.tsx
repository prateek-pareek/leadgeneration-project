"use client";

import { useQuery } from "@tanstack/react-query";
import { Topbar } from "@/components/layout/Topbar";
import { StatusPill } from "@/components/shared/StatusPill";
import { EmptyState } from "@/components/shared/EmptyState";
import { MessageSquare, ArrowRight } from "lucide-react";
import Link from "next/link";
import api from "@/lib/api/client";

async function fetchDrafts() {
  const { data } = await api.get("/comment-drafts", { params: { limit: 50 } });
  return data as any[];
}
async function fetchApprovalCount() {
  const { data } = await api.get("/approvals/count");
  return (data as any).count as number;
}

export default function CommentsPage() {
  const { data: drafts = [], isLoading } = useQuery({
    queryKey: ["comment-drafts"],
    queryFn: fetchDrafts,
    refetchInterval: 30_000,
  });
  const { data: pendingCount = 0 } = useQuery({
    queryKey: ["approvals", "count"],
    queryFn: fetchApprovalCount,
    refetchInterval: 30_000,
  });

  const byStatus = drafts.reduce<Record<string, number>>((acc, d) => {
    acc[d.status] = (acc[d.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <Topbar title="Comments" />
      <div className="p-6 max-w-4xl space-y-6">

        {/* Approval CTA */}
        {pendingCount > 0 && (
          <Link
            href="/comments/approval"
            className="flex items-center justify-between rounded-lg border border-amber-300 bg-amber-50 px-5 py-4 hover:bg-amber-100 transition-colors"
          >
            <div>
              <p className="text-sm font-semibold text-amber-800">
                {pendingCount} comment{pendingCount !== 1 ? "s" : ""} waiting for your approval
              </p>
              <p className="text-xs text-amber-700 mt-0.5">Review, edit, and approve before posting.</p>
            </div>
            <ArrowRight className="h-5 w-5 text-amber-700 flex-shrink-0" />
          </Link>
        )}

        {/* Summary cards */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            { label: "Pending",  key: "pending_approval", color: "text-amber-600 bg-amber-50"  },
            { label: "Approved", key: "approved",          color: "text-blue-600 bg-blue-50"    },
            { label: "Posted",   key: "posted",            color: "text-green-600 bg-green-50"  },
            { label: "Rejected", key: "rejected",          color: "text-red-600 bg-red-50"      },
          ].map(({ label, key, color }) => (
            <div key={key} className={`rounded-lg p-4 ${color}`}>
              <p className="text-2xl font-bold">{byStatus[key] ?? 0}</p>
              <p className="text-xs font-medium mt-1">{label}</p>
            </div>
          ))}
        </div>

        {/* Recent drafts */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-900">Recent drafts</h2>
            <Link href="/comments/approval" className="text-xs text-brand-600 hover:underline">
              Open approval queue →
            </Link>
          </div>

          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-16 rounded-lg bg-gray-100 animate-pulse" />
              ))}
            </div>
          ) : drafts.length === 0 ? (
            <EmptyState
              icon={MessageSquare}
              title="No comment drafts yet"
              description="Once leads are scored and qualify, AI will draft comments for your review."
            />
          ) : (
            <div className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white shadow-sm overflow-hidden">
              {drafts.slice(0, 20).map((draft: any) => {
                const variants = (() => {
                  try {
                    return typeof draft.variants === "string"
                      ? JSON.parse(draft.variants)
                      : draft.variants;
                  } catch { return []; }
                })();
                const preview = variants?.[0]?.text ?? "—";
                return (
                  <div key={draft.id} className="flex items-start gap-4 px-4 py-3 hover:bg-gray-50">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-700 truncate">{preview}</p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {new Date(draft.created_at).toLocaleDateString()}
                      </p>
                    </div>
                    <StatusPill status={draft.status} />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
