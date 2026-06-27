import Badge from "@/components/Badge";
import Button from "@/components/Button";
import type { DashboardTask, TaskAction } from "@/api/types";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/cn";
import {
  Archive,
  CheckCircle,
  Clock3,
  Kanban,
  Layers3,
  ListTodo,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  UserRound,
} from "lucide-react";

interface TaskKanbanBoardProps {
  tasks: DashboardTask[];
  onSelect(task: DashboardTask): void;
  onAction(task: DashboardTask, action: TaskAction): void;
  actionPending?: boolean;
}

interface BoardColumn {
  id: string;
  label: string;
  description: string;
  statuses: Set<string>;
  accent: string;
  icon: typeof ListTodo;
  empty: string;
}

const boardColumns: BoardColumn[] = [
  {
    id: "queue",
    label: "Inbox / Queue",
    description: "New, queued, and unassigned work",
    statuses: new Set(["agency incoming", "received", "queued", "todo", "ready", "unassigned"]),
    accent: "from-cyan-400/20 to-slate-900/20",
    icon: ListTodo,
    empty: "No queued work.",
  },
  {
    id: "assigned",
    label: "Assigned",
    description: "Claimed and waiting to start",
    statuses: new Set(["assigned"]),
    accent: "from-violet-400/20 to-slate-900/20",
    icon: UserRound,
    empty: "Nothing assigned.",
  },
  {
    id: "active",
    label: "In Progress",
    description: "Work currently being handled",
    statuses: new Set(["active", "running", "working", "processing", "in_progress", "in-progress"]),
    accent: "from-emerald-400/20 to-slate-900/20",
    icon: Sparkles,
    empty: "No active runs.",
  },
  {
    id: "blocked",
    label: "Blocked / Failed",
    description: "Needs attention or retry",
    statuses: new Set(["blocked", "failed", "error"]),
    accent: "from-orange-400/20 to-slate-900/20",
    icon: ShieldAlert,
    empty: "No blockers.",
  },
  {
    id: "done",
    label: "Done",
    description: "Completed work",
    statuses: new Set(["done", "completed", "complete"]),
    accent: "from-emerald-400/15 to-slate-900/20",
    icon: CheckCircle,
    empty: "No completed tasks.",
  },
  {
    id: "archived",
    label: "Archived",
    description: "Hidden from active flow",
    statuses: new Set(["archived"]),
    accent: "from-slate-400/15 to-slate-900/20",
    icon: Archive,
    empty: "Archive is empty.",
  },
];

function normalizeStatus(status: string | null | undefined) {
  return (status || "").trim().toLowerCase();
}

function columnForTask(task: DashboardTask) {
  const status = normalizeStatus(task.status);
  return boardColumns.find((column) => column.statuses.has(status)) ?? boardColumns[0];
}

function taskTitle(task: DashboardTask) {
  return task.title || task.message_text?.slice(0, 96) || "Untitled task";
}

function sourceLabel(source: DashboardTask["source"]) {
  return source === "kanban" ? "kanban" : "agency";
}

function SourceIcon({ source }: { source: DashboardTask["source"] }) {
  return source === "kanban" ? (
    <Kanban className="h-3.5 w-3.5 text-violet-300" />
  ) : (
    <ListTodo className="h-3.5 w-3.5 text-cyan-300" />
  );
}

function TaskActionButtons({
  task,
  onAction,
  actionPending,
}: {
  task: DashboardTask;
  onAction(task: DashboardTask, action: TaskAction): void;
  actionPending?: boolean;
}) {
  const actions = task.available_actions.filter((action): action is TaskAction =>
    ["complete", "retry", "archive"].includes(action)
  );

  if (actions.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5 pt-1" aria-label="Task actions">
      {actions.includes("complete") && (
        <Button
          variant="secondary"
          size="sm"
          loading={actionPending}
          aria-label={`Complete ${taskTitle(task)}`}
          className="h-7 px-2 text-[11px]"
          onClick={(event) => {
            event.stopPropagation();
            onAction(task, "complete");
          }}
        >
          <CheckCircle className="h-3.5 w-3.5" />
          Complete
        </Button>
      )}
      {actions.includes("retry") && (
        <Button
          variant="secondary"
          size="sm"
          loading={actionPending}
          aria-label={`Retry ${taskTitle(task)}`}
          className="h-7 px-2 text-[11px]"
          onClick={(event) => {
            event.stopPropagation();
            onAction(task, "retry");
          }}
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Retry
        </Button>
      )}
      {actions.includes("archive") && (
        <Button
          variant="ghost"
          size="sm"
          loading={actionPending}
          aria-label={`Archive ${taskTitle(task)}`}
          className="h-7 px-2 text-[11px]"
          onClick={(event) => {
            event.stopPropagation();
            onAction(task, "archive");
          }}
        >
          <Archive className="h-3.5 w-3.5" />
          Archive
        </Button>
      )}
    </div>
  );
}

