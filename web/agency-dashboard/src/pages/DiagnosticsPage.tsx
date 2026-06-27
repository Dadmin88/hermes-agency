import { useState } from "react";
import PageHeader from "@/components/PageHeader";
import GlassCard from "@/components/GlassCard";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import Skeleton from "@/components/Skeleton";
import ErrorState from "@/components/ErrorState";
import Tabs from "@/components/Tabs";
import { useDoctor } from "@/api/queries";
import { addToast } from "@/hooks/useToast";
import { Stethoscope, CheckCircle, AlertTriangle, XCircle, Copy } from "lucide-react";

const groupTabs = [
  { id: "all", label: "All" },
  { id: "pass", label: "Pass" },
  { id: "warn", label: "Warn" },
  { id: "fail", label: "Fail" },
];

export default function DiagnosticsPage() {
  const { data, isLoading, error, refetch } = useDoctor();
  const [group, setGroup] = useState("all");

  if (isLoading) return <Skeleton lines={8} />;
  if (error) return <ErrorState message={error.message} onRetry={refetch} />;

  const report = data;
  if (!report) return null;

  const checks = report.checks.filter(
    (c) => group === "all" || c.status === group
  );

  const handleCopy = () => {
    const text = [
      `Hermes Agency Doctor Report`,
      `Pass: ${report.summary.pass} | Warn: ${report.summary.warn} | Fail: ${report.summary.fail} | N/A: ${report.summary.na}`,
      "Checks:",
      ...report.checks.map(
        (c) => `[${c.status.toUpperCase()}] ${c.label}: ${c.message}${
          c.remediation ? `\n  → ${c.remediation}` : ""
        }`
      ),
    ].join("\n");
    navigator.clipboard.writeText(text);
    addToast("success", "Report copied to clipboard");
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Diagnostics"
        description="System health check results"
        actions={
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={() => refetch()}>
              <Stethoscope className="h-4 w-4" /> Re-run
            </Button>
            <Button variant="ghost" size="sm" onClick={handleCopy}>
              <Copy className="h-4 w-4" /> Copy Report
            </Button>
          </div>
        }
      />

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        <GlassCard className="text-center">
          <div className="flex items-center justify-center gap-2">
            <CheckCircle className="h-5 w-5 text-emerald-400" />
            <span className="text-2xl font-bold text-emerald-400">{report.summary.pass}</span>
          </div>
          <p className="text-xs text-slate-500 mt-1">Pass</p>
        </GlassCard>
        <GlassCard className="text-center">
          <div className="flex items-center justify-center gap-2">
            <AlertTriangle className="h-5 w-5 text-amber-400" />
            <span className="text-2xl font-bold text-amber-400">{report.summary.warn}</span>
          </div>
          <p className="text-xs text-slate-500 mt-1">Warn</p>
        </GlassCard>
        <GlassCard className="text-center">
          <div className="flex items-center justify-center gap-2">
            <XCircle className="h-5 w-5 text-red-400" />
            <span className="text-2xl font-bold text-red-400">{report.summary.fail}</span>
          </div>
          <p className="text-xs text-slate-500 mt-1">Fail</p>
        </GlassCard>
        <GlassCard className="text-center">
          <div className="flex items-center justify-center gap-2">
            <span className="text-2xl font-bold text-slate-400">{report.summary.na}</span>
          </div>
          <p className="text-xs text-slate-500 mt-1">N/A</p>
        </GlassCard>
      </div>

      {/* Filter tabs */}
      <Tabs tabs={groupTabs} activeTab={group} onChange={setGroup} />

      {/* Check list */}
      <div className="space-y-3">
        {checks.map((check) => (
          <GlassCard key={check.id}>
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0 mt-0.5">
                {check.status === "pass" && <CheckCircle className="h-5 w-5 text-emerald-400" />}
                {check.status === "warn" && <AlertTriangle className="h-5 w-5 text-amber-400" />}
                {check.status === "fail" && <XCircle className="h-5 w-5 text-red-400" />}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <h4 className="text-sm font-semibold text-slate-200">{check.label}</h4>
                  <Badge variant="status" status={check.status} size="sm">
                    {check.status}
                  </Badge>
                </div>
                <p className="text-sm text-slate-400">{check.message}</p>
                {check.remediation && (
                  <div className="mt-2 rounded-lg bg-amber-500/5 border border-amber-500/10 px-3 py-2">
                    <p className="text-xs text-amber-400 font-medium mb-0.5">Remediation</p>
                    <p className="text-sm text-amber-300/80">{check.remediation}</p>
                  </div>
                )}
              </div>
            </div>
          </GlassCard>
        ))}
      </div>
    </div>
  );
}
