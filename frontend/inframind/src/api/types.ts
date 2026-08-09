export type AgentKey = "monitoring" | "root_cause" | "optimization" | "reporting";

export type AgentStatus = "standby" | "running" | "completed" | "failed";

export interface AgentState {
  status: AgentStatus;
  duration_seconds?: number | null;
  description?: string | null;
}

export interface PipelineStatus {
  suspect_metric: string;
  anomaly_detected: boolean;
  elapsed_seconds: number;
  agents: Record<AgentKey, AgentState>;
}

export interface MetricsSnapshot {
  cpu_usage_rate: number | null;
  http_4xx_rate: number | null;
  http_5xx_rate: number | null;
  latency_p95: number | null;
  timestamp?: string;
}

export interface LogEntry {
  timestamp: string;
  agent: AgentKey | string;
  message: string;
}

export interface IncidentReport {
  status?: string;
  report?: string;
  summary?: string;
}

export interface PastIncident {
  anomaly: string;
  pod?: string;
  triggered_at: string;
  root_cause: string;
  duration_seconds: number;
  status: "resolved" | "failed" | string;
}

export type TrafficMode = "malformed" | "heavy_load";