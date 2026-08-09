/**
 * Single source of truth for backend connectivity.
 * Swap the base URL / paths here when the real backend lands.
 */
export const API_BASE_URL: string =
  (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "http://localhost:8000";

export const API_ENDPOINTS = {
  metrics: "/api/metrics",
  logs: "/api/logs",
  pipelineStatus: "/api/pipeline/status",
  pipelineRun: "/api/pipeline/run",
  trafficInject: "/api/traffic/inject",
  incidentLatest: "/api/incident/latest",
  incidents: "/api/incidents",
} as const;

/** Polling interval (ms) for the live-data endpoints. */
export const POLL_INTERVAL_MS = 2000;

export const apiUrl = (path: string) => `${API_BASE_URL.replace(/\/$/, "")}${path}`;