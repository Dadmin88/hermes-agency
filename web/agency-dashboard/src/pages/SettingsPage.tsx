import { useEffect, useMemo, useState } from "react";
import PageHeader from "@/components/PageHeader";
import GlassCard from "@/components/GlassCard";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import Skeleton from "@/components/Skeleton";
import ErrorState from "@/components/ErrorState";
import Select from "@/components/Select";
import { useConfig, useHealth, useModelSets, useSetActiveModelSet } from "@/api/queries";
import type { ModelSetSummary } from "@/api/types";
import { addToast } from "@/hooks/useToast";
import {
  Settings,
  Server,
  Shield,
  Cpu,
  Info,
  CheckCircle,
  AlertTriangle,
  Database,
} from "lucide-react";

export default function SettingsPage() {
  const config = useConfig();
  const health = useHealth();
  const modelSets = useModelSets();
  const setActiveModelSet = useSetActiveModelSet();
  const [selectedModelSet, setSelectedModelSet] = useState("");

  useEffect(() => {
    if (config.data?.active_model_set) {
      setSelectedModelSet(config.data.active_model_set);
    }
  }, [config.data?.active_model_set]);

  const cfg = config.data;
  const h = health.data;
  const modelSetSummaries = modelSets.data?.model_sets ?? [];
  const availableModelSets = useMemo(() => {
    const names = new Set<string>();
    cfg?.available_model_sets?.forEach((name) => names.add(name));
    modelSetSummaries.forEach((modelSet) => names.add(modelSet.name));
    return Array.from(names).sort();
  }, [cfg?.available_model_sets, modelSetSummaries]);

  const activeSummary = modelSetSummaries.find((ms) => ms.name === cfg?.active_model_set);

  if (config.isLoading || health.isLoading) return <Skeleton lines={8} />;
  if (config.error) return <ErrorState message={config.error.message} onRetry={config.refetch} />;

  const activateModelSet = (name: string) => {
    if (!name || name === cfg?.active_model_set) return;
    setActiveModelSet.mutate(
      { name, persist: true },
      {
        onSuccess: (result) => {
          addToast(
            "success",
            `Model set changed to ${result.active_model_set}${result.persisted ? " and saved" : ""}`
          );
        },
        onError: (err) => {
          addToast("error", `Model set change failed: ${err.message}`);
        },
      }
    );
  };

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
            <SettingsRow label="Profile" value={h?.active_profile ?? "—"} />
            <SettingsRow label="Profile Home" value={h?.profile_home ?? "—"} />
            <SettingsRow label="Framework" value="Vite + React + TypeScript" />
          </div>
        </GlassCard>

        {/* Runtime model set switcher */}
        <GlassCard>
          <div className="flex items-center gap-2 mb-4">
            <Cpu className="h-5 w-5 text-violet-400" />
            <h3 className="text-sm font-semibold text-slate-300">Model Set Control</h3>
          </div>
          <div className="space-y-4">
            <div className="rounded-xl border border-violet-500/20 bg-violet-500/10 p-3">
              <p className="text-xs uppercase tracking-wide text-violet-300/80">Active model set</p>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <p className="text-lg font-semibold text-slate-100">{cfg?.active_model_set ?? "—"}</p>
                <Badge variant="status" status="active" size="sm">runtime</Badge>
                <Badge variant="outline" size="sm">persisted config</Badge>
              </div>
              {activeSummary?.description && (
                <p className="mt-2 text-sm text-slate-400">{activeSummary.description}</p>
              )}
            </div>

            <div className="flex flex-col sm:flex-row gap-3 items-end">
              <Select
                label="Switch model set"
                value={selectedModelSet}
                onChange={(e) => setSelectedModelSet(e.target.value)}
                options={availableModelSets.map((name) => ({ value: name, label: name }))}
                placeholder="Choose a model set"
              />
              <Button
                className="w-full sm:w-auto"
                loading={setActiveModelSet.isPending}
                disabled={!selectedModelSet || selectedModelSet === cfg?.active_model_set}
                onClick={() => activateModelSet(selectedModelSet)}
              >
                Activate
              </Button>
            </div>
            <p className="text-xs text-slate-500">
              Changing this updates the running dashboard process immediately and writes
              <span className="font-mono text-slate-400"> agency.models.active_set </span>
              to the active Hermes profile config.
            </p>
          </div>
        </GlassCard>

        {/* Agency runtime */}
        <GlassCard>
          <div className="flex items-center gap-2 mb-4">
            <Server className="h-5 w-5 text-emerald-400" />
            <h3 className="text-sm font-semibold text-slate-300">Agency Runtime</h3>
          </div>
          <div className="space-y-3">
            <SettingsRow
              label="Active Model Set"
              value={cfg?.active_model_set ?? "—"}
            />
            <SettingsRow
              label="Daemon Status"
              value={cfg?.daemon_status ?? "—"}
            />
            <SettingsRow
              label="Profile Home"
              value={cfg?.profile_home ?? "—"}
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
              label="Auto Allow Team"
              value={cfg?.security?.auto_allow_team ? "Yes" : "No"}
            />
            {cfg?.security?.allowlist && (
              <SettingsRow
                label="Allowlist"
                value={`${cfg.security.allowlist.length} entries`}
              />
            )}
          </div>
        </GlassCard>
      </div>

      {/* Model set catalog */}
      <GlassCard>
        <div className="flex items-center justify-between gap-4 mb-4">
          <div className="flex items-center gap-2">
            <Database className="h-5 w-5 text-cyan-400" />
            <h3 className="text-sm font-semibold text-slate-300">Model Set Catalog</h3>
          </div>
          <Badge variant="outline" size="sm">
            {modelSets.data?.count ?? availableModelSets.length} available
          </Badge>
        </div>

        {modelSets.isLoading ? (
          <Skeleton lines={4} />
        ) : modelSets.error ? (
          <ErrorState message={modelSets.error.message} onRetry={modelSets.refetch} />
        ) : modelSetSummaries.length === 0 ? (
          <p className="text-sm text-slate-500">No model sets configured</p>
        ) : (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
            {modelSetSummaries.map((modelSet) => (
              <ModelSetCard
                key={modelSet.name}
                modelSet={modelSet}
                active={modelSet.name === cfg?.active_model_set}
                loading={setActiveModelSet.isPending}
                onActivate={() => activateModelSet(modelSet.name)}
              />
            ))}
          </div>
        )}
      </GlassCard>

      {/* Clear cache */}
      <GlassCard>
        <div className="flex items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-300">Cache</h3>
            <p className="text-xs text-slate-500 mt-1">Clear local browser state and reload the dashboard shell</p>
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
    <div className="flex items-center justify-between gap-4 rounded-lg bg-slate-800/30 px-3 py-2">
      <span className="text-sm text-slate-400">{label}</span>
      <span className="text-sm text-slate-200 font-medium text-right break-all">{value}</span>
    </div>
  );
}

