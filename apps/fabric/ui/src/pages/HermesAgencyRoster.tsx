import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Bot, Clock, Search, Send, Users, Wifi, WifiOff } from "lucide-react";
import type { HermesAgencyAgent, HermesAgencyAgentStatus, HermesAgencyDispatchRecord, HermesAgencyTaskPacketPreview } from "@paperclipai/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { hermesAgencyApi } from "../api/hermesAgency";
import { EmptyState } from "../components/EmptyState";
import { PageSkeleton } from "../components/PageSkeleton";
import { useBreadcrumbs } from "../context/BreadcrumbContext";
import { queryKeys } from "../lib/queryKeys";
import { cn } from "../lib/utils";

type StatusFilter = "all" | HermesAgencyAgentStatus;

const statusLabels: Record<HermesAgencyAgentStatus, string> = {
  online: "Online",
  offline: "Offline target",
  wake_failed: "Wake failed",
};

const statusTone: Record<HermesAgencyAgentStatus, string> = {
  online: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  offline: "border-slate-500/30 bg-slate-500/10 text-slate-700 dark:text-slate-300",
  wake_failed: "border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-300",
};

function formatNullable(value: string | null | undefined) {
  return value && value.trim().length > 0 ? value : "—";
}

function formatProvider(agent: HermesAgencyAgent) {
  const model = formatNullable(agent.model);
  const provider = formatNullable(agent.provider);
  if (model === "—" && provider === "—") return "Model/provider unavailable";
  if (model === "—") return provider;
  if (provider === "—") return model;
  return `${provider} · ${model}`;
}

function matchesAgent(agent: HermesAgencyAgent, query: string) {
  if (!query) return true;
  const haystack = [agent.name, agent.description, agent.provider, agent.model]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}

function matchesSkill(agent: HermesAgencyAgent, query: string) {
  if (!query) return true;
  return agent.skills.some((skill) => skill.toLowerCase().includes(query));
}

function matchesStatus(agent: HermesAgencyAgent, filter: StatusFilter) {
  return filter === "all" || agent.status === filter;
}

function buildDispatchPacket(agent: HermesAgencyAgent): HermesAgencyTaskPacketPreview {
  return {
    title: `Route a harmless Hermes Fabric check to ${agent.name}`,
    goal: "Validate that Hermes Fabric can hand a reviewed packet to Hermes Agency without hiding offline queue semantics.",
    context: `Hermes Fabric roster dispatch smoke for ${agent.name}. Offline agents are valid targets; wake failures should remain queued/actionable.`,
    requestedSkills: agent.skills.slice(0, 3),
    targetAgentName: agent.name,
    dispatchMode: "direct-agent",
    routing: { mode: "direct-agent", rationale: `Operator selected ${agent.name} from the roster.` },
    workspaceContext: {
      issueId: null,
      issueIdentifier: null,
      projectName: "Hermes Fabric",
      goalTitle: "Hermes Agency dispatch bridge",
      workspaceId: null,
      workspaceName: null,
      workspaceRoot: null,
      branchName: null,
    },
    validationExpectations: ["Report whether the task was queued, running, completed, blocked, or failed."],
    artifactExpectations: ["Return a concise status report only; no file writes required for this smoke task."],
    stopConditions: ["Stop if the task would require secrets, credentials, destructive commands, or production access."],
    dispatchReady: false,
  };
}

function SummaryCard({ label, value, icon: Icon }: { label: string; value: number; icon: typeof Users }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Icon className="h-4 w-4" />
        {label}
      </div>
      <div className="mt-2 text-3xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: HermesAgencyAgentStatus }) {
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium", statusTone[status])}>
      {statusLabels[status]}
    </span>
  );
}

function AgentCard({ agent, onDispatch, isDispatching }: {
  agent: HermesAgencyAgent;
  onDispatch: (agent: HermesAgencyAgent) => void;
  isDispatching: boolean;
}) {
  return (
    <article className="rounded-xl border border-border bg-card p-4 shadow-sm">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="break-words text-base font-semibold">{agent.name}</h2>
            <StatusBadge status={agent.status} />
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{agent.description || "No description provided."}</p>
        </div>
        <div className="flex shrink-0 flex-col gap-2">
          <div className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
            {formatProvider(agent)}
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => onDispatch(agent)}
            disabled={isDispatching}
          >
            <Send className="h-4 w-4" />
            Send to Hermes Agency
          </Button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5">
        {agent.skills.length > 0 ? agent.skills.map((skill) => (
          <Badge key={skill} variant="secondary" className="font-normal">{skill}</Badge>
        )) : <span className="text-xs text-muted-foreground">No skills listed</span>}
      </div>

      <dl className="mt-4 grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
        <div>
          <dt className="font-medium text-foreground/80">Last seen</dt>
          <dd>{formatNullable(agent.lastSeen)}</dd>
        </div>
        <div>
          <dt className="font-medium text-foreground/80">Wake attempts</dt>
          <dd>{agent.wakeAttempts}</dd>
        </div>
        <div>
          <dt className="font-medium text-foreground/80">Last attempt</dt>
          <dd>{formatNullable(agent.lastAttempt)}</dd>
        </div>
      </dl>

      {agent.lastError ? (
        <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-900 dark:text-amber-200">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div className="font-medium">Last wake/profile error</div>
              <div className="mt-1 break-words font-mono text-xs">{agent.lastError}</div>
            </div>
          </div>
        </div>
      ) : null}
    </article>
  );
}

