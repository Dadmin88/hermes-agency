import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RotateCcw } from "lucide-react";
import type { AgentDetail, ReasoningEffort } from "@hermes-fabric/shared";
import { modelSetsApi, type ProfileOverride } from "@/api/model-sets";
import { ApiError } from "@/api/client";
import { useToastActions } from "@/context/ToastContext";
import { queryKeys } from "@/lib/queryKeys";
import {
  REASONING_EFFORT_OPTIONS,
  formatModelRef,
  modelOptions,
  providerOptions,
} from "@/lib/model-set-ui";
import {
  buildRoutingOverrideDraft,
  buildRoutingOverridePayload,
  changeRoutingOverrideProvider,
  validateRoutingOverrideDraft,
  type RoutingOverrideDraft,
} from "@/lib/direct-model-routing-override";
import { SearchableSelect } from "@/components/SearchableSelect";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { Skeleton } from "@/components/ui/skeleton";

const EFFORT_LABELS: Record<ReasoningEffort, string> = {
  none: "None",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "X-high",
  max: "Max",
  ultra: "Ultra",
};

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return fallback;
}

function sourceLabel(source: string, setName: string | null, family: string | null, role: string): string {
  if (source === "profile_override") return "Direct override";
  if (source === "department_override") return `Department override · ${role}`;
  if (source === "model_set_profile" || source === "model_set_default") {
    return ["Model set", setName, family].filter(Boolean).join(" · ");
  }
  if (source === "global_default") return "Adapter fallback";
  return "No configured source";
}

function effortLabel(effort: ReasoningEffort | null): string {
  return effort ? EFFORT_LABELS[effort] : "Provider default";
}

function replaceOverrideInCache(
  current: ProfileOverride[] | undefined,
  next: ProfileOverride,
): ProfileOverride[] {
  const rows = current ?? [];
  return [...rows.filter((row) => row.agentId !== next.agentId), next]
    .sort((left, right) => left.agentName.localeCompare(right.agentName));
}

