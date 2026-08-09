import { Dot, Panel, PanelLabel, formatDuration } from "./primitives";
import type { PastIncident } from "@/api/types";

function formatTriggered(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function PastIncidents({ incidents }: { incidents: PastIncident[] }) {
  return (
    <Panel>
      <div className="flex items-center justify-between gap-2">
        <PanelLabel>Past incidents</PanelLabel>
        <span className="text-xs text-muted-foreground">{incidents.length} recorded</span>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              <th className="pb-2 pr-4 font-medium">Anomaly</th>
              <th className="pb-2 pr-4 font-medium">Triggered</th>
              <th className="pb-2 pr-4 font-medium">Root cause</th>
              <th className="pb-2 pr-4 font-medium">Duration</th>
              <th className="pb-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {incidents.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-6 text-center text-xs text-muted-foreground/70">
                  No incidents recorded yet.
                </td>
              </tr>
            ) : (
              incidents.map((incident, i) => {
                const resolved = incident.status === "resolved";
                return (
                  <tr
                    key={`${incident.anomaly}-${incident.triggered_at}-${i}`}
                    className="cursor-pointer border-t border-border transition-colors hover:bg-background"
                  >
                    <td className="py-3 pr-4 font-mono text-xs text-foreground">
                      {incident.anomaly}
                    </td>
                    <td className="py-3 pr-4 text-xs text-muted-foreground">
                      {formatTriggered(incident.triggered_at)}
                    </td>
                    <td className="max-w-xs truncate py-3 pr-4 text-xs text-muted-foreground">
                      {incident.root_cause}
                    </td>
                    <td className="py-3 pr-4 font-mono text-xs text-muted-foreground">
                      {formatDuration(incident.duration_seconds)}
                    </td>
                    <td className="py-3">
                      <span
                        className={`flex items-center gap-2 text-xs ${resolved ? "text-success" : "text-destructive"}`}
                      >
                        <Dot className={resolved ? "bg-success" : "bg-destructive"} />
                        {resolved ? "Resolved" : "Failed"}
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}