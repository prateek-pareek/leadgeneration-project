"use client";

import { useQuery } from "@tanstack/react-query";
import { Users, MessageSquare, TrendingUp, Calendar } from "lucide-react";
import { Topbar } from "@/components/layout/Topbar";
import api from "@/lib/api/client";

async function fetchOverview() {
  const { data } = await api.get("/analytics/overview");
  return data as {
    leads_discovered: number;
    hot_leads: number;
    comments_drafted: number;
    comments_posted: number;
    meetings_booked: number;
  };
}

function KpiCard({ title, value, icon: Icon, color }: {
  title: string; value: number; icon: React.ElementType; color: string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-gray-500">{title}</p>
        <div className={`rounded-md p-2 ${color}`}>
          <Icon className="h-4 w-4 text-white" />
        </div>
      </div>
      <p className="mt-3 text-3xl font-bold text-gray-900">{value.toLocaleString()}</p>
    </div>
  );
}

export default function DashboardPage() {
  const { data, isLoading } = useQuery({ queryKey: ["analytics", "overview"], queryFn: fetchOverview });

  return (
    <div>
      <Topbar title="Dashboard" />
      <div className="p-6 space-y-6">
        {/* KPI grid */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <KpiCard
            title="Leads Discovered"
            value={isLoading ? 0 : (data?.leads_discovered ?? 0)}
            icon={Users}
            color="bg-blue-500"
          />
          <KpiCard
            title="Hot Leads"
            value={isLoading ? 0 : (data?.hot_leads ?? 0)}
            icon={TrendingUp}
            color="bg-red-500"
          />
          <KpiCard
            title="Comments Drafted"
            value={isLoading ? 0 : (data?.comments_drafted ?? 0)}
            icon={MessageSquare}
            color="bg-indigo-500"
          />
          <KpiCard
            title="Meetings Booked"
            value={isLoading ? 0 : (data?.meetings_booked ?? 0)}
            icon={Calendar}
            color="bg-green-500"
          />
        </div>

        {/* Quick actions */}
        <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Quick Actions</h2>
          <div className="flex flex-wrap gap-3">
            <a href="/discover" className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">
              Discover Leads
            </a>
            <a href="/comments/approval" className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
              Review Comments
            </a>
            <a href="/crm" className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
              Open CRM
            </a>
            <a href="/email-health" className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
              Email Health
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
