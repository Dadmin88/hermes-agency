import { cn } from "@/lib/cn";

interface SkeletonProps {
  className?: string;
  lines?: number;
  variant?: "text" | "card" | "circle" | "rect";
}

export default function Skeleton({
  className,
  lines = 1,
  variant = "text",
}: SkeletonProps) {
  if (variant === "circle") {
    return (
      <div
        className={cn(
          "animate-pulse rounded-full bg-slate-800",
          className
        )}
      />
    );
  }

  if (variant === "card") {
    return (
      <div className={cn("glass-card p-6 space-y-4", className)}>
        <div className="h-4 w-1/3 rounded bg-slate-800 animate-pulse" />
        <div className="h-8 w-1/2 rounded bg-slate-800 animate-pulse" />
        <div className="h-3 w-full rounded bg-slate-800 animate-pulse" />
      </div>
    );
  }

  if (variant === "rect") {
    return (
      <div
        className={cn(
          "animate-pulse rounded-xl bg-slate-800",
          className
        )}
      />
    );
  }

  return (
    <div className="space-y-2">
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className={cn(
            "animate-pulse rounded bg-slate-800 h-4",
            i === lines - 1 ? "w-2/3" : "w-full",
            className
          )}
        />
      ))}
    </div>
  );
}