export function HermesAgencyRoster() {
  const { setBreadcrumbs } = useBreadcrumbs();
  const [agentQuery, setAgentQuery] = useState("");
  const [skillQuery, setSkillQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  useEffect(() => {
    setBreadcrumbs([{ label: "Hermes Agency roster" }]);
    return () => setBreadcrumbs([]);
  }, [setBreadcrumbs]);

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.hermesAgency.roster,
    queryFn: () => hermesAgencyApi.roster(),
    refetchInterval: 30_000,
  });

  const agents = data?.agents ?? [];
  const [latestDispatch, setLatestDispatch] = useState<HermesAgencyDispatchRecord | null>(null);
  const dispatchMutation = useMutation({
    mutationFn: (agent: HermesAgencyAgent) => hermesAgencyApi.dispatch({
      packet: buildDispatchPacket(agent),
      mode: "skill-fit",
    }),
    onSuccess: (record) => setLatestDispatch(record),
  });
  const wakeFailed = agents.filter((agent) => agent.status === "wake_failed").length;
  const filteredAgents = useMemo(() => {
    const normalizedAgentQuery = agentQuery.trim().toLowerCase();
    const normalizedSkillQuery = skillQuery.trim().toLowerCase();
    return agents.filter((agent) => (
      matchesAgent(agent, normalizedAgentQuery)
      && matchesSkill(agent, normalizedSkillQuery)
      && matchesStatus(agent, statusFilter)
    ));
  }, [agents, agentQuery, skillQuery, statusFilter]);

  if (isLoading) {
    return <PageSkeleton />;
  }

  if (error) {
    const message = error instanceof Error ? error.message : "Unknown roster error";
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-6">
        <EmptyState
          icon={AlertTriangle}
          message="Could not load Hermes Agency roster"
        />
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-center text-sm text-destructive">
          {message}
        </p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6">
        <EmptyState icon={Bot} message="No Hermes Agency roster data" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-6">
      <header className="flex flex-col gap-2">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Bot className="h-4 w-4" />
          Hermes Agency workforce
        </div>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Hermes Agency roster</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Read-only visibility into the delegable Hermes Agency specialists. Offline agents stay visible as valid targets;
            wake/profile failures are surfaced so routing problems are actionable instead of hidden.
          </p>
        </div>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Roster summary">
        <SummaryCard label="Total agents" value={data.total} icon={Users} />
        <SummaryCard label="Online" value={data.online} icon={Wifi} />
        <SummaryCard label="Offline" value={data.offline} icon={WifiOff} />
        <SummaryCard label="Wake failed" value={wakeFailed} icon={AlertTriangle} />
      </section>
      <div className="sr-only">{data.online} online · {data.offline} offline · {wakeFailed} wake failed</div>

      <section className="rounded-xl border border-border bg-card p-4 shadow-sm" aria-label="Roster filters">
        <div className="grid gap-3 lg:grid-cols-[1fr_1fr_180px]">
          <label className="flex flex-col gap-1 text-sm font-medium">
            Search agents
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                aria-label="Search agents"
                className="pl-9"
                placeholder="name, description, model"
                value={agentQuery}
                onChange={(event) => setAgentQuery(event.target.value)}
              />
            </div>
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium">
            Search skills
            <Input
              aria-label="Search skills"
              placeholder="api, design, research"
              value={skillQuery}
              onChange={(event) => setSkillQuery(event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium">
            Status
            <select
              aria-label="Status filter"
              className="h-10 rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
            >
              <option value="all">All statuses</option>
              <option value="online">Online</option>
              <option value="offline">Offline</option>
              <option value="wake_failed">Wake failed</option>
            </select>
          </label>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <Clock className="h-3.5 w-3.5" />
          Showing {filteredAgents.length} of {agents.length} agents · source filter: {data.filter}
        </div>
      </section>

      {dispatchMutation.error ? (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
          Dispatch failed: {dispatchMutation.error instanceof Error ? dispatchMutation.error.message : "unknown error"}
        </div>
      ) : null}

      {latestDispatch ? (
        <section className="rounded-xl border border-border bg-card p-4 shadow-sm" aria-label="Latest dispatch status">
          <div className="text-sm font-semibold">Latest dispatch</div>
          <div className="mt-2 grid gap-2 text-sm text-muted-foreground sm:grid-cols-4">
            <div>Status: <span className="font-medium text-foreground">{latestDispatch.status}</span></div>
            <div>Mode: <span className="font-medium text-foreground">{latestDispatch.mode}</span></div>
            <div>Queue: <span className="font-medium text-foreground">{formatNullable(latestDispatch.queueId)}</span></div>
            <div>Task: <span className="font-medium text-foreground">{formatNullable(latestDispatch.taskId)}</span></div>
          </div>
          {latestDispatch.artifacts.length > 0 ? (
            <div className="mt-3 rounded-lg bg-muted p-3 text-xs text-muted-foreground">
              Artifacts: {latestDispatch.artifacts.map((artifact) => artifact.text ?? artifact.path ?? artifact.url ?? artifact.type).join(", ")}
            </div>
          ) : null}
        </section>
      ) : null}

      {filteredAgents.length === 0 ? (
        <div className="rounded-xl border border-border bg-card">
          <EmptyState icon={Bot} message="No agents match these filters" />
          <p className="-mt-10 pb-10 text-center text-sm text-muted-foreground">
            Clear the search or choose another status.
          </p>
        </div>
      ) : (
        <section className="grid gap-3" aria-label="Agents">
          {filteredAgents.map((agent) => (
            <AgentCard
              key={agent.name}
              agent={agent}
              onDispatch={(selectedAgent) => dispatchMutation.mutate(selectedAgent)}
              isDispatching={dispatchMutation.isPending}
            />
          ))}
        </section>
      )}
    </div>
  );
}
