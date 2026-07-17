import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useParams } from "@/lib/router";
import { ArrowLeft, Loader2, Pencil, Plus, Save, Trash2, X } from "lucide-react";
import type { ModelSetDefinition } from "@hermes-fabric/shared";
import { agentsApi } from "@/api/agents";
import { modelSetsApi } from "@/api/model-sets";
import { useBreadcrumbs } from "@/context/BreadcrumbContext";
import { useCompany } from "@/context/CompanyContext";
import { useToastActions } from "@/context/ToastContext";
import {
  emptyModelSetDefinition,
  firstApprovedModel,
  liveAgencyProfileOptions,
  modelFamilyDefinition,
  modelOptions,
  providerOptions,
  REASONING_EFFORT_OPTIONS,
  unusedCanonicalFamilyKeys,
  validateModelSetDefinition,
} from "@/lib/model-set-ui";
import { queryKeys } from "@/lib/queryKeys";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SearchableSelect } from "@/components/SearchableSelect";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type FamilyRow = {
  key: string;
  provider: string;
  model: string;
  reasoningEffort: string;
  reason: string;
};

type ProfileRow = {
  profile: string;
  family: string;
};

const KNOWN_DEFINITION_KEYS = new Set([
  "version",
  "name",
  "description",
  "defaults",
  "families",
  "profiles",
  "escalation",
  "budget",
  "metadata",
]);

function parseJsonObject(value: string, label: string): { value: Record<string, unknown>; error: string | null } {
  if (!value.trim()) return { value: {}, error: null };
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { value: {}, error: `${label} must be a JSON object.` };
    }
    return { value: parsed as Record<string, unknown>, error: null };
  } catch {
    return { value: {}, error: `${label} contains invalid JSON.` };
  }
}

