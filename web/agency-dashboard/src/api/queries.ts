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
  ModelSetsResponse,
  ModelSetSourceResponse,
  CreateModelSetRequest,
  UpdateModelSetRequest,
  DeleteModelSetResponse,
  SetActiveModelSetRequest,
  SetActiveModelSetResponse,
  TaskActionRequest,
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
      api.get<DashboardTask[]>(`/tasks${status ? `?status=${encodeURIComponent(status)}` : ""}`),
    staleTime: 10_000,
    gcTime: 5 * 60_000,
    refetchInterval: 30_000,
  });
}

export function useTaskAction() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, TaskActionRequest>({
    mutationFn: ({ task, action }) => {
      if (task.source === "agency_incoming") {
        if (action !== "archive") {
          throw new Error(`Agency incoming records only support archive right now.`);
        }
        return api.post(`/agency-records/${encodeURIComponent(task.id)}/archive`, {});
      }

      if (task.source === "kanban") {
        return api.post(
          `/kanban-tasks/${encodeURIComponent(task.id)}/${encodeURIComponent(action)}`,
          { board: task.board || undefined }
        );
      }

      throw new Error(`Unsupported task source: ${task.source}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["events"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
    },
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

export function useModelSets() {
  return useQuery<ModelSetsResponse>({
    queryKey: ["model-sets"],
    queryFn: () => api.get<ModelSetsResponse>("/model-sets"),
    staleTime: 60_000,
  });
}


export function useModelSetSource(name?: string) {
  return useQuery<ModelSetSourceResponse>({
    queryKey: ["model-set-source", name],
    queryFn: () => api.get<ModelSetSourceResponse>(`/model-sets/${encodeURIComponent(name || "")}/source`),
    enabled: !!name,
  });
}

export function useCreateModelSet() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, CreateModelSetRequest>({
    mutationFn: (req) => api.post("/model-sets", req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["model-sets"] });
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });
}

export function useUpdateModelSet() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, UpdateModelSetRequest>({
    mutationFn: ({ name, content }) =>
      api.put(`/model-sets/${encodeURIComponent(name)}`, { content }),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: ["model-sets"] });
      queryClient.invalidateQueries({ queryKey: ["model-set-source", variables.name] });
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });
}

export function useDeleteModelSet() {
  const queryClient = useQueryClient();
  return useMutation<DeleteModelSetResponse, Error, string>({
    mutationFn: (name) => api.delete<DeleteModelSetResponse>(`/model-sets/${encodeURIComponent(name)}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["model-sets"] });
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });
}

export function useSetActiveModelSet() {
  const queryClient = useQueryClient();
  return useMutation<SetActiveModelSetResponse, Error, SetActiveModelSetRequest>({
    mutationFn: (req) => api.post<SetActiveModelSetResponse>("/model-sets/active", req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
      queryClient.invalidateQueries({ queryKey: ["model-sets"] });
      queryClient.invalidateQueries({ queryKey: ["events"] });
    },
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
