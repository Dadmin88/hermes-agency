import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Database, RefreshCw, Settings } from "lucide-react";
import { hermesAgencyApi } from "@/api/hermesAgency";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ToggleSwitch } from "@/components/ui/toggle-switch";
import { useBreadcrumbs } from "@/context/BreadcrumbContext";
import { useCompany } from "@/context/CompanyContext";
import { queryKeys } from "@/lib/queryKeys";
import { cn, formatDateTime } from "@/lib/utils";

export function HermesAgencySettings() {
  const { companies } = useCompany();
  const { setBreadcrumbs } = useBreadcrumbs();

  useEffect(() => {
    setBreadcrumbs([
      { label: "Settings", href: "/company/settings" },
      { label: "Instance settings", href: "/company/settings/instance/general" },
      { label: "Hermes Agency" },
    ]);
  }, [setBreadcrumbs]);

  const projectionQuery = useQuery({
    queryKey: queryKeys.hermesAgency.kanbanProjectionStatus,
    queryFn: () => hermesAgencyApi.kanbanProjectionStatus(),
    retry: false,
  });

  const status = projectionQuery.data;
  const targetCompany = status?.companyId
    ? companies.find((company) => company.id === status.companyId) ?? null
    : null;
  const targetCompanyLabel = targetCompany
    ? `${targetCompany.name} (${targetCompany.issuePrefix})`
    : status?.companyId ?? "Not configured";
  const syncStatus = status?.lastStatus ?? "disabled";
  const statusTone = syncStatus === "ok"
    ? "success"
    : syncStatus === "error"
      ? "error"
      : syncStatus === "disabled"
        ? "muted"
        : "warn";

  return (
    <div className="max-w-4xl space-y-6 overflow-x-hidden">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Settings className="h-5 w-5 shrink-0 text-muted-foreground" />
          <h1 className="text-lg font-semibold">Hermes Agency</h1>
        </div>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Review the Hermes Kanban read-only projection mapping that imports Kanban tasks into a Fabric company.
          Configuration is currently sourced from server environment variables, so this panel exposes the active
          mapping without accepting arbitrary filesystem paths from the browser.
        </p>
      </div>

      {projectionQuery.error ? (
        <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {projectionQuery.error instanceof Error
            ? projectionQuery.error.message
            : "Failed to load Hermes Kanban projection settings."}
        </div>
      ) : null}

      <section className="rounded-xl border border-border bg-card p-4 sm:p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold">Kanban projection</h2>
              <StatusBadge tone={statusTone} label={labelForStatus(syncStatus)} />
            </div>
            <p className="max-w-2xl text-sm text-muted-foreground">
              Sync mode: read-only projection. Fabric reads Hermes Kanban tasks and creates or updates projected
              issues for the configured company; edits still originate in Hermes Kanban.
            </p>
          </div>
          <ToggleSwitch
            checked={status?.enabled === true}
            disabled
            onCheckedChange={() => {}}
            aria-label="Hermes Kanban projection enabled"
            title="Projection is controlled by server environment variables."
          />
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <ReadOnlyField label="Current Kanban DB path" value={status?.dbPath ?? "Not configured"} monospace />
          <div className="min-w-0 space-y-1.5">
            <label htmlFor="hermes-kanban-company" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Target Fabric company
            </label>
            <select
              id="hermes-kanban-company"
              value={status?.companyId ?? ""}
              disabled
              className="w-full min-w-0 rounded-md border border-border bg-muted/40 px-2.5 py-2 text-sm text-foreground disabled:cursor-not-allowed disabled:opacity-80"
            >
              <option value={status?.companyId ?? ""}>{targetCompanyLabel}</option>
            </select>
            <p className="text-xs text-muted-foreground">
              Company mapping is read from FABRIC_HERMES_KANBAN_COMPANY_ID on the server.
            </p>
          </div>
          <ReadOnlyField label="Sync mode" value="Read-only projection" />
          <ReadOnlyField label="Last sync" value={status?.lastSyncAt ? formatDateTime(status.lastSyncAt) : "Never"} />
          <ReadOnlyField label="Projected tasks" value={String(status?.projectedCount ?? 0)} />
          <ReadOnlyField label="Rows changed on last sync" value={String(status?.syncedCount ?? 0)} />
        </div>

        {status?.lastError ? (
          <div role="alert" className="mt-5 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            {status.lastError}
          </div>
        ) : null}

        <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">
            Enable/disable and company changes require a server-side configuration endpoint; this env-backed build is read-only.
          </p>
          <Button
            type="button"
            variant="outline"
            className="w-full sm:w-auto"
            disabled={projectionQuery.isFetching}
            onClick={() => void projectionQuery.refetch()}
          >
            <RefreshCw className={cn("mr-2 h-4 w-4", projectionQuery.isFetching && "animate-spin")} />
            {projectionQuery.isFetching ? "Syncing..." : "Sync now"}
          </Button>
        </div>
      </section>
    </div>
  );
}

function ReadOnlyField({ label, value, monospace = false }: { label: string; value: string; monospace?: boolean }) {
  return (
    <div className="min-w-0 space-y-1.5 rounded-lg border border-border/70 bg-background px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {monospace ? <Database className="h-3.5 w-3.5 shrink-0" /> : null}
        <span>{label}</span>
      </div>
      <div className={cn("min-w-0 break-words text-sm text-foreground", monospace && "font-mono text-xs break-all")}>{value}</div>
    </div>
  );
}

function StatusBadge({ tone, label }: { tone: "success" | "error" | "warn" | "muted"; label: string }) {
  return (
    <Badge
      variant={tone === "error" ? "destructive" : tone === "muted" ? "outline" : "secondary"}
      className={cn(
        tone === "success" && "border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-300",
        tone === "warn" && "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
      )}
    >
      {label}
    </Badge>
  );
}

function labelForStatus(status: string) {
  switch (status) {
    case "ok":
      return "Last sync OK";
    case "error":
      return "Sync error";
    case "unavailable":
      return "Unavailable";
    case "disabled":
      return "Disabled";
    default:
      return status;
  }
}
