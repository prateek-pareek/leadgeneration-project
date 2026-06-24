"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Topbar } from "@/components/layout/Topbar";
import { EmptyState } from "@/components/shared/EmptyState";
import { CheckSquare, Plus, Check, Trash2, Calendar } from "lucide-react";
import api from "@/lib/api/client";

async function fetchTasks() {
  const { data } = await api.get("/tasks", { params: { limit: 100 } });
  return data as any[];
}
async function createTask(body: any) { const { data } = await api.post("/tasks", body); return data; }
async function updateTask({ id, ...body }: any) { await api.patch(`/tasks/${id}`, body); }
async function deleteTask(id: string) { await api.delete(`/tasks/${id}`); }

const PRIORITY_STYLE: Record<string, string> = {
  urgent: "bg-red-100 text-red-700",
  high:   "bg-orange-100 text-orange-700",
  medium: "bg-blue-100 text-blue-700",
  low:    "bg-gray-100 text-gray-600",
};

export default function TasksPage() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [filter, setFilter] = useState<"all" | "todo" | "done">("todo");
  const [form, setForm] = useState({ title: "", priority: "medium", due_at: "" });

  const { data: tasks = [], isLoading } = useQuery({
    queryKey: ["tasks"],
    queryFn: fetchTasks,
    refetchInterval: 30_000,
  });

  const createMutation = useMutation({
    mutationFn: createTask,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      setForm({ title: "", priority: "medium", due_at: "" });
      setShowForm(false);
    },
  });

  const updateMutation = useMutation({
    mutationFn: updateTask,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteTask,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks"] }),
  });

  const filtered = tasks.filter((t: any) => {
    if (filter === "todo") return t.status !== "done";
    if (filter === "done") return t.status === "done";
    return true;
  });

  const doneCount = tasks.filter((t: any) => t.status === "done").length;
  const todoCount = tasks.filter((t: any) => t.status !== "done").length;

  return (
    <div>
      <Topbar title="Tasks" />
      <div className="p-6 max-w-2xl space-y-5">
        {/* Stats + filter */}
        <div className="flex items-center gap-4">
          {(["all", "todo", "done"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-full px-3 py-1 text-sm font-medium transition-colors ${
                filter === f ? "bg-brand-100 text-brand-700" : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {f === "all" ? `All (${tasks.length})` : f === "todo" ? `To do (${todoCount})` : `Done (${doneCount})`}
            </button>
          ))}
          <div className="ml-auto">
            <button
              onClick={() => setShowForm(!showForm)}
              className="inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700"
            >
              <Plus className="h-4 w-4" />
              New task
            </button>
          </div>
        </div>

        {/* Create form */}
        {showForm && (
          <div className="rounded-lg border border-brand-200 bg-brand-50 p-4 space-y-3">
            <input
              value={form.title}
              onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              placeholder="Task title…"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-brand-500"
              onKeyDown={(e) => e.key === "Enter" && form.title && createMutation.mutate({ ...form, status: "todo" })}
              autoFocus
            />
            <div className="flex items-center gap-3">
              <select
                value={form.priority}
                onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value }))}
                className="rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none"
              >
                <option value="urgent">Urgent</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
              <input
                type="date"
                value={form.due_at}
                onChange={(e) => setForm((f) => ({ ...f, due_at: e.target.value }))}
                className="rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none"
              />
              <button
                onClick={() => form.title && createMutation.mutate({ ...form, status: "todo" })}
                disabled={!form.title || createMutation.isPending}
                className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
              >
                Add
              </button>
              <button onClick={() => setShowForm(false)} className="text-sm text-gray-500">Cancel</button>
            </div>
          </div>
        )}

        {/* Task list */}
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-12 rounded-lg bg-gray-100 animate-pulse" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={CheckSquare}
            title={filter === "done" ? "No completed tasks" : "All clear!"}
            description={filter === "done" ? "Complete tasks will appear here." : "Add a task to stay on top of your pipeline."}
            action={filter !== "done" ? { label: "Add task", onClick: () => setShowForm(true) } : undefined}
          />
        ) : (
          <div className="space-y-1">
            {filtered.map((task: any) => {
              const isDone = task.status === "done";
              const isOverdue = task.due_at && !isDone && new Date(task.due_at) < new Date();
              return (
                <div
                  key={task.id}
                  className={`group flex items-center gap-3 rounded-lg border px-4 py-3 transition-colors ${
                    isDone ? "border-gray-100 bg-gray-50" : "border-gray-200 bg-white hover:border-gray-300"
                  }`}
                >
                  {/* Complete checkbox */}
                  <button
                    onClick={() => updateMutation.mutate({ id: task.id, status: isDone ? "todo" : "done" })}
                    className={`flex-shrink-0 h-5 w-5 rounded border-2 flex items-center justify-center transition-colors ${
                      isDone ? "border-green-500 bg-green-500" : "border-gray-300 hover:border-brand-500"
                    }`}
                  >
                    {isDone && <Check className="h-3 w-3 text-white" />}
                  </button>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm ${isDone ? "text-gray-400 line-through" : "text-gray-900"}`}>
                      {task.title}
                    </p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className={`rounded-full px-1.5 py-0.5 text-xs font-medium ${PRIORITY_STYLE[task.priority] ?? PRIORITY_STYLE.medium}`}>
                        {task.priority}
                      </span>
                      {task.due_at && (
                        <span className={`flex items-center gap-1 text-xs ${isOverdue ? "text-red-500 font-medium" : "text-gray-400"}`}>
                          <Calendar className="h-3 w-3" />
                          {isOverdue ? "Overdue · " : ""}{new Date(task.due_at).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Delete */}
                  <button
                    onClick={() => deleteMutation.mutate(task.id)}
                    className="opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-500 transition-opacity"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
