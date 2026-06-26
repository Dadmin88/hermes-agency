import { useHealth, useTasks, useEvents, useRoster } from "@/api/queries";
import PageHeader from "@/components/PageHeader";
import MetricCard from "@/components/MetricCard";
import GlassCard from "@/components/GlassCard";
import StatusStrip from "@/components/StatusStrip";
import Skeleton from "@/components/Skeleton";
import ErrorState from "@/components/ErrorState";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import { formatRelative } from "@/lib/format";
import {
  Activity, Users, ListTodo, Zap, Server, Database, Send, Stethoscope,
} from "lucide-react";
import { Link } from "react-router-dom";

export default function OverviewPage() {
  const health = useHealth();
  const tasks = useTasks();
  const events = useEvents(10);
  const roster = useRoster();

  if (health.isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton variant="rect" className="h-8 w-48" />
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} variant="card" />
          ))}
        </div>
      </div>
    );
  }

  if (health.error) {
    return (
      <ErrorState
        title="Cannot load dashboard"
        message={health.error.message}
        onRetry={health.refetch}
      />
    );
  }

  const h = health.data;
  const allTasks = tasks.data ?? [];
  const activeTasks = allTasks.filter((t) => ["active", "working", "queued"].includes(t.status));
  const recentEvents = events.data ?? [];
  const totalAgents = roster.data?.total_agents ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Overview"
        description="Hermes Agency system status at a glance"
      />

      {/* Status strip */}
      <StatusStrip />

      {/* Metric cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <MetricCard
          label="Agents"
          value={totalAgents}
          subtitle={roster.data ? `${roster.data.departments.length} departments` : undefined}
          icon={<Users className="h-5 w-5" />}
          accent="cyan"
        />
        <MetricCard
          label="Active Tasks"
          value={activeTasks.length}
          subtitle={`${allTasks.length} total`}
          icon={<ListTodo className="h-5 w-5" />}
          accent="violet"
        />
        <MetricCard
          label="Online Peers"
          value={h?.registry.online_peers ?? 0}
          subtitle={`of ${h?.registry.total_peers ?? 0}`}
          icon={<Server className="h-5 w-5" />}
          accent="emerald"
        />
        <MetricCard
          label="Events"
          value={recentEvents.length}
          subtitle="recent"
          icon={<Activity className="h-5 w-5" />}
          accent="amber"
        />
      </div>

      {/* Bottom grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* System status */}
        <GlassCard>
          <h3 className="text-sm font-semibold text-slate-300 mb-4">System Status</h3>
          <div className="space-y-3">
            <StatusRow
              icon={<Server className="h-4 w-4" />}
              label="Daemon"
              value={h?.daemon.status ?? "unknown"}
              status={h?.daemon.status === "running" ? "ok" : "warn"}
            />
            <StatusRow
              icon={<Database className="h-4 w-4" />}
              label="Registry"
              value={h?.registry.status ?? "unknown"}
              status={h?.registry.status === "ok" ? "ok" : "warn"}
            />
            <StatusRow
              icon={<Zap className="h-4 w-4" />}
              label="Model Set"
              value={h?.model_set.name ?? "unknown"}
              status="ok"
            />
            <StatusRow
              icon={<Activity className="h-4 w-4" />}
              label="Version"
              value={h?.version ?? "—"}
              status="ok"
            />
          </div>
        </GlassCard>

        {/* Recent activity */}
        <GlassCard>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-slate-300">Recent Activity</h3>
            <Link to="/activity">
              <Button variant="ghost" size="sm">View all</Button>
            </Link>
          </div>
          {recentEvents.length === 0 ? (
            <p className="text-sm text-slate-500 py-8 text-center">No recent events</p>
          ) : (
            <div className="space-y-2">
              {recentEvents.slice(0, 6).map((evt) => (
                <div
                  key={evt.id}
                  className="flex items-start gap-3 rounded-lg bg-slate-800/30 px-3 py-2"
                >
                  <Badge variant="status" status={evt.severity} size="sm">
                    {evt.severity}
                  </Badge>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-300 truncate">{evt.message}</p>
                    <p className="text-xs text-slate-600">{formatRelative(evt.timestamp)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      </div>

      {/* Quick actions */}
      <GlassCard>
        <h3 className="text-sm font-semibold text-slate-300 mb-4">Quick Actions</h3>
        <div className="flex flex-wrap gap-3">
          <Link to="/dispatch">
            <Button variant="primary" size="sm">
              <Send className="h-4 w-4" /> Dispatch Task
            </Button>
          </Link>
          <Link to="/diagnostics">
            <Button variant="secondary" size="sm">
              <Stethoscope className="h-4 w-4" /> Run Diagnostics
            </Button>
          </Link>
          <Link to="/agents">
            <Button variant="secondary" size="sm">
              <Users className="h-4 w-4" /> Browse Agents
            </Button>
          </Link>
        </div>
      </GlassCard>
    </div>
  );
}

function StatusRow({
  icon, label, value, status,
}: {
  icon: React.ReactNode; label: string; value: string; status: string;
}) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-slate-800/30 px-3 py-2.5">
      <div className="flex items-center gap-2 text-sm text-slate-400">
        {icon}
        <span>{label}</span>
      </div>
      <Badge variant="status" status={status} size="sm">
        {value}
      </Badge>
    </div>
  );
}
