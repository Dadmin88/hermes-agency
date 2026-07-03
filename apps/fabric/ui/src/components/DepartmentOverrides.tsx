import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RotateCcw } from "lucide-react";
import type { DepartmentOverride } from "@/api/model-sets";
import { modelSetsApi } from "@/api/model-sets";
import { agentsApi } from "@/api/agents";
import { MODEL_SET_PROVIDER_OPTIONS } from "@/lib/model-set-ui";
import { queryKeys } from "@/lib/queryKeys";
import { useToastActions } from "@/context/ToastContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type RowState = DepartmentOverride & { isDefault?: boolean };

interface DepartmentOverridesEditorProps {
  companyId: string;
}

function blankRow(department: string): RowState {
  return {
    department,
    provider: "opencode-go",
    model: "",
    reason: null,
    isDefault: true,
  };
}

export function DepartmentOverridesEditor({ companyId }: DepartmentOverridesEditorProps) {
  const queryClient = useQueryClient();
  const { pushToast } = useToastActions();

  const { data: savedOverrides = [], isLoading: overridesLoading } = useQuery({
    queryKey: queryKeys.modelSets.departmentOverrides(companyId),
    queryFn: () => modelSetsApi.listDepartmentOverrides(companyId),
    enabled: !!companyId,
  });

  const { data: agents = [] } = useQuery({
    queryKey: queryKeys.agents.list(companyId),
    queryFn: () => agentsApi.list(companyId),
    enabled: !!companyId,
  });

  const departmentOptions = useMemo(() => {
    const roles = new Set<string>();
    for (const agent of agents) {
      if (agent.role?.trim()) roles.add(agent.role.trim());
    }
    for (const row of savedOverrides) roles.add(row.department);
    return Array.from(roles).sort((a, b) => a.localeCompare(b));
  }, [agents, savedOverrides]);

  const [rows, setRows] = useState<RowState[]>([]);

  useEffect(() => {
    const byDept = new Map(savedOverrides.map((row) => [row.department, row]));
    const merged = departmentOptions.map((department) => {
      const existing = byDept.get(department);
      return existing ? { ...existing, isDefault: false } : blankRow(department);
    });
    setRows(merged);
  }, [savedOverrides, departmentOptions]);

  const saveMutation = useMutation({
    mutationFn: () =>
      modelSetsApi.updateDepartmentOverrides(
        companyId,
        rows
          .filter((row) => row.provider.trim() && row.model.trim() && !row.isDefault)
          .map(({ department, provider, model, reason }) => ({
            department,
            provider,
            model,
            reason,
          })),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.departmentOverrides(companyId) });
      pushToast({ title: "Department overrides saved", tone: "success" });
    },
    onError: (error: Error) => {
      pushToast({ title: "Failed to save overrides", body: error.message, tone: "error" });
    },
  });

  function updateRow(index: number, patch: Partial<RowState>) {
    setRows((current) =>
      current.map((row, i) =>
        i === index
          ? {
              ...row,
              ...patch,
              isDefault: patch.isDefault ?? false,
            }
          : row,
      ),
    );
  }

  function resetRow(index: number) {
    const department = rows[index]?.department;
    if (!department) return;
    updateRow(index, { ...blankRow(department), isDefault: true });
  }

  if (overridesLoading) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading department overrides…
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-3 py-2">Department</th>
              <th className="px-3 py-2">Provider</th>
              <th className="px-3 py-2">Model</th>
              <th className="px-3 py-2">Reason</th>
              <th className="px-3 py-2 w-28" />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-muted-foreground">
                  No agent roles found. Create agents with roles to configure department overrides.
                </td>
              </tr>
            ) : (
              rows.map((row, index) => (
                <tr key={row.department} className="border-b border-border/60 last:border-0">
                  <td className="px-3 py-2 font-medium">{row.department}</td>
                  <td className="px-3 py-2">
                    <Select
                      value={row.provider}
                      onValueChange={(value) => updateRow(index, { provider: value })}
                    >
                      <SelectTrigger className="h-8">
                        <SelectValue placeholder="Provider" />
                      </SelectTrigger>
                      <SelectContent>
                        {MODEL_SET_PROVIDER_OPTIONS.map((provider) => (
                          <SelectItem key={provider} value={provider}>
                            {provider}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </td>
                  <td className="px-3 py-2">
                    <Input
                      className="h-8 font-mono text-xs"
                      value={row.model}
                      onChange={(event) => updateRow(index, { model: event.target.value })}
                      placeholder="model-id"
                    />
                  </td>
                  <td className="px-3 py-2">
                    <Input
                      className="h-8 text-xs"
                      value={row.reason ?? ""}
                      onChange={(event) => updateRow(index, { reason: event.target.value || null })}
                      placeholder="Optional"
                    />
                  </td>
                  <td className="px-3 py-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8"
                      onClick={() => resetRow(index)}
                    >
                      <RotateCcw className="mr-1 h-3.5 w-3.5" />
                      Reset
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="flex justify-end">
        <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
          {saveMutation.isPending ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Saving…
            </>
          ) : (
            "Save department overrides"
          )}
        </Button>
      </div>
    </div>
  );
}