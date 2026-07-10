import type { Issue } from "@paperclipai/shared";

export const HERMES_KANBAN_TASK_ORIGIN_KIND = "hermes_kanban_task";

export interface HermesKanbanIssueMetadata {
  taskId: string;
  status: string | null;
  priority: string | null;
  assignee: string | null;
  workspacePath: string | null;
  tenant: string | null;
  blockKind: string | null;
  lastHeartbeatAt: Date | null;
  latestBlockReason: string | null;
  latestRunSummary: string | null;
  latestRunError: string | null;
  taskResult: string | null;
  projectionSyncedAt: Date | null;
}

const SECTION_LABELS = [
  "Latest block reason",
  "Latest run summary",
  "Latest run error",
  "Task result",
] as const;

type SectionLabel = (typeof SECTION_LABELS)[number];

export function isHermesKanbanIssue(issue: Pick<Issue, "originKind" | "originId" | "description">): boolean {
  return issue.originKind === HERMES_KANBAN_TASK_ORIGIN_KIND || /^t_[a-z0-9]+$/i.test(issue.originId ?? "") || /Hermes Kanban task:/i.test(issue.description ?? "");
}

export function parseHermesKanbanIssueMetadata(
  issue: Pick<Issue, "originKind" | "originId" | "description" | "updatedAt">,
): HermesKanbanIssueMetadata | null {
  if (!isHermesKanbanIssue(issue)) return null;

  const description = issue.description ?? "";
  const fields = new Map<string, string>();
  const sections = new Map<SectionLabel, string>();
  const lines = description.split(/\r?\n/);

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]?.trim() ?? "";
    const section = SECTION_LABELS.find((label) => line === `${label}:`);
    if (section) {
      const bodyLines: string[] = [];
      for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
        const nextLine = lines[cursor] ?? "";
        const trimmed = nextLine.trim();
        if (SECTION_LABELS.some((label) => trimmed === `${label}:`)) break;
        if (/^[A-Z][A-Za-z ]+:\s+/.test(trimmed)) break;
        bodyLines.push(nextLine);
        index = cursor;
      }
      const value = bodyLines.join("\n").trim();
      if (value) sections.set(section, value);
      continue;
    }

    const match = line.match(/^([A-Z][A-Za-z ]+):\s*(.+)$/);
    if (match) fields.set(match[1].toLowerCase(), match[2].trim());
  }

  const taskId = fields.get("hermes kanban task") ?? issue.originId ?? null;
  if (!taskId) return null;

  return {
    taskId,
    status: fields.get("status") ?? null,
    priority: fields.get("priority") ?? null,
    assignee: fields.get("assignee") ?? null,
    workspacePath: fields.get("workspace") ?? null,
    tenant: fields.get("tenant") ?? null,
    blockKind: fields.get("block kind") ?? null,
    lastHeartbeatAt: parseMetadataDate(fields.get("last heartbeat")),
    latestBlockReason: sections.get("Latest block reason") ?? null,
    latestRunSummary: sections.get("Latest run summary") ?? null,
    latestRunError: sections.get("Latest run error") ?? null,
    taskResult: sections.get("Task result") ?? null,
    projectionSyncedAt: normalizeDate(issue.updatedAt),
  };
}

export function isHermesKanbanHeartbeatStale(metadata: Pick<HermesKanbanIssueMetadata, "status" | "lastHeartbeatAt">, now = Date.now()): boolean {
  if (metadata.status !== "running" || !metadata.lastHeartbeatAt) return false;
  return now - metadata.lastHeartbeatAt.getTime() > 60 * 60 * 1000;
}

function parseMetadataDate(value: string | null | undefined): Date | null {
  if (!value || value === "never") return null;
  return normalizeDate(value);
}

function normalizeDate(value: Date | string | null | undefined): Date | null {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}
