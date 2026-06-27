import { useState, useMemo } from "react";
import PageHeader from "@/components/PageHeader";
import Badge from "@/components/Badge";
import Drawer from "@/components/Drawer";
import Skeleton from "@/components/Skeleton";
import EmptyState from "@/components/EmptyState";
import ErrorState from "@/components/ErrorState";
import Tabs from "@/components/Tabs";
import Button from "@/components/Button";
import { useTasks } from "@/api/queries";
import type { DashboardTask } from "@/api/types";
import { formatRelative, formatDate } from "@/lib/format";
import { ListTodo, Archive, CheckCircle, Kanban } from "lucide-react";

const statusTabs = [
  { id: "all", label: "All" },
  { id: "active", label: "Active" },
  { id: "queued", label: "Queued" },
  { id: "completed", label: "Completed" },
  { id: "failed", label: "Failed" },
  { id: "blocked", label: "Blocked" },
  { id: "archived", label: "Archived" },
  { id: "stale", label: "Stale" },
];

export default function TasksPage() {
  const [statusFilter, setStatusFilter] = useState("all");
  const [selected, setSelected] = useState<DashboardTask | null>(null);
  const { data, isLoading, error, refetch } = useTasks(
    statusFilter === "all" ? undefined : statusFilter
  );

  const tasks = data ?? [];

  if (isLoading) return <Skeleton lines={8} />;
  if (error) return <ErrorState message={error.message} onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tasks"
        description={`${tasks.length} tasks`}
      />

      <Tabs tabs={statusTabs} activeTab={statusFilter} onChange={setStatusFilter} />

      {tasks.length === 0 ? (
        <EmptyState
          icon={<ListTodo className="h-8 w-8" />}
          title="No tasks"
          description={statusFilter !== "all" ? `No ${statusFilter} tasks found` : "No tasks in the system"}
        />
      ) : (
        <div className="space-y-2">
          {tasks.map((task) => (
            <div
              key={task.id}
              onClick={() => setSelected(task)}
              className="glass-card-sm flex items-center gap-4 px-4 py-3 cursor-pointer hover:border-slate-700 transition-colors"
            >
              {/* Source indicator */}
              <div className="flex-shrink-0">
                {task.source === "kanban" ? (
                  <Kanban className="h-4 w-4 text-violet-400" />
                ) : (
                  <ListTodo className="h-4 w-4 text-cyan-400" />
                )}
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h4 className="text-sm font-medium text-slate-200 truncate">
                    {task.title || task.message_text?.slice(0, 80) || "—"}
                  </h4>
                  <span className="text-[10px] font-mono text-slate-600">
                    {task.source === "kanban" ? "kanban" : "agency"}
                  </span>
                </div>
                <p className="text-xs text-slate-500 mt-0.5 truncate">
                  {formatRelative(task.created_at)}
                </p>
              </div>

              {/* Status */}
              <div className="flex items-center gap-2 flex-shrink-0">
                <Badge variant="status" status={task.status} size="sm">
                  {task.status}
                </Badge>
                {task.linked_kanban_status !== "none" && (
                  <Badge variant="outline" size="sm">
                    kanban: {task.linked_kanban_status}
                  </Badge>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Task detail drawer */}
      <Drawer
        open={!!selected}
        onClose={() => setSelected(null)}
        title="Task Details"
      >
        {selected && (
          <div className="space-y-6">
            <div>
              <p className="text-xs text-slate-500 mb-1">ID</p>
              <p className="text-sm font-mono text-slate-300">{selected.id}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Title</p>
              <p className="text-sm text-slate-300">{selected.title || "—"}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Message</p>
              <p className="text-sm text-slate-300 whitespace-pre-wrap">{selected.message_text || "—"}</p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-slate-500 mb-1">Status</p>
                <Badge variant="status" status={selected.status}>{selected.status}</Badge>
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-1">Source</p>
                <p className="text-sm text-slate-300">{selected.source}</p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-slate-500 mb-1">Kanban Task ID</p>
                <p className="text-sm font-mono text-slate-300">{selected.kanban_task_id ?? "—"}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-1">Kanban Status</p>
                <Badge variant="outline" size="sm">{selected.linked_kanban_status}</Badge>
              </div>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Created</p>
              <p className="text-sm text-slate-300">{formatDate(selected.created_at)}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Updated</p>
              <p className="text-sm text-slate-300">{formatDate(selected.updated_at)}</p>
            </div>
            {selected.result_text && (
              <div>
                <p className="text-xs text-slate-500 mb-1">Result</p>
                <div className="rounded-lg bg-slate-800/60 p-3 text-sm text-slate-300 whitespace-pre-wrap">
                  {selected.result_text}
                </div>
              </div>
            )}
            {selected.error_text && (
              <div>
                <p className="text-xs text-slate-500 mb-1">Error</p>
                <div className="rounded-lg bg-red-900/20 p-3 text-sm text-red-300 whitespace-pre-wrap">
                  {selected.error_text}
                </div>
              </div>
            )}
            {selected.available_actions.length > 0 && (
              <div>
                <p className="text-xs text-slate-500 mb-2">Available Actions</p>
                <div className="flex flex-wrap gap-1.5">
                  {selected.available_actions.map((action) => (
                    <Badge key={action} variant="outline" size="sm">{action}</Badge>
                  ))}
                </div>
              </div>
            )}
            <div className="flex gap-2 pt-2">
              <Button variant="secondary" size="sm">
                <CheckCircle className="h-4 w-4" /> Complete
              </Button>
              <Button variant="ghost" size="sm">
                <Archive className="h-4 w-4" /> Archive
              </Button>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
