import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@/lib/router";
import {
  Cpu,
  Loader2,
  Plus,
  Trash2,
  Pencil,
  Play,
  ChevronDown,
} from "lucide-react";
import { modelSetsApi, type ModelSetPreview, type ModelSetSummary } from "@/api/model-sets";
import { DepartmentOverridesEditor } from "@/components/DepartmentOverrides";
import { ModelSetPreviewDialog } from "@/components/ModelSetPreview";
import { useBreadcrumbs } from "@/context/BreadcrumbContext";
import { useCompany } from "@/context/CompanyContext";
import { useToastActions } from "@/context/ToastContext";
import { queryKeys } from "@/lib/queryKeys";
import { formatModelRef } from "@/lib/model-set-ui";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MODEL_SET_PROVIDER_OPTIONS, REASONING_EFFORT_OPTIONS } from "@/lib/model-set-ui";

export function ModelSets() {
  const { selectedCompanyId } = useCompany();
  const { setBreadcrumbs } = useBreadcrumbs();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { pushToast } = useToastActions();

  const companyId = selectedCompanyId ?? "";

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTarget, setPreviewTarget] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<ModelSetPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const [profileDialogOpen, setProfileDialogOpen] = useState(false);
  const [profileAgentId, setProfileAgentId] = useState<string | null>(null);
  const [profileProvider, setProfileProvider] = useState("opencode-go");
  const [profileModel, setProfileModel] = useState("");
  const [profileReasoningEffort, setProfileReasoningEffort] = useState("");
  const [profileReason, setProfileReason] = useState("");
  const [restartIdleGateways, setRestartIdleGateways] = useState(false);

  useEffect(() => {
    setBreadcrumbs([{ label: "Model Sets" }]);
  }, [setBreadcrumbs]);

  const { data: sets = [], isLoading } = useQuery({
    queryKey: queryKeys.modelSets.list(companyId),
    queryFn: () => modelSetsApi.listSets(companyId),
    enabled: !!companyId,
  });

  const { data: profileOverrides = [] } = useQuery({
    queryKey: queryKeys.modelSets.profileOverrides(companyId),
    queryFn: () => modelSetsApi.listProfileOverrides(companyId),
    enabled: !!companyId,
  });

  const { data: costEstimate } = useQuery({
    queryKey: queryKeys.modelSets.costEstimate(companyId),
    queryFn: () => modelSetsApi.getCostEstimate(companyId),
    enabled: !!companyId,
  });

  const activeSet = useMemo(() => sets.find((set) => set.active) ?? null, [sets]);

  const applyMutation = useMutation({
    mutationFn: (input: { name: string; restartIdleGateways: boolean }) =>
      modelSetsApi.applySet(companyId, input.name, { restartIdleGateways: input.restartIdleGateways }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.list(companyId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.costEstimate(companyId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.agents.list(companyId) });
      setPreviewOpen(false);
      const profileUpdated = result.profileConfigs?.updated.length ?? 0;
      const gatewayRestarts = result.gatewayRestart?.attempted.length ?? 0;
      pushToast({
        title: `Applied ${result.name}`,
        body: `${result.changedAgents} agent row(s) updated · ${profileUpdated} profile config(s) written${
          gatewayRestarts > 0 ? ` · ${gatewayRestarts} gateway restart(s)` : ""
        }`,
        tone: "success",
      });
    },
    onError: (error: Error) => {
      pushToast({ title: "Apply failed", body: error.message, tone: "error" });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (name: string) => modelSetsApi.deleteSet(companyId, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.list(companyId) });
      pushToast({ title: "Custom set deleted", tone: "success" });
    },
    onError: (error: Error) => {
      pushToast({ title: "Delete failed", body: error.message, tone: "error" });
    },
  });

  const profileSaveMutation = useMutation({
    mutationFn: () =>
      modelSetsApi.updateProfileOverride(companyId, profileAgentId!, {
        provider: profileProvider,
        model: profileModel,
        ...(profileReasoningEffort ? { reasoningEffort: profileReasoningEffort as (typeof REASONING_EFFORT_OPTIONS)[number] } : {}),
        reason: profileReason || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.profileOverrides(companyId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.costEstimate(companyId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.list(companyId) });
      setProfileDialogOpen(false);
      pushToast({ title: "Profile override saved", tone: "success" });
    },
    onError: (error: Error) => {
      pushToast({ title: "Save failed", body: error.message, tone: "error" });
    },
  });

  const profileDeleteMutation = useMutation({
    mutationFn: (agentId: string) => modelSetsApi.deleteProfileOverride(companyId, agentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.profileOverrides(companyId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.costEstimate(companyId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.list(companyId) });
      pushToast({ title: "Profile override removed", tone: "success" });
    },
    onError: (error: Error) => {
      pushToast({ title: "Delete failed", body: error.message, tone: "error" });
    },
  });

  async function openPreview(name: string) {
    setPreviewTarget(name);
    setPreviewOpen(true);
    setPreviewLoading(true);
    setPreviewData(null);
    try {
      const preview = await modelSetsApi.previewApply(companyId, name);
      setPreviewData(preview);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : (error as Error).message;
      pushToast({ title: "Preview failed", body: message, tone: "error" });
      setPreviewOpen(false);
    } finally {
      setPreviewLoading(false);
    }
  }

  function openProfileEditor(
    agentId: string,
    provider: string,
    model: string,
    reasoningEffort: (typeof REASONING_EFFORT_OPTIONS)[number] | null,
    reason: string | null,
  ) {
    setProfileAgentId(agentId);
    setProfileProvider(provider);
    setProfileModel(model);
    setProfileReasoningEffort(reasoningEffort ?? "");
    setProfileReason(reason ?? "");
    setProfileDialogOpen(true);
  }

  if (!companyId) {
    return <div className="p-6 text-sm text-muted-foreground">Select a company to manage model sets.</div>;
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Cpu className="h-5 w-5 text-muted-foreground" />
            <h1 className="text-2xl font-semibold tracking-tight">Model Sets</h1>
          </div>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Route agents to provider/model families, override departments or individual agents, and apply packaged presets.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => navigate("/settings/model-sets/new")}>
            <Plus className="mr-2 h-4 w-4" />
            Create new set
          </Button>
          <Button variant="outline" asChild>
            <Link to="/settings/model-pricing">Model pricing</Link>
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Active preset</CardTitle>
          <CardDescription>The applied model set used when resolving agent models.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Badge variant={activeSet ? "default" : "secondary"}>{activeSet?.name ?? "None"}</Badge>
          {activeSet?.description ? (
            <span className="text-sm text-muted-foreground">{activeSet.description}</span>
          ) : null}
          <Select
            value={activeSet?.name ?? ""}
            onValueChange={(value) => {
              if (value) void openPreview(value);
            }}
          >
            <SelectTrigger className="w-[220px]">
              <SelectValue placeholder="Change preset" />
            </SelectTrigger>
            <SelectContent>
              {sets.map((set) => (
                <SelectItem key={set.id} value={set.name}>
                  {set.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {activeSet ? (
            <>
              <Button variant="outline" size="sm" asChild>
                <Link to={`/settings/model-sets/${encodeURIComponent(activeSet.name)}?edit=1`}>
                  <Pencil className="mr-1 h-4 w-4" />
                  Edit active
                </Link>
              </Button>
              <Button variant="outline" size="sm" onClick={() => void openPreview(activeSet.name)}>
                <ChevronDown className="mr-1 h-4 w-4" />
                Preview active
              </Button>
            </>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Cost estimate (active set)</CardTitle>
          <CardDescription>
            Monthly estimates use configured pricing, historical spend (30d), or N/A when unknown.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm">
          {costEstimate ? (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-6">
                <div>
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Agents</div>
                  <div className="text-lg font-semibold tabular-nums">{costEstimate.itemCount}</div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Monthly estimate</div>
                  <div className="text-lg font-semibold tabular-nums">
                    {costEstimate.monthlyEstimateLabel ??
                      (costEstimate.monthlyEstimateTotal > 0
                        ? `$${costEstimate.monthlyEstimateTotal.toFixed(2)}`
                        : "N/A")}
                  </div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Actual spend (30d)</div>
                  <div className="text-lg font-semibold tabular-nums">
                    {costEstimate.actualSpendLast30DaysTotal != null
                      ? `$${costEstimate.actualSpendLast30DaysTotal.toFixed(2)}`
                      : "—"}
                  </div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Unknown pricing</div>
                  <div className="text-lg font-semibold tabular-nums">{costEstimate.unknownPricingCount ?? 0}</div>
                </div>
              </div>
              {costEstimate.items.length > 0 ? (
                <div className="overflow-x-auto rounded-md border border-border">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
                        <th className="px-3 py-2">Agent</th>
                        <th className="px-3 py-2">Model</th>
                        <th className="px-3 py-2">Estimate</th>
                        <th className="px-3 py-2">30d actual</th>
                      </tr>
                    </thead>
                    <tbody>
                      {costEstimate.items.map((item) => (
                        <tr key={item.agentId} className="border-b border-border/60 last:border-0">
                          <td className="px-3 py-2 font-medium">{item.agentName}</td>
                          <td className="px-3 py-2 font-mono text-xs">
                            {formatModelRef(item.provider ?? "", item.model ?? "")}
                          </td>
                          <td className="px-3 py-2 tabular-nums">
                            {item.monthlyEstimateLabel ??
                              (item.monthlyEstimate != null ? `$${item.monthlyEstimate.toFixed(2)}` : "N/A")}
                          </td>
                          <td className="px-3 py-2 tabular-nums">
                            {item.actualSpendLast30Days != null
                              ? `$${item.actualSpendLast30Days.toFixed(2)}`
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </div>
          ) : (
            <span className="text-muted-foreground">Loading estimate…</span>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Department overrides</CardTitle>
          <CardDescription>Map agent roles (departments) to explicit provider/model pairs.</CardDescription>
        </CardHeader>
        <CardContent>
          <DepartmentOverridesEditor companyId={companyId} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Profile overrides</CardTitle>
          <CardDescription>Agents with custom models that supersede set routing.</CardDescription>
        </CardHeader>
        <CardContent>
          {profileOverrides.length === 0 ? (
            <p className="text-sm text-muted-foreground">No profile overrides configured.</p>
          ) : (
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-3 py-2">Agent</th>
                    <th className="px-3 py-2">Model</th>
                    <th className="px-3 py-2 w-32" />
                  </tr>
                </thead>
                <tbody>
                  {profileOverrides.map((row) => (
                    <tr key={row.agentId} className="border-b border-border/60 last:border-0">
                      <td className="px-3 py-2 font-medium">{row.agentName}</td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {formatModelRef(row.provider, row.model)}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() =>
                              openProfileEditor(row.agentId, row.provider, row.model, row.reasoningEffort, row.reason)
                            }
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => profileDeleteMutation.mutate(row.agentId)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Model sets library</CardTitle>
          <CardDescription>Packaged presets plus company-specific custom sets.</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading sets…
            </div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {sets.map((set) => (
                <ModelSetLibraryCard
                  key={set.id}
                  set={set}
                  onApply={() => void openPreview(set.name)}
                  onDelete={() => deleteMutation.mutate(set.name)}
                  deleting={deleteMutation.isPending}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <ModelSetPreviewDialog
        open={previewOpen}
        onOpenChange={setPreviewOpen}
        preview={previewData}
        loading={previewLoading}
        applying={applyMutation.isPending}
        restartIdleGateways={restartIdleGateways}
        onRestartIdleGatewaysChange={setRestartIdleGateways}
        onApply={() => {
          if (previewTarget) {
            applyMutation.mutate({ name: previewTarget, restartIdleGateways });
          }
        }}
      />

      <Dialog open={profileDialogOpen} onOpenChange={setProfileDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit profile override</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Select value={profileProvider} onValueChange={setProfileProvider}>
              <SelectTrigger>
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
            <Input
              value={profileModel}
              onChange={(event) => setProfileModel(event.target.value)}
              placeholder="Model"
              className="font-mono text-sm"
            />
            <Select value={profileReasoningEffort || "inherit"} onValueChange={(value) => setProfileReasoningEffort(value === "inherit" ? "" : value)}>
              <SelectTrigger aria-label="Reasoning effort">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="inherit">Inherit reasoning effort</SelectItem>
                {REASONING_EFFORT_OPTIONS.map((effort) => (
                  <SelectItem key={effort} value={effort}>{effort}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              value={profileReason}
              onChange={(event) => setProfileReason(event.target.value)}
              placeholder="Reason (optional)"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setProfileDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => profileSaveMutation.mutate()}
              disabled={!profileModel.trim() || profileSaveMutation.isPending}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ModelSetLibraryCard({
  set,
  onApply,
  onDelete,
  deleting,
}: {
  set: ModelSetSummary;
  onApply: () => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  return (
    <div className="rounded-md border border-border p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-medium">{set.name}</h3>
            <Badge variant="outline">{set.source}</Badge>
            {set.active ? <Badge>Active</Badge> : null}
          </div>
          {set.description ? (
            <p className="mt-1 text-xs text-muted-foreground">{set.description}</p>
          ) : null}
          <p className="mt-2 text-xs text-muted-foreground">
            {set.familyCount} families · {set.profileCount} profile mappings
            {set.monthlyEstimateLabel ? ` · est. ${set.monthlyEstimateLabel}/mo` : null}
            {set.unknownPricingCount ? ` · ${set.unknownPricingCount} unknown` : null}
          </p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" asChild>
          <Link to={`/settings/model-sets/${encodeURIComponent(set.name)}?edit=1`}>
            <Pencil className="mr-1 h-3.5 w-3.5" />
            Edit
          </Link>
        </Button>
        <Button size="sm" onClick={onApply}>
          <Play className="mr-1 h-3.5 w-3.5" />
          Apply
        </Button>
        {set.source === "custom" ? (
          <Button size="sm" variant="ghost" onClick={onDelete} disabled={deleting}>
            <Trash2 className="mr-1 h-3.5 w-3.5" />
            Delete
          </Button>
        ) : null}
      </div>
    </div>
  );
}