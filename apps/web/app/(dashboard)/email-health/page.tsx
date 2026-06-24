"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Topbar } from "@/components/layout/Topbar";
import { EmptyState } from "@/components/shared/EmptyState";
import { Globe, Plus, RefreshCw, CheckCircle, XCircle, AlertTriangle } from "lucide-react";
import api from "@/lib/api/client";
import type { Domain, DomainCheck } from "@/types";

async function fetchDomains(): Promise<Domain[]> {
  const { data } = await api.get<Domain[]>("/email-health/domains");
  return data;
}

async function addDomain(domain: string): Promise<void> {
  await api.post("/email-health/domains", { domain });
}

async function runCheck(id: string): Promise<DomainCheck> {
  const { data } = await api.post<DomainCheck>(`/email-health/domains/${id}/check`);
  return data;
}

function HealthScore({ score }: { score: number | null }) {
  if (score === null) return <span className="text-xs text-gray-400">Not checked</span>;
  const color = score >= 75 ? "text-green-600" : score >= 50 ? "text-amber-600" : "text-red-600";
  return <span className={`text-2xl font-bold ${color}`}>{score}<span className="text-sm text-gray-400">/100</span></span>;
}

function CheckIcon({ value }: { value: boolean | null }) {
  if (value === null) return <span className="text-gray-300">—</span>;
  return value
    ? <CheckCircle className="h-4 w-4 text-green-500" />
    : <XCircle className="h-4 w-4 text-red-500" />;
}

export default function EmailHealthPage() {
  const queryClient = useQueryClient();
  const [newDomain, setNewDomain] = useState("");
  const [adding, setAdding] = useState(false);
  const [checkResults, setCheckResults] = useState<Record<string, any>>({});

  const { data: domains = [], isLoading } = useQuery({
    queryKey: ["email-health", "domains"],
    queryFn: fetchDomains,
  });

  const addMutation = useMutation({
    mutationFn: addDomain,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["email-health", "domains"] });
      setNewDomain("");
      setAdding(false);
    },
  });

  const checkMutation = useMutation({
    mutationFn: runCheck,
    onSuccess: (result, id) => {
      setCheckResults((prev) => ({ ...prev, [id]: result }));
      queryClient.invalidateQueries({ queryKey: ["email-health", "domains"] });
    },
  });

  return (
    <div>
      <Topbar title="Email Health" />
      <div className="p-6 space-y-6 max-w-4xl">
        {/* Add domain */}
        <div className="flex items-center gap-3">
          {adding ? (
            <>
              <input
                value={newDomain}
                onChange={(e) => setNewDomain(e.target.value)}
                placeholder="yourdomain.com"
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand-500"
                onKeyDown={(e) => e.key === "Enter" && addMutation.mutate(newDomain)}
              />
              <button
                onClick={() => addMutation.mutate(newDomain)}
                disabled={!newDomain || addMutation.isPending}
                className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
              >
                Add
              </button>
              <button onClick={() => setAdding(false)} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
            </>
          ) : (
            <button
              onClick={() => setAdding(true)}
              className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              <Plus className="h-4 w-4" />
              Add domain
            </button>
          )}
        </div>

        {/* Domain cards */}
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 2 }).map((_, i) => (
              <div key={i} className="h-32 rounded-lg bg-gray-100 animate-pulse" />
            ))}
          </div>
        ) : domains.length === 0 ? (
          <EmptyState
            icon={Globe}
            title="No domains monitored"
            description="Add your sending domain to monitor SPF, DKIM, DMARC, and blacklist status."
            action={{ label: "Add domain", onClick: () => setAdding(true) }}
          />
        ) : (
          <div className="space-y-4">
            {domains.map((domain) => {
              const result = checkResults[domain.id];
              return (
                <div key={domain.id} className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="font-semibold text-gray-900">{domain.domain}</p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {domain.lastCheckedAt
                          ? `Last checked ${new Date(domain.lastCheckedAt).toLocaleDateString()}`
                          : "Never checked"}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <HealthScore score={result?.health_score ?? domain.healthScore ?? null} />
                      <button
                        onClick={() => checkMutation.mutate(domain.id)}
                        disabled={checkMutation.isPending}
                        className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                      >
                        <RefreshCw className={`h-3 w-3 ${checkMutation.isPending ? "animate-spin" : ""}`} />
                        Check now
                      </button>
                    </div>
                  </div>

                  {result && (
                    <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                      {[
                        { label: "SPF", value: result.spf_valid },
                        { label: "DKIM", value: result.dkim_valid },
                        { label: "DMARC", value: result.dmarc_valid },
                        { label: "Blacklists", value: result.blacklist_clean },
                      ].map(({ label, value }) => (
                        <div key={label} className="flex items-center gap-2 rounded-md bg-gray-50 px-3 py-2">
                          <CheckIcon value={value} />
                          <span className="text-sm font-medium text-gray-700">{label}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {result?.blacklists_hit?.length > 0 && (
                    <div className="mt-3 flex items-start gap-2 rounded-md bg-red-50 p-3 text-sm text-red-700">
                      <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                      <span>Listed on: {result.blacklists_hit.join(", ")}</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
