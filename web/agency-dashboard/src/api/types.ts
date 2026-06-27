// TypeScript interfaces matching actual backend API responses

export interface DashboardHealth {
  ok: boolean;
  profile_home: string;
  active_profile: string | null;
  active_model_set: string | null;
  daemon_running: boolean | null;
  registry_configured: boolean;
  kanban_available: boolean;
  incoming_queue_count: number;
  warnings: DashboardWarning[];
}

export interface DashboardWarning {
  id: string;
  label: string;
  status: string;
  message: string;
  remediation?: string;
}

export interface DoctorReport {
  summary: {
    pass: number;
    warn: number;
    fail: number;
    na: number;
  };
  checks: DoctorCheck[];
  exit_code?: number;
}

export interface DoctorCheck {
  id: string;
  label: string;
  status: "pass" | "warn" | "fail" | "na";
  message: string;
  remediation?: string;
  details?: Record<string, unknown>;
}

export interface RosterDepartment {
  name: string;
  agent_count: number;
  agents: AgentCard[];
}

export interface AgentCard {
  name: string;
  label: string;
  department: string;
  skills: string[];
  description: string;
  discoverable: boolean;
  peer_id: string | null;
}

export interface DashboardTask {
  id: string;
  source: "agency_incoming" | "kanban";
  title: string;
  status: string;
  created_at: number | null;
  updated_at: number | null;
  message_text: string | null;
  result_text: string | null;
  error_text: string | null;
  kanban_task_id: string | null;
  linked_kanban_status: "present" | "missing" | "unknown" | "none";
  available_actions: string[];
}

export interface DashboardEvent {
  id: string;
  severity: "info" | "success" | "warning" | "error";
  source: string;
  message: string;
  timestamp: number | null;
  related_task_id: string | null;
  related_agent: string | null;
  metadata: Record<string, unknown>;
}

export interface DashboardConfig {
  active_model_set: string;
  available_model_sets: string[];
  profile_home: string;
  daemon_status: string;
  security: {
    allowlist?: string[];
    auto_allow_team?: boolean;
    allow_remote_tasks?: boolean;
    [key: string]: unknown;
  };
}

export interface DispatchRequest {
  message: string;
  skill?: string;
  department?: string;
  target_agent?: string;
  priority?: string;
  create_kanban_task?: boolean;
}

export interface DispatchResponse {
  ok: boolean;
  task_id: string | null;
  kanban_task_id: string | null;
  target: string | null;
  result_text: string | null;
  error_text: string | null;
}
