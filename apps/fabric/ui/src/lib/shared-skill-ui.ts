import type { EffectiveHermesSkill } from "../api/hermesAgency";

export type SharedDeleteImpact = { count: number; profiles: string[] } | null;

export function readSharedDeleteImpact(error: unknown): SharedDeleteImpact {
  if (!error || typeof error !== "object") return null;
  const candidate = error as { status?: unknown; body?: { impact?: unknown } };
  if (candidate.status !== 409 || !candidate.body || typeof candidate.body !== "object") return null;
  const impact = candidate.body.impact;
  if (!impact || typeof impact !== "object") return null;
  const value = impact as { count?: unknown; profiles?: unknown };
  if (!Array.isArray(value.profiles) || !value.profiles.every((profile) => typeof profile === "string")) return null;
  return { count: typeof value.count === "number" ? value.count : value.profiles.length, profiles: value.profiles };
}

export function filterSharedPoolSkills<T extends { name: string; category: string; description: string; tags: string[] }>(skills: T[], search: string, category: string): T[] {
  const query = search.trim().toLowerCase();
  return skills.filter((skill) => {
    if (category && skill.category !== category) return false;
    if (!query) return true;
    return [skill.name, skill.category, skill.description, skill.tags.join(" ")].join(" ").toLowerCase().includes(query);
  });
}

export function effectiveSkillActions(skill: EffectiveHermesSkill): { editShared: boolean; editLocal: boolean; detach: boolean; readOnly: boolean } {
  const active = skill.effective && skill.enabled && !skill.shadowed;
  return {
    editShared: skill.origin === "shared_pool" && active,
    editLocal: skill.origin === "profile" && active,
    detach: skill.origin === "shared_pool" && active,
    readOnly: skill.origin === "builtin" || !active,
  };
}
