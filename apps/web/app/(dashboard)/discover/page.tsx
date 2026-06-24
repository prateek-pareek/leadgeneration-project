"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Topbar } from "@/components/layout/Topbar";
import { EmptyState } from "@/components/shared/EmptyState";
import { Search, Play, ExternalLink, Clock } from "lucide-react";
import api from "@/lib/api/client";

async function fetchSources() {
  const { data } = await api.get("/sources");
  return data as any[];
}

async function fetchRecentPosts() {
  const { data } = await api.get("/posts", { params: { limit: 50 } });
  return (data as any).data as any[];
}

async function runSource(id: string) {
  await api.post(`/sources/${id}/run`);
}

async function importUrl(url: string, text: string) {
  await api.post("/posts", { url, text, platform: "manual" });
}

export default function DiscoverPage() {
  const queryClient = useQueryClient();
  const [importUrl_, setImportUrl_] = useState("");
  const [importText, setImportText] = useState("");
  const [showImport, setShowImport] = useState(false);

  const { data: sources = [] } = useQuery({ queryKey: ["sources"], queryFn: fetchSources });
  const { data: posts = [], isLoading } = useQuery({ queryKey: ["posts"], queryFn: fetchRecentPosts, refetchInterval: 30_000 });

  const runMutation = useMutation({
    mutationFn: runSource,
    onSuccess: () => {
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ["posts"] }), 3000);
    },
  });

  const importMutation = useMutation({
    mutationFn: () => importUrl(importUrl_, importText),
    onSuccess: () => {
      setImportUrl_("");
      setImportText("");
      setShowImport(false);
      queryClient.invalidateQueries({ queryKey: ["posts"] });
    },
  });

  return (
    <div>
      <Topbar title="Discover" />
      <div className="p-6 space-y-6">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">

          {/* Sources panel */}
          <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-900 mb-3">Sources</h2>
            {sources.length === 0 ? (
              <p className="text-sm text-gray-400">No sources configured.</p>
            ) : (
              <div className="space-y-2">
                {sources.map((src: any) => (
                  <div key={src.id} className="flex items-center justify-between rounded-md border border-gray-100 p-2.5">
                    <div>
                      <p className="text-sm font-medium text-gray-900">{src.name}</p>
                      <p className="text-xs text-gray-400 capitalize">{src.type}</p>
                    </div>
                    <button
                      onClick={() => runMutation.mutate(src.id)}
                      disabled={runMutation.isPending}
                      className="rounded-md bg-brand-600 p-1.5 text-white hover:bg-brand-700 disabled:opacity-50"
                      title="Run scan"
                    >
                      <Play className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Manual import */}
            <div className="mt-4 border-t border-gray-100 pt-4">
              {showImport ? (
                <div className="space-y-2">
                  <input
                    value={importUrl_}
                    onChange={(e) => setImportUrl_(e.target.value)}
                    placeholder="https://..."
                    className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-brand-500"
                  />
                  <textarea
                    value={importText}
                    onChange={(e) => setImportText(e.target.value)}
                    placeholder="Paste the post text here..."
                    rows={3}
                    className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-brand-500 resize-none"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={() => importMutation.mutate()}
                      disabled={!importUrl_ || !importText || importMutation.isPending}
                      className="rounded-md bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"
                    >
                      Import
                    </button>
                    <button onClick={() => setShowImport(false)} className="text-xs text-gray-500">Cancel</button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setShowImport(true)}
                  className="w-full rounded-md border border-dashed border-gray-300 py-2 text-xs text-gray-500 hover:border-brand-400 hover:text-brand-600"
                >
                  + Manual import URL
                </button>
              )}
            </div>
          </div>

          {/* Discovered posts */}
          <div className="lg:col-span-2 space-y-3">
            <h2 className="text-sm font-semibold text-gray-900">Recent Discoveries</h2>
            {isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="h-24 rounded-lg bg-gray-100 animate-pulse" />
                ))}
              </div>
            ) : posts.length === 0 ? (
              <EmptyState
                icon={Search}
                title="No posts discovered yet"
                description="Run a source scan or import a URL manually to get started."
              />
            ) : (
              posts.map((post: any) => (
                <div key={post.id} className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 capitalize">
                          {post.platform}
                        </span>
                        {post.author_handle && (
                          <span className="text-xs text-gray-500">@{post.author_handle}</span>
                        )}
                        {post.posted_at && (
                          <span className="flex items-center gap-1 text-xs text-gray-400">
                            <Clock className="h-3 w-3" />
                            {new Date(post.posted_at).toLocaleDateString()}
                          </span>
                        )}
                      </div>
                      {post.title && (
                        <p className="text-sm font-medium text-gray-900 mb-1">{post.title}</p>
                      )}
                      <p className="text-sm text-gray-600 line-clamp-2">{post.text}</p>
                    </div>
                    <div className="flex-shrink-0 flex items-center gap-2">
                      {post.is_processed ? (
                        <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">Processed</span>
                      ) : (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">Pending</span>
                      )}
                      <a href={post.url} target="_blank" rel="noopener noreferrer"
                        className="text-gray-400 hover:text-gray-600">
                        <ExternalLink className="h-4 w-4" />
                      </a>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
