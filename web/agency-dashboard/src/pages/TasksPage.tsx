import { useMemo, useState } from "react";
import PageHeader from "@/components/PageHeader";
import Badge from "@/components/Badge";
import Drawer from "@/components/Drawer";
import Skeleton from "@/components/Skeleton";
import EmptyState from "@/components/EmptyState";
import ErrorState from "@/components/ErrorState";
import Tabs from "@/components/Tabs";
import Button from "@/components/Button";
import ConfirmDialog from "@/components/ConfirmDialog";
import TaskKanbanBoard from "@/components/tasks/TaskKanbanBoard";
import { useHealth, useTaskAction, useTasks } from "@/api/queries";
import type { DashboardTask, TaskAction } from "@/api/types";
import { formatRelative, formatDate } from "@/lib/format";
import { addToast } from "@/hooks/useToast";
import {
  ListTodo,
  Archive,
  CheckCircle,
  Kanban,
  RotateCcw,
} from "lucide-react";

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

const actionLabel: Record<TaskAction, string> = {
  archive: "Archive",
  complete: "Complete",
  retry: "Retry",
};

const activeStatuses = new Set(["active", "running", "working", "queued", "processing", "received"]);
const blockedStatuses = new Set(["blocked", "failed", "error"]);
const doneStatuses = new Set(["done", "completed", "complete"]);

function matchesStatus(task: DashboardTask, statusFilter: string) {
  if (statusFilter === "all") return true;
  const status = (task.status || "").toLowerCase();
  if (statusFilter === "active") return activeStatuses.has(status);
  return status === statusFilter;
}

export default function TasksPage() {
  const [statusFilter, setStatusFilter] = useState("all");
  const [viewMode, setViewMode] = useState<"board" | "list">("board");
  const [selected, setSelected] = useState<DashboardTask | null>(null);
  const [confirmAction, setConfirmAction] = useState<{
    task: DashboardTask;
    action: TaskAction;
  } | null>(null);
  // Load the unified task list once and filter tabs client-side.
  // This keeps tab switching instant instead of issuing a fresh backend query per tab.
  const { data, isLoading, error, refetch, isFetching } = useTasks();
  const { data: health } = useHealth();
  const taskAction = useTaskAction();

  const allTasks = data ?? [];
  const tasks = useMemo(
    () => allTasks.filter((task) => matchesStatus(task, statusFilter)),
    [allTasks, statusFilter]
  );
  const summary = useMemo(() => {
    const counts = { total: tasks.length, active: 0, blocked: 0, done: 0 };
    for (const task of tasks) {
      const status = (task.status || "").toLowerCase();
      if (activeStatuses.has(status)) counts.active += 1;
      if (blockedStatuses.has(status)) counts.blocked += 1;
      if (doneStatuses.has(status)) counts.done += 1;
    }
    return counts;
  }, [tasks]);

  const runAction = (task: DashboardTask, action: TaskAction) => {
    taskAction.mutate(
      { task, action },
      {
        onSuccess: () => {
          addToast("success", `${actionLabel[action]} succeeded`);
          setConfirmAction(null);
          if (action === "archive") {
            setSelected(null);
          }
          refetch();
        },
        onError: (err) => {
          addToast("error", `${actionLabel[action]} failed: ${err.message}`);
        },
      }
    );
  };

  const requestAction = (task: DashboardTask, action: TaskAction) => {
    if (action === "archive") {
      setConfirmAction({ task, action });
      return;
    }
    runAction(task, action);
  };

  if (isLoading) return <Skeleton lines={8} />;
  if (error) return <ErrorState message={error.message} onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tasks"
        description={`${tasks.length} ${statusFilter === "all" ? "tasks" : `${statusFilter} tasks`}${isFetching ? " · refreshing" : ""}`}
      />

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <Tabs tabs={statusTabs} activeTab={statusFilter} onChange={setStatusFilter} />
        <div className="flex rounded-xl border border-slate-800 bg-slate-950/40 p-1">
          <Button
            type="button"
            variant={viewMode === "board" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setViewMode("board")}
            aria-pressed={viewMode === "board"}
            className="rounded-lg"
          >
            <Kanban className="h-4 w-4" /> Board
          </Button>
          <Button
            type="button"
            variant={viewMode === "list" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setViewMode("list")}
            aria-pressed={viewMode === "list"}
            className="rounded-lg"
          >
            <ListTodo className="h-4 w-4" /> List
          </Button>
        </div>
      </div>

      <div className="glass-card-sm flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-300">
          <Badge variant="outline" size="sm">{summary.total} visible</Badge>
          <Badge variant="status" status="active" size="sm">{summary.active} active</Badge>
          <Badge variant="status" status={summary.blocked > 0 ? "blocked" : "ok"} size="sm">
            {summary.blocked} blocked
          </Badge>
          <Badge variant="status" status="done" size="sm">{summary.done} done</Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          {isFetching && <span className="text-cyan-300">Refreshing…</span>}
          {health && !health.kanban_available && (
            <span className="rounded-full border border-amber-400/20 bg-amber-400/10 px-2 py-0.5 text-amber-300">
              Kanban unavailable — showing agency records only
            </span>
          )}
        </div>
      </div>

      {viewMode === "board" ? (
        <TaskKanbanBoard
          tasks={tasks}
          onSelect={setSelected}
          onAction={requestAction}
          actionPending={taskAction.isPending}
        />
      ) : tasks.length === 0 ? (
        <EmptyState
          icon={<ListTodo className="h-8 w-8" />}
          title="No tasks"
          description={statusFilter !== "all" ? `No ${statusFilter} tasks found` : "No tasks in the system"}
        />
      ) : (
        <div className="space-y-2">
          {tasks.map((task) => (
            <div
              key={`${task.source}:${task.id}`}
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
              <p className="text-sm font-mono text-slate-300 break-all">{selected.id}</p>
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
                <p className="text-sm font-mono text-slate-300 break-all">{selected.kanban_task_id ?? "—"}</p>
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
            <div className="flex flex-wrap gap-2 pt-2">
              {selected.available_actions.includes("complete") && (
                <Button
                  variant="secondary"
                  size="sm"
                  loading={taskAction.isPending}
                  onClick={() => requestAction(selected, "complete")}
                >
                  <CheckCircle className="h-4 w-4" /> Complete
                </Button>
              )}
              {selected.available_actions.includes("retry") && (
                <Button
                  variant="secondary"
                  size="sm"
                  loading={taskAction.isPending}
                  onClick={() => requestAction(selected, "retry")}
                >
                  <RotateCcw className="h-4 w-4" /> Retry
                </Button>
              )}
              {selected.available_actions.includes("archive") && (
                <Button
                  variant="ghost"
                  size="sm"
                  loading={taskAction.isPending}
                  onClick={() => requestAction(selected, "archive")}
                >
                  <Archive className="h-4 w-4" /> Archive
                </Button>
              )}
              {selected.available_actions.length === 0 && (
                <p className="text-sm text-slate-500">No actions available for this task.</p>
              )}
            </div>
          </div>
        )}
      </Drawer>

      <ConfirmDialog
        open={!!confirmAction}
        onClose={() => setConfirmAction(null)}
        onConfirm={() => {
          if (confirmAction) runAction(confirmAction.task, confirmAction.action);
        }}
        title="Archive task?"
        message="This will hide the task from the active dashboard views. You can still inspect archived tasks using the Archived filter."
        confirmLabel="Archive"
        variant="danger"
        loading={taskAction.isPending}
      />
    </div>
  );
}