export function ModelSetDetail() {
  const { setName: routeSetName = "" } = useParams<{ setName: string }>();
  const isNew = routeSetName === "new";
  const decodedName = isNew ? "" : decodeURIComponent(routeSetName);
  const location = useLocation();
  const editRequested = new URLSearchParams(location.search).get("edit") === "1";
  const { selectedCompanyId } = useCompany();
  const companyId = selectedCompanyId ?? "";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { setBreadcrumbs } = useBreadcrumbs();
  const { pushToast } = useToastActions();

  const [editing, setEditing] = useState(isNew || editRequested);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [defaultFamily, setDefaultFamily] = useState("general_worker");
  const [families, setFamilies] = useState<FamilyRow[]>([]);
  const [profiles, setProfiles] = useState<ProfileRow[]>([]);
  const [escalationFamily, setEscalationFamily] = useState("");
  const [escalationTriggers, setEscalationTriggers] = useState("");
  const [budgetInput, setBudgetInput] = useState("");
  const [budgetOutput, setBudgetOutput] = useState("");
  const [warnUnknownPricing, setWarnUnknownPricing] = useState(true);
  const [versionInput, setVersionInput] = useState("1");
  const [metadataJson, setMetadataJson] = useState("{}");
  const [additionalSettingsJson, setAdditionalSettingsJson] = useState("{}");

  useEffect(() => {
    if (isNew || editRequested) setEditing(true);
  }, [editRequested, isNew]);

  const { data: detail, isLoading, error } = useQuery({
    queryKey: queryKeys.modelSets.detail(companyId, decodedName),
    queryFn: () => modelSetsApi.getSet(companyId, decodedName),
    enabled: !!companyId && !isNew,
  });
  const {
    data: agents = [],
    isLoading: agentsLoading,
    error: agentsError,
  } = useQuery({
    queryKey: queryKeys.agents.list(companyId),
    queryFn: () => agentsApi.list(companyId),
    enabled: !!companyId,
  });

  useEffect(() => {
    setBreadcrumbs([
      { label: "Model Sets", href: "/settings/model-sets" },
      { label: isNew ? "New set" : decodedName },
    ]);
  }, [setBreadcrumbs, isNew, decodedName]);

  useEffect(() => {
    if (isNew) {
      const seed = emptyModelSetDefinition(`custom-${Date.now().toString(36)}`);
      hydrateFromDefinition(seed);
      setEditing(true);
      return;
    }
    if (!detail) return;
    setName(detail.name);
    setDescription(detail.description ?? "");
    hydrateFromDefinition(detail.definition);
    setEditing(false);
  }, [detail, isNew]);

  function hydrateFromDefinition(definition: ModelSetDefinition) {
    setName(definition.name);
    setDescription(definition.description ?? "");
    setDefaultFamily(definition.defaults.family);
    setFamilies(
      Object.entries(definition.families).map(([key, family]) => ({
        key,
        provider: family.provider,
        model: family.model,
        reasoningEffort: family.reasoning_effort ?? "",
        reason: family.reason ?? "",
      })),
    );
    setProfiles(
      Object.entries(definition.profiles ?? {}).map(([profile, family]) => ({ profile, family })),
    );
    setEscalationFamily(definition.escalation?.default_family ?? "");
    setEscalationTriggers((definition.escalation?.triggers ?? []).join(", "));
    setBudgetInput(
      definition.budget?.max_input_cost_per_1m != null
        ? String(definition.budget.max_input_cost_per_1m)
        : "",
    );
    setBudgetOutput(
      definition.budget?.max_output_cost_per_1m != null
        ? String(definition.budget.max_output_cost_per_1m)
        : "",
    );
    setWarnUnknownPricing(definition.budget?.warn_if_unknown_pricing !== false);
    setVersionInput(String(definition.version ?? 1));
    setMetadataJson(JSON.stringify(definition.metadata ?? {}, null, 2));
    const additionalSettings = Object.fromEntries(
      Object.entries(definition).filter(([key]) => !KNOWN_DEFINITION_KEYS.has(key)),
    );
    setAdditionalSettingsJson(JSON.stringify(additionalSettings, null, 2));
  }

  const parsedMetadata = useMemo(() => parseJsonObject(metadataJson, "Metadata"), [metadataJson]);
  const parsedAdditionalSettings = useMemo(
    () => parseJsonObject(additionalSettingsJson, "Additional settings"),
    [additionalSettingsJson],
  );

  const definition = useMemo((): ModelSetDefinition => {
    const familyMap = Object.fromEntries(
      families
        .filter((row) => row.key.trim())
        .map((row) => [
          row.key.trim(),
          modelFamilyDefinition(row),
        ]),
    );
    const profileMap = Object.fromEntries(
      profiles
        .filter((row) => row.profile.trim() && row.family.trim())
        .map((row) => [row.profile.trim(), row.family.trim()]),
    );
    const triggers = escalationTriggers
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const parseBudget = (value: string) => {
      if (!value.trim()) return null;
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : null;
    };

    return {
      ...parsedAdditionalSettings.value,
      version: Number(versionInput),
      name: name.trim() || "custom-set",
      description: description.trim() || undefined,
      defaults: { family: defaultFamily.trim() || "general_worker" },
      families: familyMap,
      profiles: profileMap,
      escalation: escalationFamily.trim()
        ? { default_family: escalationFamily.trim(), triggers }
        : triggers.length > 0
          ? { triggers }
          : undefined,
      budget: {
        max_input_cost_per_1m: parseBudget(budgetInput),
        max_output_cost_per_1m: parseBudget(budgetOutput),
        warn_if_unknown_pricing: warnUnknownPricing,
      },
      metadata: parsedMetadata.value,
    };
  }, [
    name,
    description,
    defaultFamily,
    families,
    profiles,
    escalationFamily,
    escalationTriggers,
    budgetInput,
    budgetOutput,
    warnUnknownPricing,
    versionInput,
    parsedMetadata.value,
    parsedAdditionalSettings.value,
  ]);

  const validationErrors = useMemo(() => {
    const errors = validateModelSetDefinition(definition);
    if (!Number.isInteger(Number(versionInput)) || Number(versionInput) <= 0) {
      errors.push("Version must be a positive whole number.");
    }
    if (parsedMetadata.error) errors.push(parsedMetadata.error);
    if (parsedAdditionalSettings.error) errors.push(parsedAdditionalSettings.error);
    return errors;
  }, [definition, versionInput, parsedMetadata.error, parsedAdditionalSettings.error]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (validationErrors.length > 0) {
        throw new Error(validationErrors[0]);
      }
      if (isNew) {
        return modelSetsApi.createSet(companyId, {
          definition,
          description: description.trim() || null,
        });
      }
      return modelSetsApi.updateSet(companyId, decodedName, {
        definition,
        description: description.trim() || null,
      });
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.list(companyId) });
      queryClient.setQueryData(queryKeys.modelSets.detail(companyId, saved.name), saved);
      pushToast({ title: "Model set saved", tone: "success" });
      setEditing(false);
      if (isNew || saved.name !== decodedName) {
        navigate(`/settings/model-sets/${encodeURIComponent(saved.name)}`, { replace: true });
      }
    },
    onError: (err: Error) => {
      pushToast({ title: "Save failed", body: err.message, tone: "error" });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => modelSetsApi.deleteSet(companyId, decodedName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.list(companyId) });
      pushToast({ title: "Model set deleted", tone: "success" });
      navigate("/settings/model-sets");
    },
    onError: (err: Error) => {
      pushToast({ title: "Delete failed", body: err.message, tone: "error" });
    },
  });

  const familyOptions = families.map((row) => row.key).filter(Boolean);
  const addableFamilyKeys = unusedCanonicalFamilyKeys(familyOptions);
  const selectedProfiles = profiles.map((row) => row.profile).filter(Boolean);
  const readOnly = !editing;

  function cancelEditing() {
    if (isNew) {
      navigate("/settings/model-sets");
      return;
    }
    if (detail) {
      setName(detail.name);
      setDescription(detail.description ?? "");
      hydrateFromDefinition(detail.definition);
    }
    setEditing(false);
  }

  if (!companyId) {
    return <div className="p-6 text-sm text-muted-foreground">Select a company first.</div>;
  }

  if (!isNew && isLoading) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading model set…
      </div>
    );
  }

  if (!isNew && error) {
    return (
      <div className="p-6 text-sm text-destructive">
        Failed to load model set.{" "}
        <Link to="/settings/model-sets" className="underline">
          Back to list
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/settings/model-sets">
              <ArrowLeft className="mr-1 h-4 w-4" />
              Back
            </Link>
          </Button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-semibold">{isNew ? "New model set" : name}</h1>
              {detail?.source ? <Badge variant="outline">{detail.source}</Badge> : null}
              {detail?.active ? <Badge>Active</Badge> : null}
            </div>
            {!editing && description ? (
              <p className="mt-1 text-sm text-muted-foreground">{description}</p>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {!isNew && detail?.source === "custom" ? (
            <Button variant="ghost" onClick={() => deleteMutation.mutate()} disabled={deleteMutation.isPending}>
              <Trash2 className="mr-1 h-4 w-4" />
              Delete
            </Button>
          ) : null}
          {readOnly ? (
            <Button onClick={() => setEditing(true)}>
              <Pencil className="mr-1 h-4 w-4" />
              Edit
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={cancelEditing}>
                <X className="mr-1 h-4 w-4" />
                Cancel
              </Button>
              <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
                {saveMutation.isPending ? (
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                ) : (
                  <Save className="mr-1 h-4 w-4" />
                )}
                {detail?.source === "packaged" ? "Save company override" : "Save"}
              </Button>
            </>
          )}
        </div>
      </div>

      {editing && validationErrors.length > 0 ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {validationErrors.map((message) => (
            <div key={message}>{message}</div>
          ))}
        </div>
      ) : null}

      {editing && detail?.source === "packaged" ? (
        <div className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm text-muted-foreground">
          Saving creates a company-scoped editable override. The packaged baseline remains unchanged and can be
          restored by deleting the override.
        </div>
      ) : null}

      {!isNew && !editing && detail?.agentCostBreakdown && detail.agentCostBreakdown.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Cost if this set were active</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="mb-3 flex flex-wrap gap-4 text-sm">
              <span>
                Monthly estimate:{" "}
                <strong>{detail.monthlyEstimateLabel ?? "N/A"}</strong>
              </span>
              <span>
                Unknown pricing: <strong>{detail.unknownPricingCount ?? 0}</strong>
              </span>
            </div>
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-3 py-2">Agent</th>
                    <th className="px-3 py-2">Model</th>
                    <th className="px-3 py-2">Estimate</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.agentCostBreakdown.map((row) => (
                    <tr key={row.agentId} className="border-b border-border/60 last:border-0">
                      <td className="px-3 py-2">{row.agentName}</td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {row.provider}/{row.model}
                      </td>
                      <td className="px-3 py-2 tabular-nums">
                        {row.monthlyEstimateLabel ??
                          (row.monthlyEstimate != null ? `$${row.monthlyEstimate.toFixed(2)}` : "N/A")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Basics</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Name</span>
            <Input value={name} onChange={(e) => setName(e.target.value)} disabled={readOnly} />
          </label>
          <label className="space-y-1 text-sm md:col-span-2">
            <span className="text-muted-foreground">Description</span>
            <Textarea value={description} onChange={(e) => setDescription(e.target.value)} disabled={readOnly} rows={2} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Default family</span>
            <Select value={defaultFamily} onValueChange={setDefaultFamily} disabled={readOnly}>
              <SelectTrigger>
                <SelectValue placeholder="Family" />
              </SelectTrigger>
              <SelectContent>
                {familyOptions.map((family) => (
                  <SelectItem key={family} value={family}>
                    {family}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Families</CardTitle>
          {!readOnly ? (
            <Select
              onValueChange={(key) =>
                setFamilies((rows) => [
                  ...rows,
                  { key, provider: "openai-codex", model: firstApprovedModel("openai-codex"), reasoningEffort: "", reason: "" },
                ])
              }
              disabled={addableFamilyKeys.length === 0}
            >
              <SelectTrigger className="w-52">
                <Plus className="mr-1 h-3.5 w-3.5" />
                <SelectValue placeholder={addableFamilyKeys.length ? "Add family" : "All families added"} />
              </SelectTrigger>
              <SelectContent>
                {addableFamilyKeys.map((key) => (
                  <SelectItem key={key} value={key}>
                    {key}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-2">
          {families.map((row, index) => (
            <div key={`${row.key}-${index}`} className="grid gap-2 rounded-md border border-border p-3 md:grid-cols-5">
              <div className="flex min-h-10 items-center rounded-md bg-muted/50 px-3 font-mono text-xs" aria-label={`Family key ${row.key}`}>
                {row.key}
              </div>
              <Select
                value={row.provider}
                onValueChange={(provider) =>
                  setFamilies((rows) =>
                    rows.map((item, i) =>
                      i === index
                        ? { ...item, provider, model: modelOptions(provider, item.model).some((option) => !option.legacy && option.value === item.model) ? item.model : firstApprovedModel(provider) }
                        : item,
                    ),
                  )
                }
                disabled={readOnly}
              >
                <SelectTrigger aria-label={`Provider for ${row.key}`}>
                  <SelectValue placeholder="Provider" />
                </SelectTrigger>
                <SelectContent>
                  {providerOptions(row.provider).map((provider) => (
                    <SelectItem key={provider.value} value={provider.value}>
                      {provider.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={row.model}
                onValueChange={(model) =>
                  setFamilies((rows) => rows.map((item, i) => (i === index ? { ...item, model } : item)))
                }
                disabled={readOnly}
              >
                <SelectTrigger aria-label={`Model for ${row.key}`}>
                  <SelectValue placeholder="Model" />
                </SelectTrigger>
                <SelectContent>
                  {modelOptions(row.provider, row.model).map((model) => (
                    <SelectItem key={model.value} value={model.value}>
                      {model.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={row.reasoningEffort || "inherit"}
                onValueChange={(reasoningEffort) =>
                  setFamilies((rows) => rows.map((item, i) => (i === index ? { ...item, reasoningEffort: reasoningEffort === "inherit" ? "" : reasoningEffort } : item)))
                }
                disabled={readOnly}
              >
                <SelectTrigger aria-label={`Reasoning effort for ${row.key}`}>
                  <SelectValue placeholder="Reasoning effort" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="inherit">Inherit/default</SelectItem>
                  {REASONING_EFFORT_OPTIONS.map((effort) => (
                    <SelectItem key={effort} value={effort}>
                      {effort}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="flex gap-2">
                <Input
                  value={row.reason}
                  onChange={(e) =>
                    setFamilies((rows) => rows.map((item, i) => (i === index ? { ...item, reason: e.target.value } : item)))
                  }
                  disabled={readOnly}
                  placeholder="Reason"
                />
                {!readOnly ? (
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setFamilies((rows) => rows.filter((_, i) => i !== index))}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                ) : null}
              </div>
              {row.model === "gpt-5.6-luna" ? (
                <p className="md:col-span-5 text-xs text-muted-foreground">Luna supports text, reasoning, and tools.</p>
              ) : null}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Profile mappings</CardTitle>
          {!readOnly ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setProfiles((rows) => [...rows, { profile: "", family: defaultFamily }])}
              disabled={agentsLoading}
            >
              <Plus className="mr-1 h-3.5 w-3.5" />
              Add mapping
            </Button>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-2">
          {profiles.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {agentsLoading ? "Loading company profiles…" : "No explicit profile mappings."}
            </p>
          ) : (
            profiles.map((row, index) => (
              <div key={`${row.profile}-${index}`} className="grid gap-2 md:grid-cols-[2fr_1fr_auto]">
                <SearchableSelect
                  value={row.profile}
                  groups={[{
                    id: "profiles",
                    label: "Company Agency profiles",
                    options: liveAgencyProfileOptions(agents, selectedProfiles, row.profile).map((option) => ({
                      key: option.value,
                      value: option.value,
                      label: option.label,
                      searchText: option.value,
                    })),
                  }]}
                  onValueChange={(profile) =>
                    setProfiles((rows) => rows.map((item, i) => (i === index ? { ...item, profile } : item)))
                  }
                  disabled={readOnly}
                  ariaLabel={`Profile mapping ${index + 1}`}
                  loading={agentsLoading}
                  placeholder="Select Agency profile"
                  searchPlaceholder="Search Agency profiles…"
                  loadingMessage="Loading company profiles…"
                  emptyMessage={agentsError ? "Could not load company profiles." : "No available Agency profiles. Existing mappings remain available."}
                />
                <Select
                  value={row.family}
                  onValueChange={(value) =>
                    setProfiles((rows) => rows.map((item, i) => (i === index ? { ...item, family: value } : item)))
                  }
                  disabled={readOnly}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Family" />
                  </SelectTrigger>
                  <SelectContent>
                    {familyOptions.map((family) => (
                      <SelectItem key={family} value={family}>
                        {family}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {!readOnly ? (
                  <Button variant="ghost" size="icon" onClick={() => setProfiles((rows) => rows.filter((_, i) => i !== index))}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                ) : null}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Escalation & budget</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Escalation family</span>
            <Select value={escalationFamily} onValueChange={setEscalationFamily} disabled={readOnly}>
              <SelectTrigger>
                <SelectValue placeholder="Optional" />
              </SelectTrigger>
              <SelectContent>
                {familyOptions.map((family) => (
                  <SelectItem key={family} value={family}>
                    {family}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <label className="space-y-1 text-sm md:col-span-2">
            <span className="text-muted-foreground">Trigger tags (comma-separated)</span>
            <Input value={escalationTriggers} onChange={(e) => setEscalationTriggers(e.target.value)} disabled={readOnly} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Max input cost / 1M</span>
            <Input type="number" min={0} step="any" value={budgetInput} onChange={(e) => setBudgetInput(e.target.value)} disabled={readOnly} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Max output cost / 1M</span>
            <Input type="number" min={0} step="any" value={budgetOutput} onChange={(e) => setBudgetOutput(e.target.value)} disabled={readOnly} />
          </label>
          <label className="flex items-center gap-2 text-sm md:col-span-2">
            <input
              type="checkbox"
              checked={warnUnknownPricing}
              onChange={(e) => setWarnUnknownPricing(e.target.checked)}
              disabled={readOnly}
            />
            Warn when pricing is unknown
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Advanced settings</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          <label className="max-w-40 space-y-1 text-sm">
            <span className="text-muted-foreground">Schema version</span>
            <Input
              type="number"
              min={1}
              step={1}
              value={versionInput}
              onChange={(event) => setVersionInput(event.target.value)}
              disabled={readOnly}
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Metadata (JSON)</span>
            <Textarea
              value={metadataJson}
              onChange={(event) => setMetadataJson(event.target.value)}
              disabled={readOnly}
              rows={6}
              className="font-mono text-xs"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Additional top-level settings (JSON)</span>
            <Textarea
              value={additionalSettingsJson}
              onChange={(event) => setAdditionalSettingsJson(event.target.value)}
              disabled={readOnly}
              rows={12}
              className="font-mono text-xs"
            />
            <span className="block text-xs text-muted-foreground">
              Edit routing and other extension fields that are not represented above.
            </span>
          </label>
        </CardContent>
      </Card>
    </div>
  );
}