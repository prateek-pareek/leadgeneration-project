"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, XCircle, Edit2, ExternalLink } from "lucide-react";
import { StatusPill } from "@/components/shared/StatusPill";
import { EmptyState } from "@/components/shared/EmptyState";
import { LeadScoreBadge } from "@/components/leads/LeadScoreBadge";
import api from "@/lib/api/client";
import type { Approval, CommentVariant } from "@/types";

async function fetchPendingApprovals(): Promise<Approval[]> {
  const { data } = await api.get<Approval[]>("/approvals", {
    params: { status: "pending", type: "comment_draft" },
  });
  return data;
}

async function approveComment(approvalId: string, variantText: string) {
  await api.post(`/approvals/${approvalId}/approve`, { selected_text: variantText });
}

async function rejectComment(approvalId: string, reason: string) {
  await api.post(`/approvals/${approvalId}/reject`, { reason });
}

export function CommentApprovalQueue() {
  const queryClient = useQueryClient();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  const { data: approvals = [], isLoading } = useQuery({
    queryKey: ["approvals", "pending", "comment_draft"],
    queryFn: fetchPendingApprovals,
    refetchInterval: 30_000,
  });

  const approveMutation = useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) => approveComment(id, text),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["approvals"] }),
  });

  const rejectMutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      rejectComment(id, reason),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["approvals"] }),
  });

  if (isLoading) {
    return <div className="space-y-4">{Array.from({ length: 3 }).map((_, i) => (
      <div key={i} className="h-40 rounded-lg bg-gray-100 animate-pulse" />
    ))}</div>;
  }

  if (approvals.length === 0) {
    return (
      <EmptyState
        title="No comments pending approval"
        description="When AI drafts a comment for a lead, it will appear here for your review."
      />
    );
  }

  return (
    <div className="space-y-4">
      {approvals.map((approval) => {
        const draft = approval.commentDraft;
        if (!draft) return null;

        return (
          <div
            key={approval.id}
            className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm"
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-4 mb-4">
              <div>
                <p className="text-sm font-medium text-gray-900">
                  {approval.lead?.author?.displayName ?? approval.lead?.author?.handle ?? "Unknown author"}
                </p>
                <p className="text-xs text-gray-500 mt-0.5">
                  {approval.lead?.post?.platform} ·{" "}
                  {approval.lead?.post?.postedAt
                    ? new Date(approval.lead.post.postedAt).toLocaleDateString()
                    : ""}
                </p>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                {approval.lead?.latestScore && (
                  <LeadScoreBadge
                    score={approval.lead.latestScore.score}
                    bucket={approval.lead.latestScore.bucket}
                  />
                )}
                <StatusPill status={approval.status} />
              </div>
            </div>

            {/* Original post preview */}
            {approval.lead?.post?.text && (
              <div className="mb-4 rounded bg-gray-50 px-3 py-2 text-xs text-gray-600 line-clamp-3 border-l-2 border-gray-300">
                {approval.lead.post.text}
              </div>
            )}

            {/* Comment variants */}
            <div className="space-y-3 mb-4">
              {draft.variants.map((variant) => (
                <CommentVariantCard
                  key={variant.type}
                  variant={variant}
                  isEditing={editingId === `${approval.id}-${variant.type}`}
                  editText={editText}
                  onEdit={() => {
                    setEditingId(`${approval.id}-${variant.type}`);
                    setEditText(variant.text);
                  }}
                  onEditChange={setEditText}
                  onApprove={(text) => approveMutation.mutate({ id: approval.id, text })}
                  onCancelEdit={() => setEditingId(null)}
                />
              ))}
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2 border-t pt-3">
              {approval.lead?.post?.url && (
                <a
                  href={approval.lead.post.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
                >
                  <ExternalLink className="h-3 w-3" />
                  View post
                </a>
              )}
              <button
                onClick={() => rejectMutation.mutate({ id: approval.id, reason: "Manually rejected" })}
                className="ml-auto inline-flex items-center gap-1 text-xs text-red-600 hover:text-red-700"
              >
                <XCircle className="h-4 w-4" />
                Reject all
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface VariantCardProps {
  variant: CommentVariant;
  isEditing: boolean;
  editText: string;
  onEdit: () => void;
  onEditChange: (text: string) => void;
  onApprove: (text: string) => void;
  onCancelEdit: () => void;
}

function CommentVariantCard({
  variant,
  isEditing,
  editText,
  onEdit,
  onEditChange,
  onApprove,
  onCancelEdit,
}: VariantCardProps) {
  const typeLabels: Record<string, string> = {
    concise: "Concise",
    insightful: "Insightful",
    peer: "Peer",
    founder_friendly: "Founder-Friendly",
  };

  return (
    <div className="rounded border border-gray-100 bg-gray-50 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
          {typeLabels[variant.type] ?? variant.type}
        </span>
        <span className="text-xs text-gray-400">{variant.tone}</span>
      </div>

      {isEditing ? (
        <div className="space-y-2">
          <textarea
            value={editText}
            onChange={(e) => onEditChange(e.target.value)}
            className="w-full text-sm text-gray-800 border border-gray-300 rounded p-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none resize-none"
            rows={3}
          />
          <div className="flex items-center gap-2">
            <button
              onClick={() => onApprove(editText)}
              className="inline-flex items-center gap-1 rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
            >
              <CheckCircle className="h-3 w-3" />
              Approve edited
            </button>
            <button
              onClick={onCancelEdit}
              className="text-xs text-gray-500 hover:text-gray-700"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div>
          <p className="text-sm text-gray-800 leading-relaxed">{variant.text}</p>
          <div className="mt-2 flex items-center gap-2">
            <button
              onClick={() => onApprove(variant.text)}
              className="inline-flex items-center gap-1 rounded bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700"
            >
              <CheckCircle className="h-3 w-3" />
              Use this
            </button>
            <button
              onClick={onEdit}
              className="inline-flex items-center gap-1 rounded border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100"
            >
              <Edit2 className="h-3 w-3" />
              Edit
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