export function DirectModelRoutingOverrideCard({
  agent,
  companyId,
  otherConfigDirty,
}: {
  agent: AgentDetail;
  companyId?: string;
  otherConfigDirty: boolean;
}) {
  const queryClient = useQueryClient();
  const { pushToast } = useToastActions();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [editing, setEditing] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [draft, setDraft] = useState<RoutingOverrideDraft>({
    provider: "",
    model: "",
    reasoningEffort: "inherit",
    reason: "",
  });
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [clearedOverride, setClearedOverride] = useState<ProfileOverride | null>(null);

  const overridesQuery = useQuery({
    queryKey: companyId
      ? queryKeys.modelSets.profileOverrides(companyId)
      : ["model-sets", "no-company", "profile-overrides"],
    queryFn: () => modelSetsApi.listProfileOverrides(companyId!),
    enabled: Boolean(companyId),
  });
  const costQuery = useQuery({
    queryKey: companyId
      ? queryKeys.modelSets.costEstimate(companyId)
      : ["model-sets", "no-company", "cost-estimate"],
    queryFn: () => modelSetsApi.getCostEstimate(companyId!),
    enabled: Boolean(companyId),
  });

  const directOverride = useMemo(
    () => overridesQuery.data?.find((row) => row.agentId === agent.id) ?? null,
    [agent.id, overridesQuery.data],
  );
  const effectiveRouting = useMemo(
    () => costQuery.data?.items.find((row) => row.agentId === agent.id) ?? null,
    [agent.id, costQuery.data],
  );
  const inheritedRouting = effectiveRouting?.inheritedRouting ?? null;

  useEffect(() => {
    if (!editing) {
      setDraft(buildRoutingOverrideDraft(directOverride, inheritedRouting ?? effectiveRouting));
      setMutationError(null);
    }
  }, [directOverride, editing, effectiveRouting, inheritedRouting]);

  const invalidateRouting = async () => {
    if (!companyId) return;
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.profileOverrides(companyId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.costEstimate(companyId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.list(companyId) }),
    ]);
  };

  const saveMutation = useMutation({
    mutationFn: () => modelSetsApi.updateProfileOverride(
      companyId!,
      agent.id,
      buildRoutingOverridePayload(draft),
    ),
    onSuccess: async (saved) => {
      queryClient.setQueryData<ProfileOverride[]>(
        queryKeys.modelSets.profileOverrides(companyId!),
        (current) => replaceOverrideInCache(current, saved),
      );
      setEditing(false);
      setMutationError(null);
      setClearedOverride(null);
      await invalidateRouting();
      pushToast({ title: "Routing override saved", tone: "success" });
      requestAnimationFrame(() => headingRef.current?.focus());
    },
    onError: (error) => {
      const message = errorMessage(error, "Could not save routing override.");
      setMutationError(`Override wasn’t saved. ${message}`);
      pushToast({ title: "Override wasn’t saved", body: message, tone: "error" });
    },
  });

  const clearMutation = useMutation({
    mutationFn: () => modelSetsApi.deleteProfileOverride(companyId!, agent.id),
    onSuccess: async () => {
      queryClient.setQueryData<ProfileOverride[]>(
        queryKeys.modelSets.profileOverrides(companyId!),
        (current) => (current ?? []).filter((row) => row.agentId !== agent.id),
      );
      setClearOpen(false);
      setEditing(false);
      setMutationError(null);
      await invalidateRouting();
      pushToast({
        title: "Routing override cleared",
        body: "Inherited routing is active. You can restore the previous override below.",
        tone: "success",
        ttlMs: 10000,
      });
      requestAnimationFrame(() => headingRef.current?.focus());
    },
    onError: (error) => {
      setMutationError(`Override wasn’t cleared. ${errorMessage(error, "Could not clear routing override.")}`);
    },
  });

  const undoMutation = useMutation({
    mutationFn: () => modelSetsApi.updateProfileOverride(companyId!, agent.id, {
      provider: clearedOverride!.provider,
      model: clearedOverride!.model,
      ...(clearedOverride!.reasoningEffort ? { reasoningEffort: clearedOverride!.reasoningEffort } : {}),
      reason: clearedOverride!.reason,
    }),
    onSuccess: async (restored) => {
      queryClient.setQueryData<ProfileOverride[]>(
        queryKeys.modelSets.profileOverrides(companyId!),
        (current) => replaceOverrideInCache(current, restored),
      );
      setClearedOverride(null);
      setMutationError(null);
      await invalidateRouting();
      pushToast({ title: "Routing override restored", tone: "success" });
    },
    onError: (error) => {
      setMutationError(`Couldn’t restore override. ${errorMessage(error, "Try again.")}`);
    },
  });

  const errors = validateRoutingOverrideDraft(draft);
  const draftInvalid = Object.keys(errors).length > 0;
  const pending = saveMutation.isPending || clearMutation.isPending || undoMutation.isPending;
  const loading = overridesQuery.isLoading || costQuery.isLoading;
  const queryError = overridesQuery.error || costQuery.error;
  const providerSelectOptions = providerOptions(draft.provider);
  const modelSelectOptions = modelOptions(draft.provider, draft.model);
  const inheritedEffort = effortLabel(inheritedRouting?.reasoningEffort ?? effectiveRouting?.reasoningEffort ?? null);

  function startEditing() {
    setDraft(buildRoutingOverrideDraft(directOverride, inheritedRouting ?? effectiveRouting));
    setMutationError(null);
    setEditing(true);
  }

  function save() {
    setMutationError(null);
    if (Object.keys(validateRoutingOverrideDraft(draft)).length > 0) return;
    saveMutation.mutate();
  }

  function requestClear() {
    if (!directOverride) return;
    setClearedOverride(directOverride);
    setMutationError(null);
    setClearOpen(true);
  }

  if (!companyId) {
    return null;
  }

  return (
    <section className="space-y-3" aria-busy={pending || loading}>
      <h3 ref={headingRef} tabIndex={-1} className="text-sm font-medium outline-none">Model routing</h3>
      <div className="space-y-4 rounded-lg border border-border p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <div className="font-medium">Direct override</div>
            <p className="text-xs text-muted-foreground">
              {directOverride
                ? "This agent uses this route instead of department and model-set routing."
                : "This agent follows company routing."}
            </p>
          </div>
          <Badge variant={directOverride ? "default" : "secondary"}>
            {directOverride ? "Direct override" : "Inherited"}
          </Badge>
        </div>

        {loading ? (
          <div className="space-y-2" role="status">
            <span className="sr-only">Loading model routing.</span>
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-4 w-64 max-w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : queryError ? (
          <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
            <p>{errorMessage(queryError, "Could not load model routing.")}</p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={() => { void overridesQuery.refetch(); void costQuery.refetch(); }}
            >
              Try again
            </Button>
          </div>
        ) : (
          <>
            <div className="grid gap-3 rounded-md border border-border/70 bg-muted/20 p-3 sm:grid-cols-2">
              <div className="min-w-0">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Effective route</div>
                <div className="mt-1 break-words font-mono text-sm">
                  {formatModelRef(effectiveRouting?.provider ?? null, effectiveRouting?.model ?? null)}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Reasoning: {effortLabel(effectiveRouting?.reasoningEffort ?? null)}
                </div>
                <Badge variant="outline" className="mt-2 whitespace-normal text-left">
                  {sourceLabel(
                    effectiveRouting?.source ?? "none",
                    effectiveRouting?.setName ?? null,
                    effectiveRouting?.family ?? null,
                    agent.role,
                  )}
                </Badge>
              </div>
              <div className="min-w-0 border-t border-border/70 pt-3 sm:border-l sm:border-t-0 sm:pl-3 sm:pt-0">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Inherited/default route</div>
                <div className="mt-1 break-words font-mono text-sm">
                  {formatModelRef(inheritedRouting?.provider ?? null, inheritedRouting?.model ?? null)}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Reasoning: {effortLabel(inheritedRouting?.reasoningEffort ?? null)}
                </div>
                <Badge variant="outline" className="mt-2 whitespace-normal text-left">
                  {sourceLabel(
                    inheritedRouting?.source ?? "none",
                    inheritedRouting?.setName ?? null,
                    inheritedRouting?.family ?? null,
                    agent.role,
                  )}
                </Badge>
              </div>
            </div>

            <p className="text-xs leading-5 text-muted-foreground">
              Direct override wins over department routing and the active model set. Clear it to resume inherited routing. If no company route applies, the agent’s adapter fallback is used.
            </p>

            {editing ? (
              <div className="space-y-4" role="group" aria-label="Edit direct model routing override">
                <div className="space-y-1.5">
                  <label htmlFor="routing-provider" className="text-sm font-medium">Provider</label>
                  <Select
                    value={draft.provider}
                    onValueChange={(provider) => setDraft((current) => changeRoutingOverrideProvider(current, provider))}
                    disabled={pending}
                  >
                    <SelectTrigger id="routing-provider" className="min-h-11 w-full" aria-invalid={Boolean(errors.provider)} aria-describedby="routing-provider-help routing-provider-error">
                      <SelectValue placeholder="Choose a provider" />
                    </SelectTrigger>
                    <SelectContent>
                      {providerSelectOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value} disabled={option.legacy}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p id="routing-provider-help" className="text-xs text-muted-foreground">Provider used only for this agent’s direct route.</p>
                  {errors.provider ? <p id="routing-provider-error" className="text-xs text-destructive">{errors.provider}</p> : null}
                </div>

                <div className="space-y-1.5">
                  <label id="routing-model-label" className="text-sm font-medium">Model</label>
                  <SearchableSelect
                    value={draft.model}
                    groups={[{
                      id: "routing-models",
                      options: modelSelectOptions.map((option) => ({
                        key: option.value,
                        value: option.value,
                        label: option.label,
                        disabled: option.legacy,
                      })),
                    }]}
                    onValueChange={(model) => setDraft((current) => ({ ...current, model }))}
                    placeholder={draft.provider ? "Choose a model" : "Choose a provider first"}
                    searchPlaceholder="Search models…"
                    emptyMessage={draft.provider ? "No models are available for this provider." : "Choose a provider first."}
                    disabled={!draft.provider || pending}
                    ariaLabel="Model"
                    ariaDescribedBy="routing-model-help routing-model-error"
                    ariaInvalid={Boolean(errors.model)}
                    triggerClassName="min-h-11"
                  />
                  <p id="routing-model-help" className="text-xs text-muted-foreground">Available models for the selected provider.</p>
                  {errors.model ? <p id="routing-model-error" className="text-xs text-destructive">{errors.model}</p> : null}
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="routing-effort" className="text-sm font-medium">Reasoning effort</label>
                  <Select
                    value={draft.reasoningEffort}
                    onValueChange={(reasoningEffort) => setDraft((current) => ({
                      ...current,
                      reasoningEffort: reasoningEffort as RoutingOverrideDraft["reasoningEffort"],
                    }))}
                    disabled={!draft.model || pending}
                  >
                    <SelectTrigger id="routing-effort" className="min-h-11 w-full" aria-invalid={Boolean(errors.reasoningEffort)}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="inherit">Inherit current ({inheritedEffort})</SelectItem>
                      {REASONING_EFFORT_OPTIONS.map((effort) => (
                        <SelectItem key={effort} value={effort}>{EFFORT_LABELS[effort]}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">Optional. If inherited, the active model set or adapter fallback supplies the effort.</p>
                  {errors.reasoningEffort ? <p className="text-xs text-destructive">{errors.reasoningEffort}</p> : null}
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="routing-reason" className="text-sm font-medium">Reason (optional)</label>
                  <Input
                    id="routing-reason"
                    value={draft.reason}
                    maxLength={500}
                    onChange={(event) => setDraft((current) => ({ ...current, reason: event.target.value }))}
                    disabled={pending}
                    aria-invalid={Boolean(errors.reason)}
                  />
                  <div className="flex justify-between gap-3 text-xs text-muted-foreground">
                    <span>Explain why this agent needs a direct route.</span>
                    <span className="tabular-nums">{draft.reason.length}/500</span>
                  </div>
                  {errors.reason ? <p className="text-xs text-destructive">{errors.reason}</p> : null}
                </div>

                {mutationError ? (
                  <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
                    {mutationError}
                  </div>
                ) : null}
                {otherConfigDirty ? <p className="text-xs text-muted-foreground">Other agent configuration changes are not included.</p> : null}
                <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    className="min-h-11"
                    disabled={pending}
                    onClick={() => setEditing(false)}
                  >
                    Cancel
                  </Button>
                  <Button type="button" className="min-h-11" disabled={pending || draftInvalid} onClick={save}>
                    {saveMutation.isPending ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Saving override…</> : "Save override"}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {mutationError ? (
                  <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
                    {mutationError}
                  </div>
                ) : null}
                {clearedOverride && !directOverride ? (
                  <div role="status" className="flex flex-col gap-2 rounded-md border border-border bg-muted/20 p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
                    <span>The previous direct override was cleared.</span>
                    <Button type="button" variant="outline" size="sm" disabled={pending} onClick={() => undoMutation.mutate()}>
                      <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                      {undoMutation.isPending ? "Restoring…" : "Undo"}
                    </Button>
                  </div>
                ) : null}
                <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                  <Button type="button" variant={directOverride ? "outline" : "default"} className="min-h-11" disabled={pending} onClick={startEditing}>
                    {directOverride ? "Edit override" : "Add direct override"}
                  </Button>
                  {directOverride ? (
                    <Button type="button" variant="outline" className="min-h-11" disabled={pending} onClick={requestClear}>
                      <RotateCcw className="mr-1.5 h-4 w-4" />
                      Clear routing override
                    </Button>
                  ) : null}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <Dialog open={clearOpen} onOpenChange={(open) => { if (!clearMutation.isPending) setClearOpen(open); }}>
        <DialogContent showCloseButton={!clearMutation.isPending}>
          <DialogHeader>
            <DialogTitle>Clear routing override?</DialogTitle>
            <DialogDescription>
              This removes only the direct model route for {agent.name}. The agent and its configuration remain unchanged.
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-md border border-border bg-muted/20 p-3 text-sm">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">The agent will resume</div>
            <div className="mt-1 break-words font-mono">
              {formatModelRef(inheritedRouting?.provider ?? null, inheritedRouting?.model ?? null)}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              Reasoning: {effortLabel(inheritedRouting?.reasoningEffort ?? null)} · {sourceLabel(
                inheritedRouting?.source ?? "none",
                inheritedRouting?.setName ?? null,
                inheritedRouting?.family ?? null,
                agent.role,
              )}
            </div>
          </div>
          {mutationError ? <div role="alert" className="text-sm text-destructive">{mutationError}</div> : null}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={clearMutation.isPending} onClick={() => setClearOpen(false)}>
              Keep override
            </Button>
            <Button type="button" variant="outline" disabled={clearMutation.isPending} onClick={() => clearMutation.mutate()}>
              {clearMutation.isPending ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Clearing override…</> : "Clear routing override"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
