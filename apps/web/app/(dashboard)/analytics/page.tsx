"use client";

import { useQuery } from "@tanstack/react-query";
import { Topbar } from "@/components/layout/Topbar";
import api from "@/lib/api/client";

async function fetchConversion() {
  const { data } = await api.get("/analytics/conversion");
  return data as { stage: string; count: number }[];
}

async function fetchSources() {
  const { data } = await api.get("/analytics/sources");
  return data as { source: string; count: number }[];
}

async function fetchComments() {
  const { data } = await api.get("/analytics/comments");
  return data as { pending: number; approved: number; posted: number; rejected: number };
}

export default function AnalyticsPage() {
  const { data: conversion = [] } = useQuery({ queryKey: ["analytics", "conversion"], queryFn: fetchConversion });
  const { data: sources = [] } = useQuery({ queryKey: ["analytics", "sources"], queryFn: fetchSources });
  const { data: comments } = useQuery({ queryKey: ["analytics", "comments"], queryFn: fetchComments });

  const maxConv = Math.max(...conversion.map((c) => c.count), 1);
  const maxSrc = Math.max(...sources.map((s) => s.count), 1);

  return (
    <div>
      <Topbar title="Analytics" />
      <div className="p-6 space-y-6 max-w-5xl">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">

          {/* Pipeline funnel */}
          <div className="lg:col-span-2 rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">Pipeline Funnel</h2>
            {conversion.length === 0 ? (
              <p className="text-sm text-gray-400">No data yet.</p>
            ) : (
              <div className="space-y-2">
                {conversion.map(({ stage, count }) => (
                  <div key={stage} className="flex items-center gap-3">
                    <span className="w-36 text-xs text-gray-600 truncate">{stage}</span>
                    <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                      <div
                        className="h-2 rounded-full bg-brand-500"
                        style={{ width: `${(count / maxConv) * 100}%` }}
                      />
                    </div>
                    <span className="w-6 text-right text-xs font-medium text-gray-900">{count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Comments breakdown */}
          <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">Comments</h2>
            {comments ? (
              <div className="space-y-3">
                {[
                  { label: "Pending review", value: comments.pending, color: "bg-amber-400" },
                  { label: "Approved", value: comments.approved, color: "bg-blue-400" },
                  { label: "Posted", value: comments.posted, color: "bg-green-500" },
                  { label: "Rejected", value: comments.rejected, color: "bg-red-400" },
                ].map(({ label, value, color }) => (
                  <div key={label} className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className={`h-2.5 w-2.5 rounded-full ${color}`} />
                      <span className="text-xs text-gray-600">{label}</span>
                    </div>
                    <span className="text-sm font-semibold text-gray-900">{value}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-400">Loading...</p>
            )}
          </div>
        </div>

        {/* Sources */}
        <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Leads by Source</h2>
          {sources.length === 0 ? (
            <p className="text-sm text-gray-400">No data yet.</p>
          ) : (
            <div className="space-y-2">
              {sources.map(({ source, count }) => (
                <div key={source} className="flex items-center gap-3">
                  <span className="w-28 text-xs text-gray-600 capitalize">{source}</span>
                  <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                    <div
                      className="h-2 rounded-full bg-indigo-400"
                      style={{ width: `${(count / maxSrc) * 100}%` }}
                    />
                  </div>
                  <span className="w-8 text-right text-xs font-medium text-gray-900">{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
