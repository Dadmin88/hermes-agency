import { type ReactNode } from "react";
import { cn } from "@/lib/cn";
import {
  TrendingUp,
  TrendingDown,
  Minus,
} from "lucide-react";

interface MetricCardProps {
  label: string;
  value: string | number;
  subtitle?: string;
  icon?: ReactNode;
  trend?: "up" | "down" | "flat";
  trendValue?: string;
  accent?: "cyan" | "emerald" | "amber" | "red" | "violet";
  className?: string;
}

export default function MetricCard({
  label,
  value,
  subtitle,
  icon,
  trend,
  trendValue,
  accent = "cyan",
  className,
}: MetricCardProps) {
  const accentMap = {
    cyan: "from-cyan-400/20 to-cyan-400/5 border-cyan-400/20",
    emerald: "from-emerald-400/20 to-emerald-400/5 border-emerald-400/20",
    amber: "from-amber-400/20 to-amber-400/5 border-amber-400/20",
    red: "from-red-400/20 to-red-400/5 border-red-400/20",
    violet: "from-violet-400/20 to-violet-400/5 border-violet-400/20",
  };

  const iconColor = {
    cyan: "text-cyan-400",
    emerald: "text-emerald-400",
    amber: "text-amber-400",
    red: "text-red-400",
    violet: "text-violet-400",
  };

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-2xl border bg-gradient-to-br p-6",
        accentMap[accent],
        className
      )}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-slate-400">{label}</p>
          <p className="mt-2 text-3xl font-bold text-slate-100">{value}</p>
          {subtitle && (
            <p className="mt-1 text-sm text-slate-500">{subtitle}</p>
          )}
          {trend && (
            <div className="mt-2 flex items-center gap-1 text-sm">
              {trend === "up" && (
                <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
              )}
              {trend === "down" && (
                <TrendingDown className="h-3.5 w-3.5 text-red-400" />
              )}
              {trend === "flat" && (
                <Minus className="h-3.5 w-3.5 text-slate-400" />
              )}
              {trendValue && (
                <span
                  className={cn(
                    trend === "up"
                      ? "text-emerald-400"
                      : trend === "down"
                      ? "text-red-400"
                      : "text-slate-400"
                  )}
                >
                  {trendValue}
                </span>
              )}
            </div>
          )}
        </div>
        {icon && (
          <div className={cn("rounded-xl bg-slate-900/60 p-3", iconColor[accent])}>
            {icon}
          </div>
        )}
      </div>
    </div>
  );
}
