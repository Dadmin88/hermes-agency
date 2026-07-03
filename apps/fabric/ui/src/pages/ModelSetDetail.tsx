import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "@/lib/router";
import { ArrowLeft, Loader2, Pencil, Plus, Save, Trash2, X } from "lucide-react";
import type { ModelSetDefinition } from "@paperclipai/shared";
import { modelSetsApi } from "@/api/model-sets";
import { useBreadcrumbs } from "@/context/BreadcrumbContext";
import { useCompany } from "@/context/CompanyContext";
import { useToastActions } from "@/context/ToastContext";
import {
  emptyModelSetDefinition,
  MODEL_SET_PROVIDER_OPTIONS,
  validateModelSetDefinition,
} from "@/lib/model-set-ui";
import { queryKeys } from "@/lib/queryKeys";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
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
  reason: string;
};

type ProfileRow = {
  profile: string;
  family: string;
};

export function ModelSetDetail() {
  const { setName: routeSetName = "" } = useParams<{ setName: string }>();
  const isNew = routeSetName === "new";
  const decodedName = isNew ? "" : decodeURIComponent(routeSetName);
  const { selectedCompanyId } = useCompany();
  const companyId = selectedCompanyId ?? "";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { setBreadcrumbs } = useBreadcrumbs();
  const { pushToast } = useToastActions();

  const [editing, setEditing] = useState(isNew);
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

  const { data: detail, isLoading, error } = useQuery({
    queryKey: queryKeys.modelSets.detail(companyId, decodedName),
    queryFn: () => modelSetsApi.getSet(companyId, decodedName),
    enabled: !!companyId && !isNew,
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
  }

  const definition = useMemo((): ModelSetDefinition => {
    const familyMap = Object.fromEntries(
      families
        .filter((row) => row.key.trim())
        .map((row) => [
          row.key.trim(),
          {
            provider: row.provider.trim(),
            model: row.model.trim(),
            reason: row.reason.trim() || undefined,
          },
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
      version: 1,
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
  ]);

  const validationErrors = useMemo(() => validateModelSetDefinition(definition), [definition]);

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
      queryClient.invalidateQueries({ queryKey: queryKeys.modelSets.detail(companyId, saved.name) });
      pushToast({ title: "Model set saved", tone: "success" });
      setEditing(false);
      if (isNew) {
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
  const readOnly = !editing || detail?.source === "packaged";

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
            detail?.source !== "packaged" ? (
              <Button onClick={() => setEditing(true)}>
                <Pencil className="mr-1 h-4 w-4" />
                Edit
              </Button>
            ) : null
          ) : (
            <>
              <Button variant="outline" onClick={() => (isNew ? navigate("/settings/model-sets") : setEditing(false))}>
                <X className="mr-1 h-4 w-4" />
                Cancel
              </Button>
              <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
                {saveMutation.isPending ? (
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                ) : (
                  <Save className="mr-1 h-4 w-4" />
                )}
                Save
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
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                setFamilies((rows) => [
                  ...rows,
                  { key: `family_${rows.length + 1}`, provider: "opencode-go", model: "", reason: "" },
                ])
              }
            >
              <Plus className="mr-1 h-3.5 w-3.5" />
              Add family
            </Button>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-2">
          {families.map((row, index) => (
            <div key={`${row.key}-${index}`} className="grid gap-2 rounded-md border border-border p-3 md:grid-cols-4">
              <Input
                value={row.key}
                onChange={(e) =>
                  setFamilies((rows) => rows.map((item, i) => (i === index ? { ...item, key: e.target.value } : item)))
                }
                disabled={readOnly}
                placeholder="family_name"
              />
              <Select
                value={row.provider}
                onValueChange={(value) =>
                  setFamilies((rows) => rows.map((item, i) => (i === index ? { ...item, provider: value } : item)))
                }
                disabled={readOnly}
              >
                <SelectTrigger>
                  <SelectValue />
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
                value={row.model}
                onChange={(e) =>
                  setFamilies((rows) => rows.map((item, i) => (i === index ? { ...item, model: e.target.value } : item)))
                }
                disabled={readOnly}
                placeholder="model"
                className="font-mono text-xs"
              />
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
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Profile mappings</CardTitle>
          {!readOnly ? (
            <Button size="sm" variant="outline" onClick={() => setProfiles((rows) => [...rows, { profile: "", family: defaultFamily }])}>
              <Plus className="mr-1 h-3.5 w-3.5" />
              Add mapping
            </Button>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-2">
          {profiles.length === 0 ? (
            <p className="text-sm text-muted-foreground">No explicit profile mappings.</p>
          ) : (
            profiles.map((row, index) => (
              <div key={`${row.profile}-${index}`} className="grid gap-2 md:grid-cols-[2fr_1fr_auto]">
                <Input
                  value={row.profile}
                  onChange={(e) =>
                    setProfiles((rows) => rows.map((item, i) => (i === index ? { ...item, profile: e.target.value } : item)))
                  }
                  disabled={readOnly}
                  placeholder="agency-profile-name"
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
            <Input value={budgetInput} onChange={(e) => setBudgetInput(e.target.value)} disabled={readOnly} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Max output cost / 1M</span>
            <Input value={budgetOutput} onChange={(e) => setBudgetOutput(e.target.value)} disabled={readOnly} />
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
    </div>
  );
}