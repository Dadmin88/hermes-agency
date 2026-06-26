import { cn } from "@/lib/cn";
import { useHealth } from "@/api/queries";
import {
  Activity,
  CircleDot,
  AlertTriangle,
} from "lucide-react";

export default function StatusStrip() {
  const { data: health, isLoading, error } = useHealth();

  if (isLoading) {
    return (
      <div className="glass-card-sm flex items-center gap-4 px-4 py-2">
        <div className="h-2 w-2 rounded-full bg-slate-600 animate-pulse" />
        <span className="text-xs text-slate-500">Connecting…</span>
      </div>
    );
  }

  if (error || !health) {
    return (
      <div className="glass-card-sm flex items-center gap-3 px-4 py-2">
        <AlertTriangle className="h-4 w-4 text-amber-400" />
        <span className="text-xs text-amber-400">API unreachable</span>
      </div>
    );
  }

  const isHealthy = health.status === "ok" || health.status === "healthy";

  return (
    <div className="glass-card-sm flex flex-wrap items-center gap-4 px-4 py-2 text-xs">
      <div className="flex items-center gap-2">
        <CircleDot
          className={cn(
            "h-3 w-3",
            isHealthy ? "text-emerald-400" : "text-amber-400"
          )}
        />
        <span className="text-slate-300 font-medium">
          {isHealthy ? "System OK" : "Degraded"}
        </span>
      </div>

      <div className="h-4 w-px bg-slate-800" />

      <div className="flex items-center gap-1.5">
        <Activity className="h-3.5 w-3.5 text-slate-500" />
        <span className="text-slate-400">
          Daemon: {health.daemon.status}
        </span>
      </div>

      <div className="h-4 w-px bg-slate-800" />

      <span className="text-slate-400">
        Peers: {health.registry.online_peers}/{health.registry.total_peers}
      </span>

      <div className="h-4 w-px bg-slate-800" />

      <span className="text-slate-400">
        Model: {health.model_set.name}
      </span>
    </div>
  );
}
