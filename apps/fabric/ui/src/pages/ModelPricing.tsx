import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@/lib/router";
import { ArrowLeft, Loader2, RefreshCw, Save } from "lucide-react";
import type { ModelPricingItem } from "@paperclipai/shared";
import { MODEL_PRICING_TYPES } from "@paperclipai/shared";
import { modelSetsApi, type ModelPricingRow } from "@/api/model-sets";
import { useBreadcrumbs } from "@/context/BreadcrumbContext";
import { useToastActions } from "@/context/ToastContext";
import { queryKeys } from "@/lib/queryKeys";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type EditableRow = ModelPricingRow & { key: string };

function toEditable(rows: ModelPricingRow[]): EditableRow[] {
  return rows.map((row, index) => ({
    ...row,
    key: row.id ?? `${row.provider}/${row.model}/${index}`,
  }));
}

function toPayload(rows: EditableRow[]): ModelPricingItem[] {
  return rows.map((row) => ({
    provider: row.provider.trim(),
    model: row.model.trim(),
    pricingType: row.pricingType,
    inputCostPer1m: row.inputCostPer1m,
    outputCostPer1m: row.outputCostPer1m,
    monthlyEstimate: row.monthlyEstimate,
  }));
}

export function ModelPricing() {
  const queryClient = useQueryClient();
  const { setBreadcrumbs } = useBreadcrumbs();
  const { pushToast } = useToastActions();
  const [rows, setRows] = useState<EditableRow[]>([]);

  useEffect(() => {
    setBreadcrumbs([
      { label: "Model Sets", href: "/settings/model-sets" },
      { label: "Model pricing" },
    ]);
  }, [setBreadcrumbs]);

  const { data: pricing = [], isLoading } = useQuery({
    queryKey: queryKeys.modelSets.pricing,
    queryFn: () => modelSetsApi.listPricing(),
  });

  useEffect(() => {
    setRows(toEditable(pricing));
  }, [pricing]);

  const dirty = useMemo(() => JSON.stringify(rows) !== JSON.stringify(toEditable(pricing)), [rows, pricing]);

  const saveMutation = useMutation({
    mutationFn: () => modelSetsApi.updatePricing(toPayload(rows)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.pricing });
      pushToast({ title: "Pricing saved", tone: "success" });
    },
    onError: (error: Error) => {
      pushToast({ title: "Save failed", description: error.message, tone: "error" });
    },
  });

  const detectMutation = useMutation({
    mutationFn: () => modelSetsApi.autoDetectOpenRouterPricing(),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.pricing });
      pushToast({
        title: "OpenRouter pricing refreshed",
        description: `${result.discovered} models discovered`,
        tone: "success",
      });
    },
    onError: (error: Error) => {
      pushToast({ title: "Auto-detect failed", description: error.message, tone: "error" });
    },
  });

  function updateRow(key: string, patch: Partial<EditableRow>) {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  }

  function addRow() {
    setRows((current) => [
      ...current,
      {
        key: `new-${Date.now()}`,
        provider: "openrouter",
        model: "",
        pricingType: "api",
        inputCostPer1m: null,
        outputCostPer1m: null,
        monthlyEstimate: null,
      },
    ]);
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
            <Link to="/settings/model-sets">
              <ArrowLeft className="mr-1 h-4 w-4" />
              Model sets
            </Link>
          </Button>
          <h1 className="text-2xl font-semibold tracking-tight">Model pricing</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Configure per-model pricing for cost estimates. Subscription and manual types require a monthly estimate.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            onClick={() => detectMutation.mutate()}
            disabled={detectMutation.isPending}
          >
            {detectMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="mr-2 h-4 w-4" />
            )}
            Auto-detect OpenRouter
          </Button>
          <Button onClick={() => saveMutation.mutate()} disabled={!dirty || saveMutation.isPending}>
            <Save className="mr-2 h-4 w-4" />
            Save
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Pricing table</CardTitle>
          <CardDescription>API models can use historical spend when monthly estimate is unset.</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading pricing…
            </div>
          ) : (
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-3 py-2">Provider</th>
                    <th className="px-3 py-2">Model</th>
                    <th className="px-3 py-2">Type</th>
                    <th className="px-3 py-2">Input $/1M</th>
                    <th className="px-3 py-2">Output $/1M</th>
                    <th className="px-3 py-2">Monthly est.</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.key} className="border-b border-border/60 last:border-0">
                      <td className="px-3 py-2">
                        <Input value={row.provider} onChange={(e) => updateRow(row.key, { provider: e.target.value })} />
                      </td>
                      <td className="px-3 py-2">
                        <Input value={row.model} onChange={(e) => updateRow(row.key, { model: e.target.value })} />
                      </td>
                      <td className="px-3 py-2">
                        <Select
                          value={row.pricingType}
                          onValueChange={(value) =>
                            updateRow(row.key, { pricingType: value as ModelPricingItem["pricingType"] })
                          }
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {MODEL_PRICING_TYPES.map((type) => (
                              <SelectItem key={type} value={type}>
                                {type}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </td>
                      <td className="px-3 py-2">
                        <Input
                          type="number"
                          value={row.inputCostPer1m ?? ""}
                          onChange={(e) =>
                            updateRow(row.key, {
                              inputCostPer1m: e.target.value === "" ? null : Number(e.target.value),
                            })
                          }
                        />
                      </td>
                      <td className="px-3 py-2">
                        <Input
                          type="number"
                          value={row.outputCostPer1m ?? ""}
                          onChange={(e) =>
                            updateRow(row.key, {
                              outputCostPer1m: e.target.value === "" ? null : Number(e.target.value),
                            })
                          }
                        />
                      </td>
                      <td className="px-3 py-2">
                        <Input
                          type="number"
                          value={row.monthlyEstimate ?? ""}
                          onChange={(e) =>
                            updateRow(row.key, {
                              monthlyEstimate: e.target.value === "" ? null : Number(e.target.value),
                            })
                          }
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Button variant="outline" size="sm" className="mt-3" onClick={addRow}>
            Add row
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}