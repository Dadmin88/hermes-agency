import { type ReactNode } from "react";
import { cn } from "@/lib/cn";

interface GlassCardProps {
  children: ReactNode;
  className?: string;
  padding?: "none" | "sm" | "md" | "lg";
  hover?: boolean;
  onClick?: () => void;
}

export default function GlassCard({
  children,
  className,
  padding = "md",
  hover = false,
  onClick,
}: GlassCardProps) {
  const pad = { none: "", sm: "p-4", md: "p-6", lg: "p-8" };
  return (
    <div
      onClick={onClick}
      className={cn(
        "glass-card",
        pad[padding],
        hover && "hover:border-slate-700 transition-colors duration-200",
        className
      )}
    >
      {children}
    </div>
  );
}
