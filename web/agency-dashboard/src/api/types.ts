// TypeScript interfaces matching backend Pydantic models

export interface HealthStatus {
  status: string;
  daemon: {
    status: string;
    pid: number | null;
    uptime_seconds: number | null;
  };
  registry: {
    status: string;
    total_peers: number;
    online_peers: number;
  };
  model_set: {
    name: string;
    provider: string;
  };
  config_loaded: boolean;
  version: string;
}

export interface DoctorReport {
  overall_status: string;
  checks: DoctorCheck[];
  summary: {
    pass: number;
    warn: number;
    fail: number;
  };
}

export interface DoctorCheck {
  name: string;
  status: "pass" | "warn" | "fail";
  message: string;
  remediation?: string;
}

export interface AgentCard {
  id: string;
  name: string;
  department: string;
  role: string;
  skills: string[];
  description: string;
  status: "online" | "offline" | "busy" | "unknown";
  discoverable: boolean;
  model?: string;
  metadata?: Record<string, unknown>;
}

export interface RosterInfo {
  total_agents: number;
  departments: string[];
  agents: AgentCard[];
}

export interface Task {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  priority: "low" | "medium" | "high" | "critical";
  assigned_agent?: string;
  created_at: string;
  updated_at: string;
  source: "agency_incoming" | "kanban" | "manual";
  tags: string[];
  result?: string;
}

export type TaskStatus =
  | "queued"
  | "active"
  | "working"
  | "completed"
  | "failed"
  | "blocked"
  | "archived"
  | "stale";

export interface AgencyEvent {
  id: string;
  event_type: string;
  severity: "info" | "warning" | "error" | "debug";
  source: string;
  agent_id?: string;
  message: string;
  details?: Record<string, unknown>;
  timestamp: string;
}

export interface DispatchRequest {
  message: string;
  skill?: string;
  department?: string;
  target_agent?: string;
  priority: "low" | "medium" | "high" | "critical";
  create_kanban_task: boolean;
}

export interface DispatchResult {
  task_id: string;
  status: string;
  assigned_agent?: string;
  message: string;
}

export interface ModelSet {
  name: string;
  provider: string;
  model: string;
  is_default: boolean;
}

export interface ConfigInfo {
  agency_enabled: boolean;
  daemon_pid: number | null;
  registry_mode: string;
  security: {
    allow_remote_tasks: boolean;
    incoming_tool_access: string;
  };
  runtime: Record<string, unknown>;
  model_sets: ModelSet[];
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
