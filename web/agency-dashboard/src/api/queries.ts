import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  DashboardHealth,
  DoctorReport,
  RosterDepartment,
  DashboardTask,
  DashboardEvent,
  DashboardConfig,
  DispatchRequest,
  DispatchResponse,
} from "./types";

// Health
export function useHealth() {
  return useQuery<DashboardHealth>({
    queryKey: ["health"],
    queryFn: () => api.get<DashboardHealth>("/health"),
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
  return useQuery<RosterDepartment[]>({
    queryKey: ["roster"],
    queryFn: () => api.get<RosterDepartment[]>("/roster"),
    staleTime: 60_000,
  });
}

export function useAgents() {
  return useQuery<RosterDepartment[]>({
    queryKey: ["agents"],
    queryFn: () => api.get<RosterDepartment[]>("/agents"),
    staleTime: 60_000,
  });
}

// Tasks
export function useTasks(status?: string) {
  return useQuery<DashboardTask[]>({
    queryKey: ["tasks", status],
    queryFn: () =>
      api.get<DashboardTask[]>(`/tasks${status ? `?status=${status}` : ""}`),
    refetchInterval: 15_000,
  });
}

// Events
export function useEvents(limit = 100) {
  return useQuery<DashboardEvent[]>({
    queryKey: ["events", limit],
    queryFn: () => api.get<DashboardEvent[]>(`/events?limit=${limit}`),
    refetchInterval: 10_000,
  });
}

// Config
export function useConfig() {
  return useQuery<DashboardConfig>({
    queryKey: ["config"],
    queryFn: () => api.get<DashboardConfig>("/config"),
    staleTime: 60_000,
  });
}

// Dispatch
export function useDispatchTask() {
  const queryClient = useQueryClient();
  return useMutation<DispatchResponse, Error, DispatchRequest>({
    mutationFn: (req) => api.post<DispatchResponse>("/dispatch", req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["events"] });
    },
  });
}
