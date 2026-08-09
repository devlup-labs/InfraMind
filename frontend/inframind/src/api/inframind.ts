import { API_ENDPOINTS, apiUrl } from "@/config/api";
import type {
  IncidentReport,
  LogEntry,
  MetricsSnapshot,
  PastIncident,
  PipelineStatus,
  TrafficMode,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export const getMetrics = () => request<MetricsSnapshot>(API_ENDPOINTS.metrics);
export const getLogs = () => request<LogEntry[]>(API_ENDPOINTS.logs);
export const getPipelineStatus = () => request<PipelineStatus>(API_ENDPOINTS.pipelineStatus);
export const getLatestIncident = () => request<IncidentReport>(API_ENDPOINTS.incidentLatest);
export const getIncidents = () => request<PastIncident[]>(API_ENDPOINTS.incidents);

export const runPipeline = () =>
  request<unknown>(API_ENDPOINTS.pipelineRun, { method: "POST", body: JSON.stringify({}) });

export const injectTraffic = (mode: TrafficMode) =>
  request<unknown>(API_ENDPOINTS.trafficInject, {
    method: "POST",
    body: JSON.stringify({ mode }),
  });