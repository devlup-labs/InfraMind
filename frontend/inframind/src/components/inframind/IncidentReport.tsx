import { cn } from "@/lib/utils";
import { Panel, PanelLabel } from "./primitives";
import type { IncidentReport as IncidentReportData } from "@/api/types";

export function IncidentReportCard({
  report,
  anomaly,
}: {
  report: IncidentReportData | null;
  anomaly: boolean;
}) {
  const status = report?.status ?? (anomaly ? "Anomaly — investigating" : "No anomaly");
  const body =
    report?.report ??
    report?.summary ??
    "No incident report yet. Run the pipeline to generate an analysis of the current system state.";

  return (
    <Panel>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <PanelLabel>Incident report</PanelLabel>
        <span
          className={cn(
            "text-xs font-medium",
            anomaly ? "text-destructive" : "text-success",
          )}
        >
          {status}
        </span>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{body}</p>
    </Panel>
  );
}