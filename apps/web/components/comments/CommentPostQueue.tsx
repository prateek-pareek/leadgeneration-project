"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, Copy, ExternalLink, ClipboardCheck, Sparkles, Puzzle } from "lucide-react";
import api from "@/lib/api/client";
import { EmptyState } from "@/components/shared/EmptyState";
import {
  assistOpenPost,
  detectExtension,
  isExtensionInstalled,
} from "@/lib/extension/commentAssist";

const PLATFORM_NOTES: Record<string, string> = {
  linkedin: "Extension fills the LinkedIn comment box — you review and click Post.",
  threads: "Extension fills the reply box on Threads — you submit manually.",
  twitter: "Extension fills the reply on X — you submit manually.",
  x: "Extension fills the reply on X — you submit manually.",
  reddit: "Extension fills Reddit comment box, or auto-posts if OAuth is configured.",
  devto: "Extension fills Dev.to comment box, or auto-posts if API key is set.",
  hackernews: "Extension fills the HN reply textarea.",
};

function parseJsonField<T>(value: unknown, fallback: T): T {
  if (!value) return fallback;
  if (typeof value === "string") {
    try {
      return JSON.parse(value) as T;
    } catch {
      return fallback;
    }
  }
  return value as T;
}

async function fetchReadyDrafts() {
  const { data } = await api.get("/comment-drafts", { params: { status: "approved" } });
  return data as any[];
}

async function markPosted(draftId: string, postedUrl?: string) {
  await api.post(`/comment-drafts/${draftId}/mark-posted`, { posted_url: postedUrl ?? "" });
}

export function CommentPostQueue() {
  const queryClient = useQueryClient();
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [assistingId, setAssistingId] = useState<string | null>(null);
  const [extensionReady, setExtensionReady] = useState(isExtensionInstalled());

  useEffect(() => {
    detectExtension().then(setExtensionReady);
  }, []);

  const { data: drafts = [], isLoading } = useQuery({
    queryKey: ["comment-drafts", "approved"],
    queryFn: fetchReadyDrafts,
    refetchInterval: 30_000,
  });

  const postedMutation = useMutation({
    mutationFn: ({ id, url }: { id: string; url?: string }) => markPosted(id, url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["comment-drafts"] });
      queryClient.invalidateQueries({ queryKey: ["leads"] });
    },
  });

  async function copyComment(id: string, text: string) {
    await navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }

  async function handleAssistPost(draft: any, commentText: string) {
    const platform = (draft.platform ?? "manual").toLowerCase();
    setAssistingId(draft.id);
    try {
      const result = await assistOpenPost({
        text: commentText,
        postUrl: draft.post_url ?? "",
        platform,
        draftId: draft.id,
      });
      if (result.extensionUsed) {
        setCopiedId(draft.id);
        setTimeout(() => setCopiedId(null), 2500);
      }
    } finally {
      setAssistingId(null);
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="h-32 rounded-lg bg-gray-100 animate-pulse" />
        ))}
      </div>
    );
  }

  if (drafts.length === 0) {
    return (
      <EmptyState
        title="No comments ready to post"
        description="Approved comments appear here with one-click copy and extension assist."
      />
    );
  }

  return (
    <div className="space-y-4">
      {!extensionReady && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800 flex items-start gap-2">
          <Puzzle className="h-4 w-4 flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold">Install Comment Assist extension</p>
            <p className="mt-0.5">
              Load <code className="bg-amber-100 px-1 rounded">apps/extension</code> in Chrome
              (chrome://extensions → Developer mode → Load unpacked) for auto-fill on LinkedIn & Threads.
            </p>
          </div>
        </div>
      )}

      {drafts.map((draft) => {
        const selected = parseJsonField<{ text?: string }>(draft.selected_variant, {});
        const commentText = selected.text ?? "";
        const platform = (draft.platform ?? "manual").toLowerCase();
        const note = PLATFORM_NOTES[platform] ?? "Open the post and paste your comment.";

        return (
          <div key={draft.id} className="rounded-lg border border-blue-200 bg-blue-50/50 p-5 shadow-sm">
            <div className="flex items-start justify-between gap-3 mb-3">
              <div>
                <p className="text-sm font-semibold text-gray-900 capitalize">
                  {platform} · Ready to post
                </p>
                <p className="text-xs text-gray-500 mt-0.5">{note}</p>
              </div>
              {draft.post_url && (
                <a
                  href={draft.post_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 rounded-md bg-white border border-gray-300 px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 flex-shrink-0"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  Open post
                </a>
              )}
            </div>

            {draft.post_text && (
              <div className="mb-3 rounded bg-white px-3 py-2 text-xs text-gray-500 line-clamp-2 border-l-2 border-gray-300">
                {draft.post_text}
              </div>
            )}

            <div className="rounded-md bg-white border border-blue-100 p-3 mb-3">
              <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">{commentText}</p>
            </div>

            <div className="flex flex-wrap gap-2">
              {draft.post_url && (
                <button
                  onClick={() => handleAssistPost(draft, commentText)}
                  disabled={assistingId === draft.id}
                  className="inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  {assistingId === draft.id
                    ? "Opening…"
                    : extensionReady
                    ? "Assist post"
                    : "Copy & open post"}
                </button>
              )}
              <button
                onClick={() => copyComment(draft.id, commentText)}
                className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
              >
                {copiedId === draft.id ? (
                  <>
                    <ClipboardCheck className="h-3.5 w-3.5" />
                    Copied!
                  </>
                ) : (
                  <>
                    <Copy className="h-3.5 w-3.5" />
                    Copy only
                  </>
                )}
              </button>
              <button
                onClick={() => postedMutation.mutate({ id: draft.id, url: draft.post_url })}
                disabled={postedMutation.isPending}
                className="inline-flex items-center gap-1.5 rounded-md border border-green-300 bg-green-50 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-100 ml-auto"
              >
                <CheckCircle className="h-3.5 w-3.5" />
                Mark as posted
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
