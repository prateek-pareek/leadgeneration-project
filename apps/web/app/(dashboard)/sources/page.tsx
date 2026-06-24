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
  { value: "threads",        label: "Threads",          icon: "🧵", desc: "Public posts via Google" },
  { value: "twitter",        label: "X / Twitter",      icon: "⬛", desc: "Public tweets via Nitter" },
  { value: "producthunt",    label: "Product Hunt",     icon: "🟡", desc: "Discussions & new launches" },
  { value: "devto",          label: "Dev.to",           icon: "⚫", desc: "Articles & discussions" },
  { value: "github",         label: "GitHub",           icon: "🐙", desc: "Help-wanted issues & hiring posts" },
  { value: "indiehackers",   label: "Indie Hackers",    icon: "🚀", desc: "Founder posts via Google — no login" },
  { value: "job_portals",    label: "Job Portals",      icon: "💼", desc: "RemoteOK, Jobicy, Himalayas, WWR — no login" },
  { value: "freelance_marketplaces", label: "Freelance", icon: "🤝", desc: "Freelancer API + Upwork/Guru via Google — no login" },
  { value: "google_places",  label: "Google Places",    icon: "📍", desc: "Local businesses without websites" },
];

const DEFAULT_KEYWORDS: Record<string, string> = {
  hackernews:     "looking for developer, IT outsourcing, devops help, cloud migration",
  reddit:         "need IT help, managed services, hire developer, cloud setup",
  linkedin:       "IT support, devops team, cloud migration, legacy modernisation",
  threads:        "need developer, IT help, startup tech, cloud costs, hiring",
  twitter:        "IT outsourcing, need developer, cloud costs, devops help",
  producthunt:    "looking for developer, tech team, IT support",
  devto:          "hiring, team, startup, cloud",
  github:         "looking for developer, need developer, hire developer, contractor, mvp, help wanted",
  indiehackers:   "need developer, outsource, mvp, saas, technical cofounder, hiring",
  job_portals:    "web development, full stack, react, node, python, devops, cloud engineer, mobile app",
  freelance_marketplaces: "software development, web development, devops, cloud migration, mobile app, API development, mvp",
  google_places:  "",
};

const JOB_PORTALS = [
  { value: "remoteok",        label: "RemoteOK",         auth: "api" as const },
  { value: "remotive",        label: "Remotive",         auth: "api" as const },
  { value: "arbeitnow",       label: "Arbeitnow",        auth: "api" as const },
  { value: "jobicy",          label: "Jobicy",           auth: "api" as const },
  { value: "workingnomads",   label: "Working Nomads",   auth: "api" as const },
  { value: "himalayas",       label: "Himalayas",        auth: "api" as const },
  { value: "weworkremotely",  label: "We Work Remotely", auth: "rss" as const },
];

const FREELANCE_MARKETPLACES = [
  { value: "freelancer",      label: "Freelancer.com",   auth: "api" as const },
  { value: "upwork",          label: "Upwork",           auth: "snippet" as const },
  { value: "guru",            label: "Guru",             auth: "snippet" as const },
  { value: "fiverr",          label: "Fiverr Community", auth: "snippet" as const },
  { value: "peopleperhour",   label: "PeoplePerHour",    auth: "snippet" as const },
  { value: "contra",          label: "Contra",           auth: "snippet" as const },
];

