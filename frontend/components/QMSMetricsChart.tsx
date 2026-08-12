"use client";

import * as React from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatDate, formatQuantity, formatTime, formatTimestamp, humanise } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { LabTestRecord, MetricSummary } from "@/lib/types";

/**
 * Acceptance metrics over the life of one article, one panel per metric.
 *
 * Small multiples rather than a single combined chart: the four metrics are in
 * different units, and putting them on one plot would need two y-scales, which
 * is the one thing a chart must never do.
 *
 * Pass and fail are carried by *position* — whether a point sits inside the
 * shaded acceptable band — not by the colour of the dot. That is deliberate:
 * the obvious green-dot/red-dot encoding puts the two most important states at
 * ΔE 6.5 under deuteranopia, which is well inside the range where a red-green
 * reader cannot separate them. Breaching points also take a different shape.
 * Colour here only repeats what the geometry already says.
 */

type MetricKey = keyof Pick<
  LabTestRecord,
  | "temperature_span_delta_K"
  | "pressure_drop_mbar"
  | "magnetization_cycles_hz"
  | "cooling_capacity_W"
>;

interface Point {
  recorded_at: string;
  value: number;
  breached: boolean;
}

function metricTitle(metric: string): string {
  return humanise(metric.replace(/_(delta_K|mbar|W|hz|Hz)$/i, "").replace(/_/g, " "));
}

export function QMSMetricsChart({
  records,
  summaries,
}: {
  records: LabTestRecord[];
  summaries: MetricSummary[];
}) {
  if (records.length < 2 || summaries.length === 0) return null;

  // Oldest first: a trajectory reads left to right.
  const ordered = [...records].sort(
    (a, b) => new Date(a.recorded_at).valueOf() - new Date(b.recorded_at).valueOf(),
  );

  // An endurance run puts every sample on one day, and a date axis then reads
  // "08 Apr" five times. Switch to clock time when the run fits inside a day.
  const days = new Set(ordered.map((record) => record.recorded_at.slice(0, 10)));
  const tickFormat = days.size > 1 ? "date" : "time";

  return (
    <div className="grid gap-x-6 gap-y-5 lg:grid-cols-2">
      {summaries.map((summary) => (
        <MetricPanel
          key={summary.metric}
          summary={summary}
          tickFormat={tickFormat}
          points={ordered.map((record) => ({
            recorded_at: record.recorded_at,
            value: record[summary.metric as MetricKey],
            breached: record.breaches.some((breach) => breach.metric === summary.metric),
          }))}
        />
      ))}
    </div>
  );
}

function MetricPanel({
  summary,
  points,
  tickFormat,
}: {
  summary: MetricSummary;
  points: Point[];
  tickFormat: "date" | "time";
}) {
  const values = points.map((point) => point.value);
  const bounds = [
    ...values,
    ...(summary.lower_limit !== null ? [summary.lower_limit] : []),
    ...(summary.upper_limit !== null ? [summary.upper_limit] : []),
  ];
  const low = Math.min(...bounds);
  const high = Math.max(...bounds);
  const pad = (high - low || Math.abs(high) || 1) * 0.2;
  const domain: [number, number] = [low - pad, high + pad];

  const latest = points[points.length - 1];
  const anyBreach = points.some((point) => point.breached);

  return (
    <figure className="min-w-0">
      <figcaption className="mb-1 flex items-baseline justify-between gap-3">
        <span className="text-ink-dim min-w-0 truncate text-xs">
          {metricTitle(summary.metric)}
        </span>
        <span
          className={cn(
            "ident shrink-0 text-sm font-semibold",
            latest.breached ? "text-breach" : anyBreach ? "text-warm" : "text-verified",
          )}
        >
          {formatQuantity(latest.value)} {summary.unit}
        </span>
      </figcaption>

      <div className="h-28 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 4, right: 6, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--rule)" strokeDasharray="2 4" vertical={false} />
            {/* The acceptable region. A point below or above it has failed, and
                that is visible from its position alone. */}
            <ReferenceArea
              y1={summary.lower_limit ?? domain[0]}
              y2={summary.upper_limit ?? domain[1]}
              fill="var(--verified)"
              fillOpacity={0.1}
              stroke="var(--rule-strong)"
              strokeOpacity={0.6}
            />
            <XAxis
              dataKey="recorded_at"
              tickFormatter={(value: string) =>
                tickFormat === "time" ? formatTime(value) : formatDate(value).slice(0, 6)
              }
              tick={{ fontSize: 10, fill: "var(--ink-faint)" }}
              stroke="var(--rule)"
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              domain={domain}
              width={38}
              tick={{ fontSize: 10, fill: "var(--ink-faint)" }}
              stroke="var(--rule)"
              tickLine={false}
              tickFormatter={(value: number) => formatQuantity(value)}
            />
            <Tooltip
              cursor={{ stroke: "var(--rule-strong)", strokeWidth: 1 }}
              contentStyle={{
                background: "var(--panel)",
                border: "1px solid var(--rule)",
                borderRadius: 4,
                fontSize: 11,
                color: "var(--ink)",
              }}
              labelFormatter={(value) => formatTimestamp(String(value))}
              formatter={(value) => [
                `${formatQuantity(Number(value))} ${summary.unit}`,
                metricTitle(summary.metric),
              ]}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke="var(--ink-dim)"
              strokeWidth={2}
              isAnimationActive={false}
              dot={<Marker />}
              activeDot={{ r: 5, fill: "var(--cold)", stroke: "var(--panel)", strokeWidth: 2 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

/**
 * A sample. Breaching samples are drawn as an open ring rather than a filled
 * dot, so the two states differ in shape as well as colour.
 */
function Marker(props: { cx?: number; cy?: number; payload?: Point }) {
  const { cx, cy, payload } = props;
  if (cx === undefined || cy === undefined || !payload) return null;
  return payload.breached ? (
    <circle
      cx={cx}
      cy={cy}
      r={4.5}
      fill="var(--panel)"
      stroke="var(--breach)"
      strokeWidth={2.5}
    />
  ) : (
    <circle cx={cx} cy={cy} r={3} fill="var(--verified)" stroke="var(--panel)" strokeWidth={1.5} />
  );
}