function TaskCard({
  task,
  onSelect,
  onAction,
  actionPending,
}: {
  task: DashboardTask;
  onSelect(task: DashboardTask): void;
  onAction(task: DashboardTask, action: TaskAction): void;
  actionPending?: boolean;
}) {
  const timestamp = task.updated_at || task.created_at;
  const hasKanbanLink = task.linked_kanban_status && task.linked_kanban_status !== "none";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(task)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(task);
        }
      }}
      className={cn(
        "group rounded-xl border border-slate-800/70 bg-slate-950/45 p-3 text-left shadow-lg shadow-slate-950/20",
        "transition-all duration-200 hover:-translate-y-0.5 hover:border-cyan-400/30 hover:bg-slate-900/75 hover:shadow-cyan-950/20",
        "focus:outline-none focus:ring-2 focus:ring-cyan-400/50"
      )}
      aria-label={`Open task details for ${taskTitle(task)}`}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-semibold leading-5 text-slate-100 line-clamp-2">
          {taskTitle(task)}
        </h3>
        <span className="rounded-lg border border-slate-800 bg-slate-900/80 p-1.5">
          <SourceIcon source={task.source} />
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <Badge variant="outline" size="sm" className="gap-1 border-slate-700/80 bg-slate-900/60 text-slate-300">
          <SourceIcon source={task.source} />
          {sourceLabel(task.source)}
        </Badge>
        <Badge variant="status" status={task.status} size="sm">
          {task.status || "unknown"}
        </Badge>
        {hasKanbanLink && task.linked_kanban_status !== "present" && (
          <Badge variant="outline" size="sm" className="border-amber-400/30 text-amber-300">
            kanban: {task.linked_kanban_status}
          </Badge>
        )}
      </div>

      {(task.assignee || task.board) && (
        <div className="mt-3 grid gap-1.5 text-xs text-slate-400">
          {task.assignee && (
            <div className="flex min-w-0 items-center gap-1.5">
              <UserRound className="h-3.5 w-3.5 shrink-0 text-slate-500" />
              <span className="truncate">{task.assignee}</span>
            </div>
          )}
          {task.board && (
            <div className="flex min-w-0 items-center gap-1.5">
              <Layers3 className="h-3.5 w-3.5 shrink-0 text-slate-500" />
              <span className="truncate">{task.board}</span>
            </div>
          )}
        </div>
      )}

      <div className="mt-3 flex items-center gap-1.5 text-xs text-slate-500">
        <Clock3 className="h-3.5 w-3.5" />
        <span>{task.updated_at ? "Updated" : "Created"} {formatRelative(timestamp)}</span>
      </div>

      <TaskActionButtons task={task} onAction={onAction} actionPending={actionPending} />
    </div>
  );
}

export default function TaskKanbanBoard({
  tasks,
  onSelect,
  onAction,
  actionPending = false,
}: TaskKanbanBoardProps) {
  const tasksByColumn = boardColumns.map((column) => ({
    column,
    tasks: tasks.filter((task) => columnForTask(task).id === column.id),
  }));

  return (
    <div className="overflow-x-auto pb-2">
      <div className="grid min-w-[1120px] grid-cols-6 gap-4 lg:min-w-0">
        {tasksByColumn.map(({ column, tasks: columnTasks }) => {
          const Icon = column.icon;
          return (
            <section
              key={column.id}
              className="glass-card-sm flex min-h-[28rem] flex-col overflow-hidden"
              aria-label={`${column.label} column`}
            >
              <div className={cn("border-b border-slate-800/70 bg-gradient-to-br p-3", column.accent)}>
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="rounded-lg border border-slate-700/70 bg-slate-950/50 p-1.5">
                      <Icon className="h-4 w-4 text-slate-200" />
                    </span>
                    <div className="min-w-0">
                      <h2 className="truncate text-sm font-semibold text-slate-100">{column.label}</h2>
                      <p className="truncate text-[11px] text-slate-400">{column.description}</p>
                    </div>
                  </div>
                  <Badge variant="outline" size="sm" className="bg-slate-950/40 text-slate-200">
                    {columnTasks.length}
                  </Badge>
                </div>
              </div>

              <div className="flex-1 space-y-3 overflow-y-auto p-3">
                {columnTasks.length === 0 ? (
                  <div className="flex min-h-32 items-center justify-center rounded-xl border border-dashed border-slate-800/80 bg-slate-950/30 px-3 py-6 text-center text-xs text-slate-500">
                    {column.empty}
                  </div>
                ) : (
                  columnTasks.map((task) => (
                    <TaskCard
                      key={`${task.source}:${task.id}`}
                      task={task}
                      onSelect={onSelect}
                      onAction={onAction}
                      actionPending={actionPending}
                    />
                  ))
                )}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
