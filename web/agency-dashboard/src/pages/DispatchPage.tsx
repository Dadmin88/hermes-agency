import { useState } from "react";
import PageHeader from "@/components/PageHeader";
import GlassCard from "@/components/GlassCard";
import Textarea from "@/components/Textarea";
import Input from "@/components/Input";
import Select from "@/components/Select";
import Button from "@/components/Button";
import Badge from "@/components/Badge";
import { useDispatchTask, useRoster } from "@/api/queries";
import { addToast } from "@/hooks/useToast";
import { Send, CheckCircle } from "lucide-react";

export default function DispatchPage() {
  const [message, setMessage] = useState("");
  const [skill, setSkill] = useState("");
  const [department, setDepartment] = useState("");
  const [targetAgent, setTargetAgent] = useState("");
  const [priority, setPriority] = useState("medium");
  const [createKanban, setCreateKanban] = useState(false);

  const dispatch = useDispatchTask();
  const roster = useRoster();

  const departments = roster.data?.departments ?? [];
  const agents = roster.data?.agents ?? [];
  const skills = [...new Set(agents.flatMap((a) => a.skills))].sort();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!message.trim()) return;

    dispatch.mutate(
      {
        message: message.trim(),
        skill: skill || undefined,
        department: department || undefined,
        target_agent: targetAgent || undefined,
        priority: priority as "low" | "medium" | "high" | "critical",
        create_kanban_task: createKanban,
      },
      {
        onSuccess: (result) => {
          addToast("success", `Task dispatched: ${result.message}`);
          setMessage("");
        },
        onError: (err) => {
          addToast("error", `Dispatch failed: ${err.message}`);
        },
      }
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dispatch"
        description="Send a task to the agent network"
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Dispatch form */}
        <div className="lg:col-span-2">
          <GlassCard>
            <form onSubmit={handleSubmit} className="space-y-5">
              <Textarea
                label="Message"
                placeholder="Describe what you need done…"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={4}
              />

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Select
                  label="Department"
                  value={department}
                  onChange={(e) => setDepartment(e.target.value)}
                  options={departments.map((d) => ({ value: d, label: d }))}
                  placeholder="Any department"
                />
                <Select
                  label="Skill"
                  value={skill}
                  onChange={(e) => setSkill(e.target.value)}
                  options={skills.map((s) => ({ value: s, label: s }))}
                  placeholder="Any skill"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Input
                  label="Target Agent ID"
                  placeholder="Leave blank for auto-routing"
                  value={targetAgent}
                  onChange={(e) => setTargetAgent(e.target.value)}
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

              <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={createKanban}
                  onChange={(e) => setCreateKanban(e.target.checked)}
                  className="rounded border-slate-600 bg-slate-800 text-cyan-500 focus:ring-cyan-500/40"
                />
                Create Kanban task
              </label>

              <Button
                type="submit"
                variant="primary"
                size="lg"
                loading={dispatch.isPending}
                disabled={!message.trim()}
              >
                <Send className="h-4 w-4" />
                Dispatch
              </Button>
            </form>
          </GlassCard>
        </div>

        {/* Result / help */}
        <div className="space-y-6">
          {dispatch.isSuccess && dispatch.data && (
            <GlassCard>
              <div className="flex items-center gap-2 mb-3">
                <CheckCircle className="h-5 w-5 text-emerald-400" />
                <h3 className="text-sm font-semibold text-emerald-400">Dispatched</h3>
              </div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-500">Task ID</span>
                  <span className="text-slate-200 font-mono text-xs">{dispatch.data.task_id}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Status</span>
                  <Badge variant="status" status={dispatch.data.status}>
                    {dispatch.data.status}
                  </Badge>
                </div>
                {dispatch.data.assigned_agent && (
                  <div className="flex justify-between">
                    <span className="text-slate-500">Assigned</span>
                    <span className="text-slate-200">{dispatch.data.assigned_agent}</span>
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
            <h3 className="text-sm font-semibold text-slate-300 mb-3">Tips</h3>
            <ul className="space-y-2 text-sm text-slate-500">
              <li>• Be specific in your message for best results</li>
              <li>• Departments route to specialized agent groups</li>
              <li>• Skills match agents by their registered capabilities</li>
              <li>• Auto-routing picks the best available agent</li>
            </ul>
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
