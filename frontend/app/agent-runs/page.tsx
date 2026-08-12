"use client";

import { Shell } from "@/components/Shell";
import { DataTable } from "@/components/ui/data-table";
import { Panel, PanelHeader, Reading } from "@/components/ui/panel";
import { Ident, Verdict } from "@/components/ui/verdict";
import { formatDuration, formatNumber, formatTimestamp, humanise } from "@/lib/format";
import { Loaded, useResource } from "@/lib/use-resource";
import type { AgentRun } from "@/lib/types";

/**
 * Agent runs.
 *
 * One row per turn, with the domains the router actually reached and the
 * correlation id that ties the turn to its audit entries. Which specialist a
 * question was routed to is the interesting column — it is the evidence that
 * routing happened at all rather than one agent seeing every tool.
 */
export default function AgentRunsPage() {
  const runs = useResource<AgentRun[]>("/api/agent-runs");

  const completed = runs.data?.filter((run) => run.status === "completed").length ?? 0;
  const durations = runs.data?.map((run) => run.duration_ms ?? 0).filter(Boolean) ?? [];
  const median = durations.length
    ? [...durations].sort((a, b) => a - b)[Math.floor(durations.length / 2)]
    : null;

  return (
    <Shell
      eyebrow="Agents & control · trajectory"
      title="Agent runs"
      summary="Every agent turn, the domains it was routed to, and how long it took."
      cells={
        runs.data
          ? [
              { label: "Turns", value: runs.data.length },
              {
                label: "Completed",
                value: `${completed}/${runs.data.length}`,
              },
              { label: "Median", value: formatDuration(median) },
            ]
          : []
      }
      onRefresh={runs.reload}
      refreshing={runs.refreshing}
    >
      <Loaded resource={runs}>
        {(rows) => (
          <div className="space-y-4">
            <Panel>
              <div className="grid grid-cols-2 divide-x divide-y divide-[var(--rule)] sm:grid-cols-4 sm:divide-y-0">
                <div className="p-4">
                  <Reading label="Turns recorded" value={rows.length} />
                </div>
                <div className="p-4">
                  <Reading
                    label="Completion rate"
                    value={`${formatNumber(rows.length ? (completed / rows.length) * 100 : 0, 0)}%`}
                    tone={completed === rows.length ? "text-verified" : "text-warm"}
                  />
                </div>
                <div className="p-4">
                  <Reading label="Median duration" value={formatDuration(median)} />
                </div>
                <div className="p-4">
                  <Reading
                    label="Domains reached"
                    value={new Set(rows.flatMap((run) => run.domains)).size}
                    hint="distinct specialists routed to"
                  />
                </div>
              </div>
            </Panel>

            <Panel>
              <PanelHeader eyebrow="Trajectory" title="Turn log" meta="Most recent first" />
              <DataTable
                caption="Agent turns with routing and timing"
                rows={rows}
                rowKey={(row) => row.id}
                emptyTitle="No agent turns yet"
                emptyBody="Ask the agent something and the turn will be recorded here."
                columns={[
                  {
                    key: "started",
                    header: "Started",
                    cell: (row) => <span className="ident">{formatTimestamp(row.started_at)}</span>,
                  },
                  {
                    key: "domains",
                    header: "Routed to",
                    cell: (row) =>
                      row.domains.length === 0 ? (
                        <span className="text-ink-faint">no tool call</span>
                      ) : (
                        <span className="flex flex-wrap gap-1">
                          {row.domains.map((domain) => (
                            <span
                              key={domain}
                              className="bg-cold-wash text-cold rounded-chip px-1.5 py-0.5 text-[10px] font-semibold"
                            >
                              {humanise(domain)}
                            </span>
                          ))}
                        </span>
                      ),
                  },
                  {
                    key: "model",
                    header: "Model",
                    hideBelow: "md",
                    cell: (row) => <Ident className="text-ink-dim">{row.model ?? "—"}</Ident>,
                  },
                  {
                    key: "duration",
                    header: "Duration",
                    align: "right",
                    cell: (row) => <span className="ident">{formatDuration(row.duration_ms)}</span>,
                  },
                  {
                    key: "correlation",
                    header: "Correlation",
                    hideBelow: "xl",
                    cell: (row) => (
                      <Ident
                        className="text-ink-faint text-[10px]"
                        title="Ties this turn to its audit entries"
                      >
                        {row.correlation_id.slice(0, 8)}
                      </Ident>
                    ),
                  },
                  { key: "status", header: "Status", cell: (row) => <Verdict status={row.status} /> },
                ]}
              />
            </Panel>
          </div>
        )}
      </Loaded>
    </Shell>
  );
}
