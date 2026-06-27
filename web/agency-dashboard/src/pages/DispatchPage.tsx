import { useEffect, useMemo, useState } from "react";
import PageHeader from "@/components/PageHeader";
import GlassCard from "@/components/GlassCard";
import Textarea from "@/components/Textarea";
import Select from "@/components/Select";
import Button from "@/components/Button";
import Badge from "@/components/Badge";
import { useDispatchTask, useRoster } from "@/api/queries";
import { addToast } from "@/hooks/useToast";
import { Send, CheckCircle, Radio, Moon, Kanban } from "lucide-react";

export default function DispatchPage() {
  const [message, setMessage] = useState("");
  const [skill, setSkill] = useState("");
  const [department, setDepartment] = useState("");
  const [targetAgent, setTargetAgent] = useState("");
  const [priority, setPriority] = useState("medium");
  const [createKanban, setCreateKanban] = useState(true);

  const dispatch = useDispatchTask();
  const roster = useRoster();

  const departments = roster.data ?? [];
  const departmentNames = departments.map((d) => d.name);
  const agents = departments.flatMap((d) => d.agents).sort((a, b) => a.name.localeCompare(b.name));
  const selectedAgent = agents.find((a) => a.name === targetAgent);
  const visibleAgents = useMemo(() => {
    if (!department) return agents;
    return agents.filter((agent) => agent.department === department);
  }, [agents, department]);
  const skills = [...new Set(agents.flatMap((a) => a.skills))].sort();

  useEffect(() => {
    if (!targetAgent) return;
    const agent = agents.find((a) => a.name === targetAgent);
    if (agent && department && agent.department !== department) {
      setTargetAgent("");
    }
  }, [agents, department, targetAgent]);

  const handleTargetChange = (name: string) => {
    setTargetAgent(name);
    const agent = agents.find((a) => a.name === name);
    if (agent) setDepartment(agent.department);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!message.trim()) return;

    dispatch.mutate(
      {
        message: message.trim(),
        skill: skill || undefined,
        department: department || undefined,
        target_agent: targetAgent || undefined,
        priority,
        create_kanban_task: createKanban,
      },
      {
        onSuccess: (result) => {
          if (!result.ok) {
            addToast("warning", result.error_text || "Dispatch returned a warning");
            return;
          }
          addToast(
            "success",
            `Task dispatched to ${result.target ?? "auto-router"}: task ${result.task_id ?? "pending"}`
          );
          setMessage("");
        },
        onError: (err) => addToast("error", `Dispatch failed: ${err.message}`),
      }
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dispatch"
        description="Send a task to a specific agent, department, skill, or the auto-router"
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <GlassCard>
            <form onSubmit={handleSubmit} className="space-y-5">
              <Textarea
                label="Message"
                placeholder="Describe what you need done…"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={6}
              />

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Select
                  label="Department"
                  value={department}
                  onChange={(e) => setDepartment(e.target.value)}
                  options={departmentNames.map((d) => ({ value: d, label: d }))}
                  placeholder="Any department"
                />
                <Select
                  label="Target Agent"
                  value={targetAgent}
                  onChange={(e) => handleTargetChange(e.target.value)}
                  options={visibleAgents.map((agent) => ({
                    value: agent.name,
                    label: `${agent.label || agent.name} · ${agent.name} · ${agent.online ? "online" : "offline"}`,
                  }))}
                  placeholder={department ? `Any ${department} agent` : "Any agent / auto-route"}
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Select
                  label="Skill"
                  value={skill}
                  onChange={(e) => setSkill(e.target.value)}
                  options={skills.map((s) => ({ value: s, label: s }))}
                  placeholder="Any skill"
                />
                <Select
                  label="Priority"
                  value={priority}
                  onChange={(e) => setPriority(e.target.value)}
                  options={[
                    { value: "low", label: "Low" },
                    { value: "medium", label: "Medium" },
                    { value: "high", label: "High" },
                    { value: "critical", label: "Critical" },
                  ]}
                />
              </div>

              {selectedAgent && (
                <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="status" status={selectedAgent.online ? "online" : "queued"} size="sm">
                      {selectedAgent.online ? "online" : "offline / starts on dispatch"}
                    </Badge>
                    <Badge variant="outline" size="sm">{selectedAgent.department}</Badge>
                    <Badge variant="outline" size="sm">discoverable</Badge>
                  </div>
                  <p className="mt-2 text-sm font-medium text-slate-200">{selectedAgent.name}</p>
                  <p className="mt-1 text-xs text-slate-500">{selectedAgent.description || selectedAgent.label}</p>
                  <p className="mt-2 text-xs text-slate-600">
                    Dispatch uses the pool sender, starts this agent when needed, and creates the Kanban task on its department board.
                  </p>
                </div>
              )}

              <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={createKanban}
                  onChange={(e) => setCreateKanban(e.target.checked)}
                  className="rounded border-slate-600 bg-slate-800 text-cyan-500 focus:ring-cyan-500/40"
                />
                Create and route Kanban task
              </label>

              <Button type="submit" variant="primary" size="lg" loading={dispatch.isPending} disabled={!message.trim()}>
                <Send className="h-4 w-4" /> Dispatch
              </Button>
            </form>
          </GlassCard>
        </div>

        <div className="space-y-6">
          {dispatch.isSuccess && dispatch.data && (
            <GlassCard className={dispatch.data.ok ? "" : "border-amber-500/20"}>
              <div className="flex items-center gap-2 mb-3">
                <CheckCircle className="h-5 w-5 text-emerald-400" />
                <h3 className="text-sm font-semibold text-emerald-400">Dispatch Result</h3>
              </div>
              <div className="space-y-2 text-sm">
                <ResultRow label="Task ID" value={dispatch.data.task_id ?? "—"} mono />
                {dispatch.data.kanban_task_id && <ResultRow label="Kanban Task" value={dispatch.data.kanban_task_id} mono />}
                {dispatch.data.target && <ResultRow label="Target" value={dispatch.data.target} />}
                {dispatch.data.result_text && (
                  <div className="mt-2">
                    <p className="text-xs text-slate-500 mb-1">Result</p>
                    <p className="text-sm text-slate-300 whitespace-pre-wrap">{dispatch.data.result_text}</p>
                  </div>
                )}
                {dispatch.data.error_text && (
                  <div className="mt-2">
                    <p className="text-xs text-red-400 mb-1">Error</p>
                    <p className="text-sm text-red-300 whitespace-pre-wrap">{dispatch.data.error_text}</p>
                  </div>
                )}
              </div>
            </GlassCard>
          )}

          {dispatch.isError && (
            <GlassCard className="border-red-500/20">
              <p className="text-sm text-red-400">{dispatch.error.message}</p>
            </GlassCard>
          )}

          <GlassCard>
            <h3 className="text-sm font-semibold text-slate-300 mb-3">Routing</h3>
            <ul className="space-y-3 text-sm text-slate-500">
              <li className="flex gap-2"><Radio className="h-4 w-4 text-emerald-400 mt-0.5" /> Online agents are sent directly through their peer ID.</li>
              <li className="flex gap-2"><Moon className="h-4 w-4 text-amber-400 mt-0.5" /> Offline agents are valid targets; dispatch starts them or queues the work.</li>
              <li className="flex gap-2"><Kanban className="h-4 w-4 text-violet-400 mt-0.5" /> Targeted tasks are assigned to the target and routed to that agent's department board.</li>
            </ul>
          </GlassCard>
        </div>
      </div>
    </div>
  );
}

function ResultRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-slate-500">{label}</span>
      <span className={`${mono ? "font-mono text-xs" : ""} text-slate-200 break-all text-right`}>{value}</span>
    </div>
  );
}
