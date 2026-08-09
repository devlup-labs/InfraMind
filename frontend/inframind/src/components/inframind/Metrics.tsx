import { Panel, PanelLabel } from "./primitives";
import type { MetricsSnapshot } from "@/api/types";

const TILES: { key: keyof MetricsSnapshot; label: string; unit?: string; digits: number }[] = [
  { key: "cpu_usage_rate", label: "CPU usage rate", digits: 2 },
  { key: "http_4xx_rate", label: "HTTP 4xx rate", unit: "req/s", digits: 2 },
  { key: "http_5xx_rate", label: "HTTP 5xx rate", unit: "req/s", digits: 2 },
  { key: "latency_p95", label: "Latency p95", unit: "s", digits: 2 },
];

export function Metrics({ data }: { data: MetricsSnapshot | null }) {
  return (
    <Panel className="flex flex-col">
      <PanelLabel>Metrics</PanelLabel>
      <div className="mt-4 flex flex-col gap-2.5">
        {TILES.map((tile) => {
          const raw = data ? (data[tile.key] as number | null | undefined) : undefined;
          const hasValue = typeof raw === "number" && !Number.isNaN(raw);
          return (
            <div
              key={tile.key}
              className="flex items-center justify-between gap-3 rounded-lg border border-border bg-background px-4 py-3"
            >
              <div className="min-w-0">
                <p className="text-[11px] uppercase tracking-[0.1em] text-muted-foreground">
                  {tile.label}
                </p>
                {!hasValue ? (
                  <p className="mt-1 text-xs text-muted-foreground/70">Waiting for data</p>
                ) : null}
              </div>
              <p className="shrink-0 text-right font-mono text-xl font-bold text-foreground">
                {hasValue ? raw.toFixed(tile.digits) : "—"}
                {hasValue && tile.unit ? (
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    {tile.unit}
                  </span>
                ) : null}
              </p>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}