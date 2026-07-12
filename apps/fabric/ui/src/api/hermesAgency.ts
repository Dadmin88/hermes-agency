import type {
  HermesAgencyDispatchMode,
  HermesAgencyDispatchRecord,
  HermesAgencyRosterResponse,
  HermesAgencyTaskPacketPreview,
} from "@hermes-fabric/shared";
import { api } from "./client";

export const hermesAgencyApi = {
  roster: () => api.get<HermesAgencyRosterResponse>("/hermes-agency/roster"),
  dispatch: (body: { packet: HermesAgencyTaskPacketPreview; mode: HermesAgencyDispatchMode }) => (
    api.post<HermesAgencyDispatchRecord>("/hermes-agency/dispatch", body)
  ),
  dispatchStatus: (id: string) => api.get<HermesAgencyDispatchRecord>(`/hermes-agency/dispatches/${id}`),
};
