export function formatDate(iso: string | number | null | undefined): string {
  if (iso === null || iso === undefined) return "—";
  try {
    return new Date(typeof iso === "number" ? iso * 1000 : iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return String(iso);
  }
}

export function formatTime(iso: string | number | null | undefined): string {
  if (iso === null || iso === undefined) return "—";
  try {
    return new Date(typeof iso === "number" ? iso * 1000 : iso).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return String(iso);
  }
}

export function formatRelative(iso: string | number | null | undefined): string {
  if (iso === null || iso === undefined) return "—";
  try {
    const diff = Date.now() - new Date(typeof iso === "number" ? iso * 1000 : iso).getTime();
    const seconds = Math.floor(diff / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  } catch {
    return String(iso);
  }
}

export const statusColor: Record<string, string> = {
  healthy: "text-emerald-400",
  ok: "text-emerald-400",
  pass: "text-emerald-400",
  online: "text-emerald-400",
  running: "text-emerald-400",
  active: "text-cyan-400",
  working: "text-cyan-400",
  queued: "text-amber-400",
  pending: "text-amber-400",
  warn: "text-amber-400",
  warning: "text-amber-400",
  degraded: "text-amber-400",
  fail: "text-red-400",
  failed: "text-red-400",
  error: "text-red-400",
  offline: "text-red-400",
  unhealthy: "text-red-400",
  blocked: "text-orange-400",
  stale: "text-slate-500",
  archived: "text-slate-500",
  completed: "text-emerald-400",
  done: "text-emerald-400",
  success: "text-emerald-400",
  na: "text-slate-400",
};

export const statusBg: Record<string, string> = {
  healthy: "bg-emerald-400/10 text-emerald-400 border-emerald-400/20",
  ok: "bg-emerald-400/10 text-emerald-400 border-emerald-400/20",
  pass: "bg-emerald-400/10 text-emerald-400 border-emerald-400/20",
  online: "bg-emerald-400/10 text-emerald-400 border-emerald-400/20",
  running: "bg-emerald-400/10 text-emerald-400 border-emerald-400/20",
  active: "bg-cyan-400/10 text-cyan-400 border-cyan-400/20",
  working: "bg-cyan-400/10 text-cyan-400 border-cyan-400/20",
  queued: "bg-amber-400/10 text-amber-400 border-amber-400/20",
  pending: "bg-amber-400/10 text-amber-400 border-amber-400/20",
  warn: "bg-amber-400/10 text-amber-400 border-amber-400/20",
  warning: "bg-amber-400/10 text-amber-400 border-amber-400/20",
  degraded: "bg-amber-400/10 text-amber-400 border-amber-400/20",
  fail: "bg-red-400/10 text-red-400 border-red-400/20",
  failed: "bg-red-400/10 text-red-400 border-red-400/20",
  error: "bg-red-400/10 text-red-400 border-red-400/20",
  offline: "bg-red-400/10 text-red-400 border-red-400/20",
  unhealthy: "bg-red-400/10 text-red-400 border-red-400/20",
  blocked: "bg-orange-400/10 text-orange-400 border-orange-400/20",
  stale: "bg-slate-400/10 text-slate-400 border-slate-400/20",
  archived: "bg-slate-400/10 text-slate-400 border-slate-400/20",
  completed: "bg-emerald-400/10 text-emerald-400 border-emerald-400/20",
  done: "bg-emerald-400/10 text-emerald-400 border-emerald-400/20",
  success: "bg-emerald-400/10 text-emerald-400 border-emerald-400/20",
  na: "bg-slate-400/10 text-slate-400 border-slate-400/20",
};

export function getStatusColor(status: string): string {
  return statusColor[status.toLowerCase()] ?? "text-slate-400";
}

export function getStatusBg(status: string): string {
  return statusBg[status.toLowerCase()] ?? "bg-slate-400/10 text-slate-400 border-slate-400/20";
}

export function truncate(str: string, max: number): string {
  return str.length > max ? str.slice(0, max) + "…" : str;
}
