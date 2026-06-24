"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Topbar } from "@/components/layout/Topbar";
import { useAuthStore } from "@/lib/stores/authStore";
import api from "@/lib/api/client";

async function fetchMe() {
  const { data } = await api.get("/auth/me");
  return data as any;
}
async function updateProfile(body: any) {
  const { data } = await api.patch("/auth/me", body);
  return data;
}
async function changePassword(body: any) {
  await api.post("/auth/change-password", body);
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm space-y-4">
      <h2 className="text-sm font-semibold text-gray-900 border-b border-gray-100 pb-3">{title}</h2>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
      {children}
    </div>
  );
}

const inputCls = "w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-brand-500";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const user = useAuthStore((s: any) => s.user);

  const { data: me } = useQuery({ queryKey: ["me"], queryFn: fetchMe });

  const [profile, setProfile] = useState({ name: "", email: "" });
  const [profileReady, setProfileReady] = useState(false);
  const [pwForm, setPwForm] = useState({ current_password: "", new_password: "", confirm: "" });
  const [pwMsg, setPwMsg] = useState("");
  const [apiKeyVisible, setApiKeyVisible] = useState(false);

  if (me && !profileReady) {
    setProfile({ name: me.name || "", email: me.email || "" });
    setProfileReady(true);
  }

  const profileMutation = useMutation({
    mutationFn: updateProfile,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me"] }),
  });

  const passwordMutation = useMutation({
    mutationFn: changePassword,
    onSuccess: () => {
      setPwForm({ current_password: "", new_password: "", confirm: "" });
      setPwMsg("Password updated successfully.");
      setTimeout(() => setPwMsg(""), 3000);
    },
    onError: (e: any) => setPwMsg(e?.response?.data?.message || "Failed to update password."),
  });

  function handlePasswordSubmit() {
    if (pwForm.new_password !== pwForm.confirm) {
      setPwMsg("New passwords do not match.");
      return;
    }
    if (pwForm.new_password.length < 8) {
      setPwMsg("Password must be at least 8 characters.");
      return;
    }
    setPwMsg("");
    passwordMutation.mutate({ current_password: pwForm.current_password, new_password: pwForm.new_password });
  }

  return (
    <div>
      <Topbar title="Settings" />
      <div className="p-6 max-w-2xl space-y-6">

        {/* Profile */}
        <Section title="Profile">
          <Field label="Full name">
            <input
              value={profile.name}
              onChange={(e) => setProfile((p) => ({ ...p, name: e.target.value }))}
              className={inputCls}
            />
          </Field>
          <Field label="Email">
            <input
              value={profile.email}
              onChange={(e) => setProfile((p) => ({ ...p, email: e.target.value }))}
              type="email"
              className={inputCls}
            />
          </Field>
          <div className="flex items-center gap-3 pt-1">
            <button
              onClick={() => profileMutation.mutate(profile)}
              disabled={profileMutation.isPending}
              className="rounded-md bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {profileMutation.isPending ? "Saving…" : "Save changes"}
            </button>
            {profileMutation.isSuccess && (
              <span className="text-sm text-green-600">Saved!</span>
            )}
          </div>
        </Section>

        {/* Password */}
        <Section title="Change password">
          <Field label="Current password">
            <input
              type="password"
              value={pwForm.current_password}
              onChange={(e) => setPwForm((f) => ({ ...f, current_password: e.target.value }))}
              className={inputCls}
            />
          </Field>
          <Field label="New password">
            <input
              type="password"
              value={pwForm.new_password}
              onChange={(e) => setPwForm((f) => ({ ...f, new_password: e.target.value }))}
              className={inputCls}
            />
          </Field>
          <Field label="Confirm new password">
            <input
              type="password"
              value={pwForm.confirm}
              onChange={(e) => setPwForm((f) => ({ ...f, confirm: e.target.value }))}
              className={inputCls}
              onKeyDown={(e) => e.key === "Enter" && handlePasswordSubmit()}
            />
          </Field>
          {pwMsg && (
            <p className={`text-sm ${pwMsg.includes("success") ? "text-green-600" : "text-red-600"}`}>{pwMsg}</p>
          )}
          <button
            onClick={handlePasswordSubmit}
            disabled={!pwForm.current_password || !pwForm.new_password || passwordMutation.isPending}
            className="rounded-md bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {passwordMutation.isPending ? "Updating…" : "Update password"}
          </button>
        </Section>

        {/* Organisation */}
        <Section title="Organisation">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-xs font-medium text-gray-500">Name</p>
              <p className="text-gray-900 mt-0.5">{me?.org_name ?? "—"}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-gray-500">Plan</p>
              <p className="text-gray-900 mt-0.5 capitalize">{me?.plan ?? "free"}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-gray-500">Your role</p>
              <p className="text-gray-900 mt-0.5 capitalize">{me?.role ?? "admin"}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-gray-500">Member since</p>
              <p className="text-gray-900 mt-0.5">{me?.created_at ? new Date(me.created_at).toLocaleDateString() : "—"}</p>
            </div>
          </div>
        </Section>

        {/* Safety & approval rules */}
        <Section title="Safety & approval">
          <div className="space-y-3 text-sm">
            <div className="flex items-center justify-between rounded-md bg-green-50 border border-green-200 px-4 py-3">
              <div>
                <p className="font-medium text-green-800">Human approval required</p>
                <p className="text-green-700 text-xs mt-0.5">All AI drafts must be manually approved before posting.</p>
              </div>
              <span className="rounded-full bg-green-600 px-2.5 py-0.5 text-xs font-semibold text-white">Always on</span>
            </div>
            <div className="flex items-center justify-between rounded-md bg-green-50 border border-green-200 px-4 py-3">
              <div>
                <p className="font-medium text-green-800">Safety classifier</p>
                <p className="text-green-700 text-xs mt-0.5">High-severity AI outputs are blocked automatically.</p>
              </div>
              <span className="rounded-full bg-green-600 px-2.5 py-0.5 text-xs font-semibold text-white">Always on</span>
            </div>
            <p className="text-xs text-gray-400">
              These settings cannot be disabled. ProspectOS never posts, sends, or contacts anyone without explicit human approval.
            </p>
          </div>
        </Section>

        {/* Danger zone */}
        <Section title="Danger zone">
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-red-800">Delete account</p>
              <p className="text-xs text-red-700 mt-0.5">Permanently delete your account and all data. This cannot be undone.</p>
            </div>
            <button
              onClick={() => alert("Please contact support to delete your account.")}
              className="rounded-md border border-red-400 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100 flex-shrink-0"
            >
              Delete account
            </button>
          </div>
        </Section>
      </div>
    </div>
  );
}
