import { useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Play } from "lucide-react";
import { AskBar } from "@/components/inframind/AskBar";
import { IncidentReportCard } from "@/components/inframind/IncidentReport";
import { LiveLogs } from "@/components/inframind/LiveLogs";
import { Metrics } from "@/components/inframind/Metrics";
import { PastIncidents } from "@/components/inframind/PastIncidents";
import { PipelineStatusPanel } from "@/components/inframind/PipelineStatus";
import { TrafficGenerator } from "@/components/inframind/TrafficGenerator";
import {
  useIncidentReport,
  useIncidents,
  useLogs,
  useMetrics,
  usePipelineActions,
  usePipelineStatus,
} from "@/hooks/useInframind";
import type { TrafficMode } from "@/api/types";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "InfraMind — Agentic ML Infrastructure Observability" },
      {
        name: "description",
        content:
          "InfraMind monitors ML infrastructure with an agentic pipeline: live metrics, root-cause analysis, incident reports and traffic simulation.",
      },
      { property: "og:title", content: "InfraMind — Agentic Observability Pipeline" },
      {
        property: "og:description",
        content:
          "Live metrics, agent pipeline status, log stream and incident reports for ML infrastructure.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Index,
});

function Index() {
  const metrics = useMetrics();
  const logs = useLogs();
  const pipeline = usePipelineStatus();
  const incidents = useIncidents();
  const [reportKey, setReportKey] = useState(0);
  const report = useIncidentReport(reportKey);
  const { run, bombard, pending } = usePipelineActions();
  const [mode, setMode] = useState<TrafficMode>("malformed");

  // Refresh the incident report whenever the reporting agent finishes a run.
  const reportingStatus = pipeline?.agents?.reporting?.status;
  useEffect(() => {
    if (reportingStatus === "completed") setReportKey((k) => k + 1);
  }, [reportingStatus]);

  return (
    <main className="min-h-screen bg-background pb-24">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-6 py-6">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground">InfraMind</h1>
            <p className="text-sm text-muted-foreground">Agentic observability pipeline</p>
          </div>
          <button
            type="button"
            onClick={() => void run()}
            disabled={pending === "pipeline"}
            className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            <Play className="size-4" />
            Run pipeline
          </button>
        </header>

        <TrafficGenerator
          mode={mode}
          onModeChange={setMode}
          onBombard={() => void bombard(mode)}
          pending={pending === "traffic"}
        />

        <PipelineStatusPanel data={pipeline} />

        <div className="grid gap-4 lg:grid-cols-[65fr_35fr]">
          <LiveLogs logs={logs} />
          <Metrics data={metrics} />
        </div>

        <IncidentReportCard report={report} anomaly={pipeline?.anomaly_detected ?? false} />

        <PastIncidents incidents={incidents} />
      </div>

      <AskBar />
    </main>
  );
}
