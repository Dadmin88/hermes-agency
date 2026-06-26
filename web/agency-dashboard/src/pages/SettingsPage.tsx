import PageHeader from "@/components/PageHeader";
import GlassCard from "@/components/GlassCard";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import Skeleton from "@/components/Skeleton";
import ErrorState from "@/components/ErrorState";
import { useConfig, useHealth } from "@/api/queries";
import { addToast } from "@/hooks/useToast";
import {
  Settings, Server, Shield, Cpu, Zap, Info,
} from "lucide-react";

export default function SettingsPage() {
  const config = useConfig();
  const health = useHealth();

  if (config.isLoading || health.isLoading) return <Skeleton lines={8} />;
  if (config.error) return <ErrorState message={config.error.message} onRetry={config.refetch} />;

  const cfg = config.data;
  const h = health.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Dashboard and agency configuration"
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Dashboard info */}
        <GlassCard>
          <div className="flex items-center gap-2 mb-4">
            <Info className="h-5 w-5 text-cyan-400" />
            <h3 className="text-sm font-semibold text-slate-300">Dashboard</h3>
          </div>
          <div className="space-y-3">
            <SettingsRow label="Version" value={h?.version ?? "—"} />
            <SettingsRow label="API Status" value={h?.status ?? "unknown"} />
            <SettingsRow label="Framework" value="Vite + React + TypeScript" />
          </div>
        </GlassCard>

        {/* Model sets */}
        <GlassCard>
          <div className="flex items-center gap-2 mb-4">
            <Cpu className="h-5 w-5 text-violet-400" />
            <h3 className="text-sm font-semibold text-slate-300">Model Sets</h3>
          </div>
          {cfg?.model_sets && cfg.model_sets.length > 0 ? (
            <div className="space-y-2">
              {cfg.model_sets.map((ms) => (
                <div
                  key={ms.name}
                  className="flex items-center justify-between rounded-lg bg-slate-800/40 px-3 py-2.5"
                >
                  <div>
                    <p className="text-sm font-medium text-slate-200">{ms.name}</p>
                    <p className="text-xs text-slate-500">{ms.provider} · {ms.model}</p>
                  </div>
                  {ms.is_default && (
                    <Badge variant="status" status="active" size="sm">default</Badge>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-500">No model sets configured</p>
          )}
        </GlassCard>

        {/* Agency runtime */}
        <GlassCard>
          <div className="flex items-center gap-2 mb-4">
            <Server className="h-5 w-5 text-emerald-400" />
            <h3 className="text-sm font-semibold text-slate-300">Agency Runtime</h3>
          </div>
          <div className="space-y-3">
            <SettingsRow
              label="Enabled"
              value={cfg?.agency_enabled ? "Yes" : "No"}
            />
            <SettingsRow
              label="Daemon PID"
              value={cfg?.daemon_pid?.toString() ?? "—"}
            />
            <SettingsRow
              label="Registry Mode"
              value={cfg?.registry_mode ?? "—"}
            />
          </div>
        </GlassCard>

        {/* Security */}
        <GlassCard>
          <div className="flex items-center gap-2 mb-4">
            <Shield className="h-5 w-5 text-amber-400" />
            <h3 className="text-sm font-semibold text-slate-300">Security</h3>
          </div>
          <div className="space-y-3">
            <SettingsRow
              label="Remote Tasks"
              value={cfg?.security?.allow_remote_tasks ? "Allowed" : "Blocked"}
            />
            <SettingsRow
              label="Incoming Tool Access"
              value={cfg?.security?.incoming_tool_access ?? "—"}
            />
          </div>
        </GlassCard>
      </div>

      {/* Clear cache */}
      <GlassCard>
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-slate-300">Cache</h3>
            <p className="text-xs text-slate-500 mt-1">Clear React Query cache and reload</p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              localStorage.clear();
              window.location.reload();
            }}
          >
            Clear & Reload
          </Button>
        </div>
      </GlassCard>
    </div>
  );
}

function SettingsRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-slate-800/30 px-3 py-2">
      <span className="text-sm text-slate-400">{label}</span>
      <span className="text-sm text-slate-200 font-medium">{value}</span>
    </div>
  );
}
