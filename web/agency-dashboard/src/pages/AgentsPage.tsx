import { useState, useMemo } from "react";
import PageHeader from "@/components/PageHeader";
import GlassCard from "@/components/GlassCard";
import Badge from "@/components/Badge";
import Input from "@/components/Input";
import Select from "@/components/Select";
import Drawer from "@/components/Drawer";
import Skeleton from "@/components/Skeleton";
import EmptyState from "@/components/EmptyState";
import ErrorState from "@/components/ErrorState";
import { useRoster } from "@/api/queries";
import type { AgentCard } from "@/api/types";
import { Search, Users, Eye, EyeOff } from "lucide-react";

export default function AgentsPage() {
  const { data, isLoading, error, refetch } = useRoster();
  const [search, setSearch] = useState("");
  const [deptFilter, setDeptFilter] = useState("");
  const [skillFilter, setSkillFilter] = useState("");
  const [selected, setSelected] = useState<AgentCard | null>(null);

  const agents = data?.agents ?? [];
  const departments = data?.departments ?? [];
  const allSkills = [...new Set(agents.flatMap((a) => a.skills))].sort();

  const filtered = useMemo(() => {
    return agents.filter((a) => {
      if (search && !a.name.toLowerCase().includes(search.toLowerCase()) &&
          !a.id.toLowerCase().includes(search.toLowerCase())) return false;
      if (deptFilter && a.department !== deptFilter) return false;
      if (skillFilter && !a.skills.includes(skillFilter)) return false;
      return true;
    });
  }, [agents, search, deptFilter, skillFilter]);

  if (isLoading) return <Skeleton lines={8} />;
  if (error) return <ErrorState message={error.message} onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agents"
        description={`${agents.length} agents across ${departments.length} departments`}
      />

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="w-64">
          <Input
            placeholder="Search agents…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="w-48">
          <Select
            value={deptFilter}
            onChange={(e) => setDeptFilter(e.target.value)}
            options={departments.map((d) => ({ value: d, label: d }))}
            placeholder="All departments"
          />
        </div>
        <div className="w-48">
          <Select
            value={skillFilter}
            onChange={(e) => setSkillFilter(e.target.value)}
            options={allSkills.map((s) => ({ value: s, label: s }))}
            placeholder="All skills"
          />
        </div>
      </div>

      {/* Agent grid */}
      {filtered.length === 0 ? (
        <EmptyState
          title="No agents found"
          description="Try adjusting your filters"
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filtered.map((agent) => (
            <GlassCard
              key={agent.id}
              hover
              className="cursor-pointer"
              onClick={() => setSelected(agent)}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-500/20 to-violet-500/20 text-sm font-bold text-cyan-400">
                  {agent.name.slice(0, 2).toUpperCase()}
                </div>
                <div className="flex items-center gap-1.5">
                  {agent.discoverable ? (
                    <Eye className="h-3.5 w-3.5 text-emerald-400" />
                  ) : (
                    <EyeOff className="h-3.5 w-3.5 text-slate-600" />
                  )}
                  <Badge variant="status" status={agent.status} size="sm">
                    {agent.status}
                  </Badge>
                </div>
              </div>
              <h3 className="text-sm font-semibold text-slate-200 truncate">{agent.name}</h3>
              <p className="text-xs text-slate-500 mt-0.5">{agent.department}</p>
              <p className="text-xs text-slate-600 mt-1 line-clamp-2">{agent.role}</p>
              <div className="mt-3 flex flex-wrap gap-1">
                {agent.skills.slice(0, 3).map((s) => (
                  <span key={s} className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-500">
                    {s}
                  </span>
                ))}
                {agent.skills.length > 3 && (
                  <span className="text-[10px] text-slate-600">+{agent.skills.length - 3}</span>
                )}
              </div>
            </GlassCard>
          ))}
        </div>
      )}

      {/* Agent detail drawer */}
      <Drawer
        open={!!selected}
        onClose={() => setSelected(null)}
        title={selected?.name ?? "Agent"}
      >
        {selected && (
          <div className="space-y-6">
            <div>
              <p className="text-xs text-slate-500 mb-1">ID</p>
              <p className="text-sm font-mono text-slate-300">{selected.id}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Department</p>
              <p className="text-sm text-slate-300">{selected.department}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Role</p>
              <p className="text-sm text-slate-300">{selected.role}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Description</p>
              <p className="text-sm text-slate-300">{selected.description || "No description"}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Status</p>
              <Badge variant="status" status={selected.status}>{selected.status}</Badge>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Discoverable</p>
              <p className="text-sm text-slate-300">{selected.discoverable ? "Yes" : "No"}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-2">Skills ({selected.skills.length})</p>
              <div className="flex flex-wrap gap-1.5">
                {selected.skills.map((s) => (
                  <Badge key={s} variant="outline" size="sm">{s}</Badge>
                ))}
              </div>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
