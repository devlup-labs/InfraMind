export const API_BASE_URL = "";

export const API_ENDPOINTS = {
  metrics: "/api/metrics",
  logs: "/api/logs",
  pipelineStatus: "/api/pipelineStatus",
  pipelineRun: "/api/pipelineRun",
  trafficInject: "/api/trafficInject",
  incidentLatest: "/api/incidentLatest",
  incidents: "/api/incidents",
} as const;

export const POLL_INTERVAL_MS = 2000;

export const apiUrl = (path: string) => `${API_BASE_URL}${path}`;