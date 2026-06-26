import { useState, useMemo } from "react";
import PageHeader from "@/components/PageHeader";
import Badge from "@/components/Badge";
import Drawer from "@/components/Drawer";
import Skeleton from "@/components/Skeleton";
import EmptyState from "@/components/EmptyState";
import ErrorState from "@/components/ErrorState";
import Select from "@/components/Select";
import Input from "@/components/Input";
import { useEvents } from "@/api/queries";
import type { AgencyEvent } from "@/api/types";
import { formatRelative, formatDate, formatTime } from "@/lib/format";
import { Activity, Info, AlertTriangle, XCircle, Bug } from "lucide-react";

const severityIcons: Record<string, typeof Info> = {
  info: Info,
  warning: AlertTriangle,
  error: XCircle,
  debug: Bug,
};

export default function ActivityPage() {
  const [severityFilter, setSeverityFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<AgencyEvent | null>(null);
  const { data, isLoading, error, refetch } = useEvents(200);

  const events = data ?? [];
  const sources = [...new Set(events.map((e) => e.source))].sort();

  const filtered = useMemo(() => {
    return events.filter((e) => {
      if (severityFilter && e.severity !== severityFilter) return false;
      if (sourceFilter && e.source !== sourceFilter) return false;
      if (search && !e.message.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [events, severityFilter, sourceFilter, search]);

  if (isLoading) return <Skeleton lines={8} />;
  if (error) return <ErrorState message={error.message} onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Activity"
        description={`${events.length} events`}
      />

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="w-64">
          <Input
            placeholder="Search events…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="w-40">
          <Select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            options={[
              { value: "info", label: "Info" },
              { value: "warning", label: "Warning" },
              { value: "error", label: "Error" },
              { value: "debug", label: "Debug" },
            ]}
            placeholder="All severities"
          />
        </div>
        <div className="w-48">
          <Select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            options={sources.map((s) => ({ value: s, label: s }))}
            placeholder="All sources"
          />
        </div>
      </div>

      {/* Timeline */}
      {filtered.length === 0 ? (
        <EmptyState
          icon={<Activity className="h-8 w-8" />}
          title="No events"
          description="No events match your filters"
        />
      ) : (
        <div className="relative">
          <div className="absolute left-5 top-0 bottom-0 w-px bg-slate-800" />
          <div className="space-y-1">
            {filtered.map((evt) => {
              const Icon = severityIcons[evt.severity] ?? Info;
              return (
                <div
                  key={evt.id}
                  onClick={() => setSelected(evt)}
                  className="relative flex items-start gap-4 pl-12 py-3 cursor-pointer hover:bg-slate-800/20 rounded-lg transition-colors"
                >
                  <div className="absolute left-3 top-4 rounded-full bg-slate-950 p-1">
                    <Icon
                      className={`h-3.5 w-3.5 ${
                        evt.severity === "error"
                          ? "text-red-400"
                          : evt.severity === "warning"
                          ? "text-amber-400"
                          : evt.severity === "debug"
                          ? "text-slate-500"
                          : "text-cyan-400"
                      }`}
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-300">{evt.message}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-slate-600">{formatRelative(evt.timestamp)}</span>
                      <span className="text-xs text-slate-700">·</span>
                      <span className="text-xs text-slate-600">{evt.source}</span>
                      {evt.agent_id && (
                        <>
                          <span className="text-xs text-slate-700">·</span>
                          <span className="text-xs text-slate-600">{evt.agent_id}</span>
                        </>
                      )}
                    </div>
                  </div>
                  <Badge variant="status" status={evt.severity} size="sm">
                    {evt.severity}
                  </Badge>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Event detail drawer */}
      <Drawer
        open={!!selected}
        onClose={() => setSelected(null)}
        title="Event Details"
      >
        {selected && (
          <div className="space-y-4">
            <div>
              <p className="text-xs text-slate-500 mb-1">ID</p>
              <p className="text-sm font-mono text-slate-300">{selected.id}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Type</p>
              <p className="text-sm text-slate-300">{selected.event_type}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Severity</p>
              <Badge variant="status" status={selected.severity}>{selected.severity}</Badge>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Source</p>
              <p className="text-sm text-slate-300">{selected.source}</p>
            </div>
            {selected.agent_id && (
              <div>
                <p className="text-xs text-slate-500 mb-1">Agent</p>
                <p className="text-sm text-slate-300">{selected.agent_id}</p>
              </div>
            )}
            <div>
              <p className="text-xs text-slate-500 mb-1">Message</p>
              <p className="text-sm text-slate-300">{selected.message}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Timestamp</p>
              <p className="text-sm text-slate-300">
                {formatDate(selected.timestamp)} {formatTime(selected.timestamp)}
              </p>
            </div>
            {selected.details && (
              <div>
                <p className="text-xs text-slate-500 mb-1">Details</p>
                <pre className="rounded-lg bg-slate-800/60 p-3 text-xs text-slate-400 overflow-x-auto">
                  {JSON.stringify(selected.details, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </Drawer>
    </div>
  );
}
