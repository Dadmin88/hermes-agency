import { cn } from "@/lib/cn";
import { useToast, removeToast, type Toast as TToast, type ToastType } from "@/hooks/useToast";
import { CheckCircle, XCircle, AlertTriangle, Info, X } from "lucide-react";

const iconMap: Record<ToastType, typeof CheckCircle> = {
  success: CheckCircle,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const colorMap: Record<ToastType, string> = {
  success:
    "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  error: "border-red-500/30 bg-red-500/10 text-red-300",
  warning: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  info: "border-cyan-500/30 bg-cyan-500/10 text-cyan-300",
};

export function ToastContainer() {
  const { toasts } = useToast();

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 max-w-sm">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} />
      ))}
    </div>
  );
}

function ToastItem({ toast }: { toast: TToast }) {
  const Icon = iconMap[toast.type];

  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-xl border px-4 py-3",
        "backdrop-blur-xl shadow-lg shadow-black/20",
        "animate-[toastIn_0.3s_ease-out]",
        colorMap[toast.type]
      )}
      style={{
        animation: "toastIn 0.3s ease-out",
      }}
    >
      <Icon className="h-5 w-5 mt-0.5 flex-shrink-0" />
      <p className="text-sm flex-1">{toast.message}</p>
      <button
        onClick={() => removeToast(toast.id)}
        className="flex-shrink-0 rounded p-0.5 hover:bg-white/10 transition-colors"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

// Inject keyframes once
if (typeof document !== "undefined") {
  const style = document.createElement("style");
  style.textContent = `
    @keyframes toastIn {
      from { opacity: 0; transform: translateX(100%) scale(0.9); }
      to { opacity: 1; transform: translateX(0) scale(1); }
    }
  `;
  document.head.appendChild(style);
}
