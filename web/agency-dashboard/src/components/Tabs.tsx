import { useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";

interface Tab {
  id: string;
  label: string;
  icon?: ReactNode;
}

interface TabsProps {
  tabs: Tab[];
  activeTab: string;
  onChange: (id: string) => void;
  className?: string;
}

export default function Tabs({ tabs, activeTab, onChange, className }: TabsProps) {
  return (
    <div className={cn("flex gap-1 rounded-xl bg-slate-900/60 p-1", className)}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={cn(
            "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all duration-200",
            activeTab === tab.id
              ? "bg-slate-800 text-slate-100 shadow-sm"
              : "text-slate-400 hover:text-slate-300 hover:bg-slate-800/40"
          )}
        >
          {tab.icon}
          {tab.label}
        </button>
      ))}
    </div>
  );
}
