"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Topbar } from "@/components/layout/Topbar";
import { EmptyState } from "@/components/shared/EmptyState";
import { Radio, Plus, Play, Trash2, Clock, MapPin } from "lucide-react";
import api from "@/lib/api/client";

const SOURCE_TYPES = [
  { value: "hackernews",     label: "Hacker News",     icon: "🟠", desc: "Ask HN, Show HN, job posts" },
  { value: "reddit",         label: "Reddit",           icon: "🔴", desc: "Subreddit keyword search" },
  { value: "linkedin",       label: "LinkedIn",         icon: "🔵", desc: "Public posts via Google" },
  { value: "twitter",        label: "X / Twitter",      icon: "⬛", desc: "Public tweets via Nitter" },
  { value: "producthunt",    label: "Product Hunt",     icon: "🟡", desc: "Discussions & new launches" },
  { value: "devto",          label: "Dev.to",           icon: "⚫", desc: "Articles & discussions" },
  { value: "google_places",  label: "Google Places",    icon: "📍", desc: "Local businesses without websites" },
];

const DEFAULT_KEYWORDS: Record<string, string> = {
  hackernews:     "looking for developer, IT outsourcing, devops help, cloud migration",
  reddit:         "need IT help, managed services, hire developer, cloud setup",
  linkedin:       "IT support, devops team, cloud migration, legacy modernisation",
  twitter:        "IT outsourcing, need developer, cloud costs, devops help",
  producthunt:    "looking for developer, tech team, IT support",
  devto:          "hiring, team, startup, cloud",
  google_places:  "",
};

const PLACES_BUSINESS_TYPES = [
  { value: "restaurant",        label: "Restaurants" },
  { value: "beauty_salon",      label: "Beauty Salons" },
  { value: "lawyer",            label: "Law Firms" },
  { value: "accountant",        label: "Accountants" },
  { value: "dentist",           label: "Dentists" },
  { value: "doctor",            label: "Medical Clinics" },
  { value: "real_estate_agency",label: "Real Estate" },
  { value: "car_repair",        label: "Auto Repair" },
  { value: "plumber",           label: "Plumbers" },
  { value: "electrician",       label: "Electricians" },
  { value: "contractor",        label: "Contractors" },
  { value: "gym",               label: "Gyms & Fitness" },
  { value: "insurance_agency",  label: "Insurance" },
  { value: "clothing_store",    label: "Clothing Stores" },
  { value: "pharmacy",          label: "Pharmacies" },
];

async function fetchSources() {
  const { data } = await api.get("/sources");
  return data as any[];
}
async function createSource(body: any) {
  const { data } = await api.post("/sources", body);
  return data;
}
async function deleteSource(id: string) {
  await api.delete(`/sources/${id}`);
}
async function runSource(id: string) {
  await api.post(`/sources/${id}/run`);
}

const STATUS_COLOR: Record<string, string> = {
  active: "bg-green-100 text-green-700",
  paused: "bg-gray-100 text-gray-600",
  error:  "bg-red-100 text-red-700",
};

const DEFAULT_FORM = {
  name: "",
  type: "hackernews",
  keywords: DEFAULT_KEYWORDS["hackernews"],
  subreddit: "smallbusiness,entrepreneurs,startups",
  max_results: 20,
  schedule: "manual",
  // Google Places fields
  location: "",
  business_types: ["restaurant", "lawyer", "accountant"] as string[],
};

