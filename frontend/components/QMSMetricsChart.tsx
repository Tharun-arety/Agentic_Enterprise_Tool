"use client";

import * as React from "react";
import { Activity } from "lucide-react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatClock, formatNumber } from "@/lib/utils";
import type { QmsResponse } from "@/lib/types";

/**
 * Temperature span and pressure drop on one chart.
 *
 * They differ by roughly two orders of magnitude (≈16 K against ≈850 mbar), so
 * they get separate Y axes. On a shared axis the span line would be pinned flat
 * against the baseline and the 0.9 K of variation — the thing an engineer is
 * actually looking at — would be invisible.
 */

const SPAN_COLOR = "#0891b2";
const PRESSURE_COLOR = "#b45309";

export function QMSMetricsChart({ qms }: { qms: QmsResponse | null }) {
  const data = React.useMemo(
    () =>
      (qms?.records ?? []).map((record) => ({
        time: formatClock(record.recorded_at),
        span: record.temperature_span_delta_K,
        pressure: record.pressure_drop_mbar,
        capacity: record.cooling_capacity_W,
      })),
    [qms],
  );

  if (!qms || data.length === 0) {
    return (
      <div className="text-muted-foreground flex flex-col items-center gap-2 py-10 text-center text-xs">
        <Activity className="size-5 opacity-40" />
        <p>
          No QMS samples loaded. Start the backend and seed the database, or ask
          the agent for test metrics.
        </p>
      </div>
    );
  }

  const spanSummary = qms.summaries.find(
    (summary) => summary.metric === "temperature_span_delta_K",
  );
  const pressureSummary = qms.summaries.find(
    (summary) => summary.metric === "pressure_drop_mbar",
  );

  return (
    <div data-testid="qms-chart">
      <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {qms.summaries.map((summary) => (
          <div key={summary.metric} className="bg-surface-muted rounded-lg p-2">
            <p className="text-muted-foreground truncate text-[10px] uppercase tracking-wide">
              {summary.metric.replace(/_/g, " ")}
            </p>
            <p className="mt-0.5 font-mono text-sm font-semibold">
              {formatNumber(summary.latest, 1)}
              <span className="text-muted-foreground ml-1 text-[10px] font-normal">
                {summary.unit}
              </span>
            </p>
            <p className="text-muted-foreground text-[10px]">
              {formatNumber(summary.minimum, 1)} – {formatNumber(summary.maximum, 1)}
            </p>
          </div>
        ))}
      </div>

      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 8, right: 8, bottom: 4, left: -8 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="var(--border)"
              vertical={false}
            />
            <XAxis
              dataKey="time"
              stroke="var(--muted-foreground)"
              fontSize={11}
              tickLine={false}
              axisLine={{ stroke: "var(--border)" }}
            />
            <YAxis
              yAxisId="span"
              stroke={SPAN_COLOR}
              fontSize={11}
              tickLine={false}
              axisLine={false}
              // Padded rather than zero-based: the story is the variation
              // within a ~1 K band, not the distance from absolute zero.
              domain={["dataMin - 0.4", "dataMax + 0.4"]}
              tickFormatter={(value: number) => formatNumber(value, 1)}
            />
            <YAxis
              yAxisId="pressure"
              orientation="right"
              stroke={PRESSURE_COLOR}
              fontSize={11}
              tickLine={false}
              axisLine={false}
              domain={["dataMin - 5", "dataMax + 5"]}
              tickFormatter={(value: number) => formatNumber(value, 0)}
            />
            <Tooltip
              contentStyle={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: "0.5rem",
                fontSize: "12px",
                color: "var(--foreground)",
              }}
              labelStyle={{ color: "var(--muted-foreground)" }}
              // Recharts types the value as possibly undefined, so it is
              // coerced here rather than asserted.
              formatter={(value, name) => {
                const numeric = Number(value ?? 0);
                const label = String(name ?? "");
                return [
                  label === "Temperature span"
                    ? `${formatNumber(numeric, 2)} K`
                    : `${formatNumber(numeric, 1)} mbar`,
                  label,
                ];
              }}
            />
            <Legend
              wrapperStyle={{ fontSize: "11px" }}
              iconType="plainline"
              iconSize={14}
            />
            <Line
              yAxisId="span"
              type="monotone"
              dataKey="span"
              name="Temperature span"
              stroke={SPAN_COLOR}
              strokeWidth={2}
              dot={{ r: 3, strokeWidth: 0, fill: SPAN_COLOR }}
              activeDot={{ r: 5 }}
            />
            <Line
              yAxisId="pressure"
              type="monotone"
              dataKey="pressure"
              name="Pressure drop"
              stroke={PRESSURE_COLOR}
              strokeWidth={2}
              strokeDasharray="4 3"
              dot={{ r: 3, strokeWidth: 0, fill: PRESSURE_COLOR }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <p className="text-muted-foreground mt-2 text-[11px]">
        Serial{" "}
        <span className="text-foreground font-mono font-semibold">
          {qms.serial_number}
        </span>
        {qms.part_number && (
          <>
            {" "}
            · instance of{" "}
            <span className="font-mono">{qms.part_number}</span>
          </>
        )}
        {spanSummary && pressureSummary && (
          <>
            {" "}
            · span {formatNumber(spanSummary.minimum, 1)}–
            {formatNumber(spanSummary.maximum, 1)} K at{" "}
            {formatNumber(pressureSummary.mean, 0)} mbar nominal
          </>
        )}
      </p>
    </div>
  );
}