const AUTH_BADGE: Record<string, { label: string; className: string }> = {
  api:     { label: "No login · API", className: "bg-green-50 text-green-700 border-green-200" },
  rss:     { label: "No login · RSS", className: "bg-green-50 text-green-700 border-green-200" },
  snippet: { label: "No login · Google", className: "bg-blue-50 text-blue-700 border-blue-200" },
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
  job_portals: ["remoteok", "remotive", "jobicy", "himalayas"] as string[],
  freelance_portals: ["freelancer", "upwork", "guru"] as string[],
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

  function toggleJobPortal(value: string) {
    setForm((f) => ({
      ...f,
      job_portals: f.job_portals.includes(value)
        ? f.job_portals.filter((p) => p !== value)
        : [...f.job_portals, value],
    }));
  }

  function toggleFreelancePortal(value: string) {
    setForm((f) => ({
      ...f,
      freelance_portals: f.freelance_portals.includes(value)
        ? f.freelance_portals.filter((p) => p !== value)
        : [...f.freelance_portals, value],
    }));
  }

  function handleSubmit() {
    let config: any = { max_results: form.max_results };

    if (form.type === "google_places") {
      config.location = form.location.trim();
      config.business_types = form.business_types;
    } else if (form.type === "job_portals") {
      config.keywords = form.keywords.split(",").map((k) => k.trim()).filter(Boolean);
      config.portals = form.job_portals;
    } else if (form.type === "freelance_marketplaces") {
      config.keywords = form.keywords.split(",").map((k) => k.trim()).filter(Boolean);
      config.portals = form.freelance_portals;
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
  const isJobPortals = form.type === "job_portals";
  const isFreelance = form.type === "freelance_marketplaces";
  const canSubmit = form.name && !createMutation.isPending &&
    (isPlaces ? form.location.trim().length > 0 && form.business_types.length > 0
      : isJobPortals ? form.keywords.length > 0 && form.job_portals.length > 0
      : isFreelance ? form.keywords.length > 0 && form.freelance_portals.length > 0
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

            {isFreelance && (
              <div className="rounded-md bg-emerald-50 border border-emerald-200 px-4 py-3 text-xs text-emerald-800 space-y-1">
                <p className="font-semibold">🤝 Freelance marketplaces — software dev clients posting projects</p>
                <p>Freelancer.com uses the official public API (safest). Upwork, Guru, Fiverr, and PeoplePerHour use Google snippets only — no account login, no ban risk.</p>
                <p className="text-emerald-600">We never log into your Upwork/LinkedIn accounts by default.</p>
              </div>
            )}

            {/* Platform safety warnings */}
            {(form.type === "linkedin" || form.type === "threads" || form.type === "twitter" || form.type === "indiehackers" || form.type === "freelance_marketplaces" || form.type === "job_portals" || form.type === "reddit" || form.type === "github") && (
              <div className="rounded-md bg-amber-50 border border-amber-200 px-4 py-3 text-xs text-amber-800 space-y-1">
                <p className="font-semibold">🛡️ Strict scraping safety (SCRAPING_STRICT_MODE=true)</p>
                <ul className="list-disc list-inside space-y-0.5 text-amber-700">
                  <li>Google snippets first — zero direct hits on LinkedIn/Upwork when possible</li>
                  <li>Rate limits ~45% lower + longer delays between requests</li>
                  <li>Scan cooldowns: LinkedIn 2h · Threads 1h · Job/Freelance 15–60 min</li>
                  <li>Max 12 results/scan, max 3 portals/scan in strict mode</li>
                  <li>Circuit breaker pauses 3–4 hours after CAPTCHA or block detection</li>
                  <li>LinkedIn Playwright disabled in strict mode — never log in to platforms</li>
                </ul>
              </div>
            )}

            {/* Google Places info banner */}
            {isPlaces && (
              <div className="rounded-md bg-blue-50 border border-blue-200 px-4 py-3 text-xs text-blue-700 space-y-1">
                <p className="font-semibold">📍 Google Places — finds businesses without websites</p>
                <p>Uses the official Google Maps API to find local businesses that have no website. These are prime IT services leads (web development, cloud setup, managed IT). Uses your GOOGLE_API_KEY from .env.</p>
                <p className="text-blue-500">Free tier: ~11,700 searches/month included in the $200 Google credit.</p>
              </div>
            )}

            {isJobPortals && (
              <div className="rounded-md bg-violet-50 border border-violet-200 px-4 py-3 text-xs text-violet-700 space-y-1">
                <p className="font-semibold">💼 Job Portals — companies hiring software developers</p>
                <p>Pulls live listings from public APIs and RSS (RemoteOK, Jobicy, Working Nomads, WWR, etc.). Each hiring company becomes a lead for IT services, staff aug, and DevOps contracts.</p>
                <p className="text-violet-500">No login required. No API keys needed for most boards.</p>
              </div>
            )}

            {/* Name */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Source name</label>
              <input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder={
                  isPlaces ? "e.g. Austin Local Businesses"
                  : isJobPortals ? "e.g. DevOps & Cloud Hiring"
                  : isFreelance ? "e.g. Web Dev & DevOps Projects"
                  : "e.g. LinkedIn IT Pain Points"
                }
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
            ) : isJobPortals || isFreelance ? (
              <>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-2">
                    {isFreelance ? "Marketplaces to scan" : "Job boards to scan"}
                    <span className="text-gray-400"> (select all that apply)</span>
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {(isFreelance ? FREELANCE_MARKETPLACES : JOB_PORTALS).map((portal) => {
                      const selected = (isFreelance ? form.freelance_portals : form.job_portals).includes(portal.value);
                      const badge = AUTH_BADGE[portal.auth];
                      return (
                        <button
                          key={portal.value}
                          type="button"
                          onClick={() => isFreelance ? toggleFreelancePortal(portal.value) : toggleJobPortal(portal.value)}
                          className={`rounded-lg px-3 py-2 text-left border transition-all ${
                            selected
                              ? "bg-brand-600 text-white border-brand-600"
                              : "bg-white text-gray-700 border-gray-300 hover:border-brand-400"
                          }`}
                        >
                          <span className="block text-xs font-medium">{portal.label}</span>
                          <span className={`mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] border ${
                            selected ? "bg-white/20 text-white border-white/30" : badge.className
                          }`}>
                            {badge.label}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    {isFreelance ? "Project keywords" : "Role keywords"}
                    <span className="text-gray-400"> (comma-separated)</span>
                  </label>
                  <textarea
                    value={form.keywords}
                    onChange={(e) => setForm((f) => ({ ...f, keywords: e.target.value }))}
                    rows={2}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-brand-500 resize-none"
                  />
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
                    : isJobPortals || isFreelance
                    ? [10, 20, 30, 50].map((n) => <option key={n} value={n}>{n} {isFreelance ? "projects" : "jobs"}</option>)
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
              const isJP = src.type === "job_portals";
              const isFM = src.type === "freelance_marketplaces";
              const subtitle = isGP
                ? `📍 ${src.config?.location ?? "location not set"} · ${(src.config?.business_types ?? []).length} categories`
                : isJP || isFM
                ? `${isFM ? "🤝" : "💼"} ${(src.config?.portals ?? []).join(", ") || "no portals"} · ${(src.config?.keywords ?? []).slice(0, 3).join(", ")}`
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
                            {src.postsFound != null && ` · ${src.postsFound} ${isGP ? "businesses" : isJP || isFM ? "projects" : "posts"} found`}
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
