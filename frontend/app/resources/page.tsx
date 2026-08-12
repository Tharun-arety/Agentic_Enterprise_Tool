"use client";

import { Shell } from "@/components/Shell";
import { DataTable } from "@/components/ui/data-table";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { SpanBar } from "@/components/ui/span-bar";
import { EmptyState } from "@/components/ui/states";
import { Ident } from "@/components/ui/verdict";
import { formatDate, formatNumber } from "@/lib/format";
import { Loaded, useResource } from "@/lib/use-resource";
import type { CapacityRow, TimesheetRow } from "@/lib/types";

/**
 * Resourcing.
 *
 * Booked hours against the week's capacity, per named engineer, with the work
 * packages the booking came from. An overloaded week that will not say which
 * package overloaded it is a number nobody can act on.
 */
export default function ResourcingPage() {
  const capacity = useResource<CapacityRow[]>("/api/resources/capacity");
  const timesheets = useResource<TimesheetRow[]>("/api/resources/timesheets");

  const overloaded = capacity.data?.filter((row) => row.overloaded).length ?? 0;
  const booked = capacity.data?.reduce((sum, row) => sum + row.allocated_hours, 0) ?? 0;

  return (
    <Shell
      eyebrow="Resourcing · weekly capacity"
      title="Who is committed to what"
      summary="Allocated hours against each engineer's capacity for the week, and the time actually booked against work packages."
      cells={
        capacity.data
          ? [
              { label: "Engineer-weeks", value: capacity.data.length },
              { label: "Hours booked", value: formatNumber(booked, 0) },
              {
                label: "Overloaded",
                value: (
                  <span className={overloaded > 0 ? "text-breach" : "text-verified"}>{overloaded}</span>
                ),
              },
            ]
          : []
      }
      onRefresh={() => {
        capacity.reload();
        timesheets.reload();
      }}
      refreshing={capacity.refreshing || timesheets.refreshing}
    >
      <div className="space-y-4">
        <Panel>
          <PanelHeader eyebrow="Capacity" title="Allocation against availability" />
          <Loaded resource={capacity}>
            {(rows) =>
              rows.length === 0 ? (
                <EmptyState
                  title="No capacity recorded"
                  body="Capacity is set per engineer per week; none has been entered."
                />
              ) : (
                <PanelBody className="grid gap-x-8 gap-y-5 lg:grid-cols-2">
                  {rows.map((row) => (
                    <SpanBar
                      key={`${row.user_id}-${row.week_start}`}
                      label={`${row.engineer ?? "Unassigned"} · week of ${formatDate(row.week_start)}`}
                      value={row.allocated_hours}
                      unit="h"
                      upper={row.available_hours}
                      digits={0}
                      tone={row.overloaded ? "breach" : undefined}
                      note={
                        row.packages.length > 0
                          ? row.packages
                              .map((entry) => `${entry.work_package} ${formatNumber(entry.hours, 0)}h`)
                              .join(" · ")
                          : "no packages booked"
                      }
                    />
                  ))}
                </PanelBody>
              )
            }
          </Loaded>
        </Panel>

        <Panel>
          <PanelHeader eyebrow="Timesheets" title="Time booked" />
          <Loaded resource={timesheets}>
            {(rows) => (
              <DataTable
                caption="Time booked against work packages"
                rows={rows}
                rowKey={(row) => row.id}
                emptyTitle="No time booked"
                emptyBody="Engineers book hours against a work package; none has been recorded."
                columns={[
                  { key: "date", header: "Date", cell: (row) => <span className="ident">{formatDate(row.work_date)}</span> },
                  { key: "who", header: "Engineer", cell: (row) => row.engineer },
                  {
                    key: "wp",
                    header: "Work package",
                    cell: (row) =>
                      row.work_package ? (
                        <Ident className="font-semibold">{row.work_package}</Ident>
                      ) : (
                        <span className="text-ink-faint">unallocated</span>
                      ),
                  },
                  {
                    key: "hours",
                    header: "Hours",
                    align: "right",
                    cell: (row) => <span className="ident">{formatNumber(row.hours, 1)}</span>,
                  },
                  {
                    key: "what",
                    header: "Description",
                    hideBelow: "md",
                    cell: (row) => <span className="text-ink-dim line-clamp-1">{row.description ?? "—"}</span>,
                  },
                ]}
              />
            )}
          </Loaded>
        </Panel>
      </div>
    </Shell>
  );
}
