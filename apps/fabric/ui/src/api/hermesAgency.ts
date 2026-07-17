import type {
  HermesAgencyDispatchMode,
  HermesAgencyDispatchRecord,
  HermesAgencyRosterResponse,
  HermesAgencyTaskPacketPreview,
} from "@hermes-fabric/shared";
import { api } from "./client";

export type SharedPoolSkill = { name: string; category: string; description: string; tags: string[]; files: Array<{ path: string; sizeBytes: number; editable?: boolean }>; consumerCount: number };
export type SharedPoolImpact = { count: number; profiles: string[] };
export type SharedPoolApiErrorBody = { error?: string; message?: string; impact?: SharedPoolImpact };
export type EffectiveHermesSkill = { name: string; description: string; origin: "profile" | "shared_pool" | "builtin" | "external"; effective: boolean; enabled: boolean; editable: boolean; assigned: boolean; shadowed: boolean; status: "enabled" | "disabled" | "shadowed"; category: string | null };

export const hermesAgencyApi = {
  roster: () => api.get<HermesAgencyRosterResponse>("/hermes-agency/roster"),
  dispatch: (body: { packet: HermesAgencyTaskPacketPreview; mode: HermesAgencyDispatchMode }) => (
    api.post<HermesAgencyDispatchRecord>("/hermes-agency/dispatch", body)
  ),
  dispatchStatus: (id: string) => api.get<HermesAgencyDispatchRecord>(`/hermes-agency/dispatches/${id}`),
  sharedSkills: () => api.get<{ skills: SharedPoolSkill[] }>("/hermes-agency/shared-skills"),
  sharedSkill: (name: string) => api.get<SharedPoolSkill & { content: Record<string, string> }>(`/hermes-agency/shared-skills/${encodeURIComponent(name)}`),
  createSharedSkill: (body: { name: string; category: string; description?: string; tags?: string[]; files: Record<string, string> }) => api.post<SharedPoolSkill>("/hermes-agency/shared-skills", body),
  updateSharedSkill: (name: string, body: { category?: string; description?: string; tags?: string[]; files: Record<string, string> }) => api.put<SharedPoolSkill>(`/hermes-agency/shared-skills/${encodeURIComponent(name)}`, body),
  deleteSharedSkill: (name: string, confirm = false) => api.delete<{ deleted: true; affectedProfiles: string[] }>(`/hermes-agency/shared-skills/${encodeURIComponent(name)}?confirm=${confirm ? "true" : "false"}`),
  agentSkills: (agentId: string) => api.get<{ agentId: string; skills: EffectiveHermesSkill[] }>(`/hermes-agency/agents/${encodeURIComponent(agentId)}/skills`),
  attachPoolSkill: (agentId: string, name: string) => api.post<{ agentId: string; skills: EffectiveHermesSkill[] }>(`/hermes-agency/agents/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(name)}`, {}),
  detachPoolSkill: (agentId: string, name: string) => api.delete<{ agentId: string; skills: EffectiveHermesSkill[] }>(`/hermes-agency/agents/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(name)}`),
  localSkill: (agentId: string, name: string) => api.get<{ name: string; description: string; files: Array<{ path: string; sizeBytes: number; editable: boolean }>; content: Record<string, string> }>(`/hermes-agency/agents/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(name)}/local`),
  updateLocalSkill: (agentId: string, name: string, files: Record<string, string>) => api.put(`/hermes-agency/agents/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(name)}/local`, { files }),
};