export default function SourcesPage() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(DEFAULT_FORM);
  const [runningId, setRunningId] = useState<string | null>(null);

  const { data: sources = [], isLoading } = useQuery({
    queryKey: ["sources"],
    queryFn: fetchSources,
  });

  const createMutation = useMutation({
    mutationFn: createSource,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sources"] });
      setShowForm(false);
      setForm(DEFAULT_FORM);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteSource,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sources"] }),
  });

  const runMutation = useMutation({
    mutationFn: runSource,
    onMutate: (id) => setRunningId(id),
    onSettled: () => setRunningId(null),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sources"] }),
  });

  function handleTypeChange(type: string) {
    setForm((f) => ({
      ...f,
      type,
      keywords: DEFAULT_KEYWORDS[type] ?? f.keywords,
      name: f.name || SOURCE_TYPES.find((t) => t.value === type)?.label || "",
    }));
  }

  function toggleBusinessType(value: string) {
    setForm((f) => ({
      ...f,
      business_types: f.business_types.includes(value)
        ? f.business_types.filter((t) => t !== value)
        : [...f.business_types, value],
    }));
  }

  function handleSubmit() {
    let config: any = { max_results: form.max_results };

    if (form.type === "google_places") {
      config.location = form.location.trim();
      config.business_types = form.business_types;
    } else {
      config.keywords = form.keywords.split(",").map((k) => k.trim()).filter(Boolean);
      if (form.type === "reddit") config.subreddit = form.subreddit;
    }

    createMutation.mutate({
      name: form.name,
      type: form.type,
      config,
      schedule: form.schedule,
      status: "active",
    });
  }

  const isPlaces = form.type === "google_places";
  const canSubmit = form.name && !createMutation.isPending &&
    (isPlaces ? form.location.trim().length > 0 && form.business_types.length > 0
               : form.keywords.length > 0);

  return (
    <div>
      <Topbar title="Sources" />
      <div className="p-6 max-w-4xl space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between">
          <p className="text-sm text-gray-500">
            Configure where ProspectOS discovers leads. Each source scans automatically or on demand.
          </p>
          <button
            onClick={() => setShowForm(!showForm)}
            className="inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700"
          >
            <Plus className="h-4 w-4" />
            Add source
          </button>
        </div>

        {/* Create form */}
        {showForm && (
          <div className="rounded-lg border border-brand-200 bg-brand-50 p-5 space-y-4">
            <h3 className="text-sm font-semibold text-gray-900">New source</h3>

            {/* Type picker */}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {SOURCE_TYPES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => handleTypeChange(t.value)}
                  className={`flex items-start gap-2 rounded-lg border p-3 text-left transition-all ${
                    form.type === t.value
                      ? "border-brand-500 bg-white shadow-sm"
                      : "border-gray-200 bg-white hover:border-gray-300"
                  }`}
                >
                  <span className="text-xl leading-none">{t.icon}</span>
                  <div>
                    <p className="text-xs font-semibold text-gray-900">{t.label}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{t.desc}</p>
                  </div>
                </button>
              ))}
            </div>

            {/* Google Places info banner */}
            {isPlaces && (
              <div className="rounded-md bg-blue-50 border border-blue-200 px-4 py-3 text-xs text-blue-700 space-y-1">
                <p className="font-semibold">📍 Google Places — finds businesses without websites</p>
                <p>Uses the official Google Maps API to find local businesses that have no website. These are prime IT services leads (web development, cloud setup, managed IT). Uses your GOOGLE_API_KEY from .env.</p>
                <p className="text-blue-500">Free tier: ~11,700 searches/month included in the $200 Google credit.</p>
              </div>
            )}

            {/* Name */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Source name</label>
              <input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder={isPlaces ? "e.g. Austin Local Businesses" : "e.g. LinkedIn IT Pain Points"}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
            </div>

            {/* Google Places: location + business types */}
            {isPlaces ? (
              <>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    Target location <span className="text-gray-400">(city, state or postcode)</span>
                  </label>
                  <div className="relative">
                    <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                    <input
                      value={form.location}
                      onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
                      placeholder="e.g. Austin, TX"
                      className="w-full rounded-md border border-gray-300 pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-brand-500"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-2">
                    Business categories to scan <span className="text-gray-400">(select all that apply)</span>
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {PLACES_BUSINESS_TYPES.map((bt) => (
                      <button
                        key={bt.value}
                        type="button"
                        onClick={() => toggleBusinessType(bt.value)}
                        className={`rounded-full px-3 py-1 text-xs font-medium border transition-all ${
                          form.business_types.includes(bt.value)
                            ? "bg-brand-600 text-white border-brand-600"
                            : "bg-white text-gray-600 border-gray-300 hover:border-brand-400"
                        }`}
                      >
                        {bt.label}
                      </button>
                    ))}
                  </div>
                  {form.business_types.length > 0 && (
                    <p className="text-xs text-gray-400 mt-2">{form.business_types.length} categories selected</p>
                  )}
                </div>
              </>
            ) : (
              <>
                {/* Keywords */}
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    Keywords <span className="text-gray-400">(comma-separated)</span>
                  </label>
                  <textarea
                    value={form.keywords}
                    onChange={(e) => setForm((f) => ({ ...f, keywords: e.target.value }))}
                    rows={2}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-brand-500 resize-none"
                  />
                </div>

                {/* Reddit subreddit */}
                {form.type === "reddit" && (
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Subreddits</label>
                    <input
                      value={form.subreddit}
                      onChange={(e) => setForm((f) => ({ ...f, subreddit: e.target.value }))}
                      placeholder="smallbusiness,startups"
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-brand-500"
                    />
                  </div>
                )}
              </>
            )}

            {/* Max results + schedule */}
            <div className="flex items-center gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Max results per scan</label>
                <select
                  value={form.max_results}
                  onChange={(e) => setForm((f) => ({ ...f, max_results: Number(e.target.value) }))}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-brand-500"
                >
                  {isPlaces
                    ? [10, 20, 30, 50].map((n) => <option key={n} value={n}>{n} businesses</option>)
                    : [10, 20, 30, 50].map((n) => <option key={n} value={n}>{n} posts</option>)
                  }
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Auto-scan</label>
                <select
                  value={form.schedule}
                  onChange={(e) => setForm((f) => ({ ...f, schedule: e.target.value }))}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-brand-500"
                >
                  <option value="manual">Manual only</option>
                  <option value="daily">Daily</option>
                  <option value="twice_daily">Twice daily</option>
                </select>
              </div>
            </div>

            <div className="flex gap-2 pt-1">
              <button
                onClick={handleSubmit}
                disabled={!canSubmit}
                className="rounded-md bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
              >
                {createMutation.isPending ? "Creating..." : "Create source"}
              </button>
              <button onClick={() => setShowForm(false)} className="text-sm text-gray-500 hover:text-gray-700">
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Sources list */}
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-24 rounded-lg bg-gray-100 animate-pulse" />
            ))}
          </div>
        ) : sources.length === 0 ? (
          <EmptyState
            icon={Radio}
            title="No sources yet"
            description="Add your first source to start discovering leads automatically."
            action={{ label: "Add source", onClick: () => setShowForm(true) }}
          />
        ) : (
          <div className="space-y-3">
            {sources.map((src: any) => {
              const typeInfo = SOURCE_TYPES.find((t) => t.value === src.type);
              const isGP = src.type === "google_places";
              const subtitle = isGP
                ? `📍 ${src.config?.location ?? "location not set"} · ${(src.config?.business_types ?? []).length} categories`
                : `${typeInfo?.label} · ${(src.config?.keywords ?? []).slice(0, 3).join(", ")}${(src.config?.keywords ?? []).length > 3 ? " …" : ""}`;

              return (
                <div key={src.id} className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="text-2xl">{typeInfo?.icon ?? "🔍"}</span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-semibold text-gray-900 truncate">{src.name}</p>
                          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLOR[src.status] ?? STATUS_COLOR.active}`}>
                            {src.status}
                          </span>
                        </div>
                        <p className="text-xs text-gray-500 mt-0.5 truncate">{subtitle}</p>
                        {src.lastRunAt && (
                          <p className="flex items-center gap-1 text-xs text-gray-400 mt-1">
                            <Clock className="h-3 w-3" />
                            Last run {new Date(src.lastRunAt).toLocaleString()}
                            {src.postsFound != null && ` · ${src.postsFound} ${isGP ? "businesses" : "posts"} found`}
                          </p>
                        )}
                        {src.lastError && (
                          <p className="text-xs text-red-500 mt-1 truncate">Error: {src.lastError}</p>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 flex-shrink-0">
                      <button
                        onClick={() => runMutation.mutate(src.id)}
                        disabled={runningId === src.id}
                        className="inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"
                        title="Run scan now"
                      >
                        <Play className={`h-3 w-3 ${runningId === src.id ? "animate-pulse" : ""}`} />
                        {runningId === src.id ? "Scanning…" : "Scan now"}
                      </button>
                      <button
                        onClick={() => {
                          if (confirm(`Delete source "${src.name}"?`)) deleteMutation.mutate(src.id);
                        }}
                        className="rounded-md border border-gray-200 p-1.5 text-gray-400 hover:border-red-300 hover:text-red-500"
                        title="Delete source"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
