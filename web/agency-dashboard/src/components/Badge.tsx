import { cn } from "@/lib/cn";
import { getStatusBg } from "@/lib/format";

interface BadgeProps {
  children: React.ReactNode;
  variant?: "default" | "status" | "outline";
  size?: "sm" | "md";
  className?: string;
  status?: string;
}

export default function Badge({
  children,
  variant = "default",
  size = "sm",
  className,
  status,
}: BadgeProps) {
  const base =
    "inline-flex items-center font-medium rounded-full border whitespace-nowrap";

  const sizeMap = {
    sm: "px-2 py-0.5 text-xs",
    md: "px-3 py-1 text-sm",
  };

  if (variant === "status" && status) {
    return (
      <span className={cn(base, sizeMap[size], getStatusBg(status), className)}>
        {children}
      </span>
    );
  }

  const variantMap = {
    default: "bg-slate-800 text-slate-300 border-slate-700",
    outline: "bg-transparent text-slate-400 border-slate-700",
    status: "",
  };

  return (
    <span className={cn(base, sizeMap[size], variantMap[variant], className)}>
      {children}
    </span>
  );
}
