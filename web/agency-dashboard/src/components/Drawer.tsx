import { useEffect, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { X } from "lucide-react";

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  width?: "sm" | "md" | "lg";
  className?: string;
}

export default function Drawer({
  open,
  onClose,
  title,
  children,
  width = "md",
  className,
}: DrawerProps) {
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (open) window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  const widthMap = { sm: "max-w-md", md: "max-w-lg", lg: "max-w-2xl" };

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        className={cn(
          "fixed right-0 top-0 z-50 h-full w-full bg-slate-900 border-l border-slate-800",
          "shadow-2xl shadow-black/40 overflow-y-auto",
          "animate-[slideIn_0.2s_ease-out]",
          widthMap[width],
          className
        )}
        style={{
          animation: "slideIn 0.2s ease-out",
        }}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-800 bg-slate-900/95 backdrop-blur-xl px-6 py-4">
          <h2 className="text-lg font-semibold text-slate-100">{title}</h2>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-6">{children}</div>
      </div>
      <style>{`
        @keyframes slideIn {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
      `}</style>
    </>
  );
}