function ModelSetCard({
  modelSet,
  active,
  loading,
  onActivate,
}: {
  modelSet: ModelSetSummary;
  active: boolean;
  loading: boolean;
  onActivate: () => void;
}) {
  const families = Object.entries(modelSet.families ?? {});
  const profileCount = Object.keys(modelSet.profiles ?? {}).length;
  const warnings = modelSet.validation?.warnings ?? [];
  const errors = modelSet.validation?.errors ?? [];
  const ok = errors.length === 0 && !modelSet.error;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold text-slate-100 truncate">{modelSet.name}</h4>
            {active && <Badge variant="status" status="active" size="sm">active</Badge>}
            {ok ? (
              <Badge variant="status" status="success" size="sm">valid</Badge>
            ) : (
              <Badge variant="status" status="error" size="sm">check</Badge>
            )}
          </div>
          {modelSet.description && (
            <p className="mt-2 text-sm text-slate-400 line-clamp-2">{modelSet.description}</p>
          )}
        </div>
        <Button
          variant={active ? "ghost" : "secondary"}
          size="sm"
          disabled={active}
          loading={loading && !active}
          onClick={onActivate}
        >
          {active ? <CheckCircle className="h-4 w-4" /> : null}
          {active ? "Active" : "Use"}
        </Button>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg bg-slate-800/40 px-3 py-2">
          <p className="text-slate-500">Families</p>
          <p className="font-semibold text-slate-200">{families.length}</p>
        </div>
        <div className="rounded-lg bg-slate-800/40 px-3 py-2">
          <p className="text-slate-500">Profiles</p>
          <p className="font-semibold text-slate-200">{profileCount || "default"}</p>
        </div>
      </div>

      {families.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {families.slice(0, 3).map(([familyName, family]) => (
            <div key={familyName} className="flex items-center justify-between gap-2 text-xs">
              <span className="text-slate-500 truncate">{familyName}</span>
              <span className="font-mono text-slate-300 truncate text-right">
                {family.provider}/{family.model}
              </span>
            </div>
          ))}
          {families.length > 3 && (
            <p className="text-xs text-slate-600">+{families.length - 3} more families</p>
          )}
        </div>
      )}

      {(warnings.length > 0 || errors.length > 0 || modelSet.error) && (
        <div className="mt-3 rounded-lg bg-amber-500/10 border border-amber-500/20 p-2 text-xs text-amber-300">
          <div className="flex items-center gap-1.5 font-medium">
            <AlertTriangle className="h-3.5 w-3.5" /> Validation notes
          </div>
          <p className="mt-1 text-amber-200/80">
            {modelSet.error || errors[0] || warnings[0]}
            {(errors.length + warnings.length > 1) && " …"}
          </p>
        </div>
      )}
    </div>
  );
}
