import { useCallback, useEffect, useRef, useState } from "react";
import {
  getIncidents,
  getLatestIncident,
  getLogs,
  getMetrics,
  getPipelineStatus,
  injectTraffic,
  runPipeline,
} from "@/api/inframind";
import { POLL_INTERVAL_MS } from "@/config/api";
import type {
  IncidentReport,
  LogEntry,
  MetricsSnapshot,
  PastIncident,
  PipelineStatus,
  TrafficMode,
} from "@/api/types";

/** Poll a fetcher on an interval, swallowing errors so the UI never crashes. */
function usePoll<T>(fetcher: () => Promise<T>, intervalMs = POLL_INTERVAL_MS) {
  const [data, setData] = useState<T | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const next = await fetcherRef.current();
        if (!cancelled) setData(next);
      } catch {
        /* endpoint unreachable — keep last known state */
      }
    };
    void tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [intervalMs]);

  return data;
}

export const useMetrics = () => usePoll<MetricsSnapshot>(getMetrics);

export const usePipelineStatus = () => usePoll<PipelineStatus>(getPipelineStatus);

/**
 * Live logs. Isolated here so it can become a WebSocket subscription later
 * without touching any component.
 */
export function useLogs(): LogEntry[] {
  const polled = usePoll<LogEntry[]>(getLogs);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const seen = useRef(new Set<string>());

  useEffect(() => {
    if (!Array.isArray(polled)) return;
    const fresh = polled.filter((entry) => {
      const key = `${entry.timestamp}|${entry.agent}|${entry.message}`;
      if (seen.current.has(key)) return false;
      seen.current.add(key);
      return true;
    });
    if (fresh.length) setLogs((prev) => [...prev, ...fresh]);
  }, [polled]);

  return logs;
}

export function useIncidents() {
  const [incidents, setIncidents] = useState<PastIncident[]>([]);
  useEffect(() => {
    let cancelled = false;
    getIncidents()
      .then((data) => {
        if (!cancelled && Array.isArray(data)) setIncidents(data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  return incidents;
}

export function useIncidentReport(refreshKey: number) {
  const [report, setReport] = useState<IncidentReport | null>(null);
  useEffect(() => {
    let cancelled = false;
    getLatestIncident()
      .then((data) => {
        if (!cancelled) setReport(data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);
  return report;
}

export function usePipelineActions() {
  const [pending, setPending] = useState<"pipeline" | "traffic" | null>(null);

  const run = useCallback(async () => {
    setPending("pipeline");
    try {
      await runPipeline();
      return true;
    } catch {
      return false;
    } finally {
      setPending(null);
    }
  }, []);

  const bombard = useCallback(async (mode: TrafficMode) => {
    setPending("traffic");
    try {
      await injectTraffic(mode);
      return true;
    } catch {
      return false;
    } finally {
      setPending(null);
    }
  }, []);

  return { run, bombard, pending };
}