import { cn } from "@/lib/cn";
import { useHealth } from "@/api/queries";
import { CircleDot, Cpu, Menu } from "lucide-react";

interface TopBarProps {
  onMenuToggle: () => void;
}

export default function TopBar({ onMenuToggle }: TopBarProps) {
  const { data: health } = useHealth();
  const isHealthy = health?.status === "ok" || health?.status === "healthy";

  return (
    <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-800 bg-slate-950/80 backdrop-blur-xl px-4 py-3 lg:px-6">
      <div className="flex items-center gap-3">
        <button
          onClick={onMenuToggle}
          className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-slate-200 lg:hidden transition-colors"
        >
          <Menu className="h-5 w-5" />
        </button>
      </div>

      <div className="flex items-center gap-4">
        {/* Health indicator */}
        <div className="flex items-center gap-2 rounded-full bg-slate-800/60 px-3 py-1.5">
          <CircleDot
            className={cn(
              "h-3 w-3",
              isHealthy ? "text-emerald-400 animate-pulse-slow" : "text-amber-400"
            )}
          />
          <span className="text-xs font-medium text-slate-400">
            {isHealthy ? "Healthy" : health?.status ?? "Unknown"}
          </span>
        </div>

        {/* Model set */}
        {health?.model_set && (
          <div className="hidden sm:flex items-center gap-2 rounded-full bg-slate-800/60 px-3 py-1.5">
            <Cpu className="h-3.5 w-3.5 text-violet-400" />
            <span className="text-xs font-medium text-slate-400">
              {health.model_set.name}
            </span>
          </div>
        )}

        {/* Profile */}
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-cyan-500 to-violet-500 text-xs font-bold text-white">
            H
          </div>
        </div>
      </div>
    </header>
  );
}
