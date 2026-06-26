import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  HealthStatus,
  DoctorReport,
  RosterInfo,
  Task,
  AgencyEvent,
  DispatchRequest,
  DispatchResult,
  ConfigInfo,
  ModelSet,
} from "./types";

// Health
export function useHealth() {
  return useQuery<HealthStatus>({
    queryKey: ["health"],
    queryFn: () => api.get<HealthStatus>("/health"),
    refetchInterval: 30_000,
    retry: 2,
  });
}

// Doctor
export function useDoctor() {
  return useQuery<DoctorReport>({
    queryKey: ["doctor"],
    queryFn: () => api.get<DoctorReport>("/doctor"),
  });
}

// Roster / Agents
export function useRoster() {
  return useQuery<RosterInfo>({
    queryKey: ["roster"],
    queryFn: () => api.get<RosterInfo>("/roster"),
    staleTime: 60_000,
  });
}

export function useAgents() {
  return useQuery<RosterInfo>({
    queryKey: ["agents"],
    queryFn: () => api.get<RosterInfo>("/roster"),
    staleTime: 60_000,
  });
}

// Tasks
export function useTasks(status?: string) {
  return useQuery<Task[]>({
    queryKey: ["tasks", status],
    queryFn: () =>
      api.get<Task[]>(`/tasks${status ? `?status=${status}` : ""}`),
    refetchInterval: 15_000,
  });
}

// Events
export function useEvents(limit = 100) {
  return useQuery<AgencyEvent[]>({
    queryKey: ["events", limit],
    queryFn: () => api.get<AgencyEvent[]>(`/events?limit=${limit}`),
    refetchInterval: 10_000,
  });
}

// Config
export function useConfig() {
  return useQuery<ConfigInfo>({
    queryKey: ["config"],
    queryFn: () => api.get<ConfigInfo>("/config"),
    staleTime: 60_000,
  });
}

// Model Sets
export function useModelSets() {
  return useQuery<ModelSet[]>({
    queryKey: ["model-sets"],
    queryFn: () => api.get<ModelSet[]>("/model-sets"),
    staleTime: 60_000,
  });
}

// Dispatch
export function useDispatchTask() {
  const queryClient = useQueryClient();
  return useMutation<DispatchResult, Error, DispatchRequest>({
    mutationFn: (req) => api.post<DispatchResult>("/dispatch", req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["events"] });
    },
  });
}
