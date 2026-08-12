"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { QMSMetricsChart } from "@/components/QMSMetricsChart";
import { Shell } from "@/components/Shell";
import { DataTable } from "@/components/ui/data-table";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { SpanBar } from "@/components/ui/span-bar";
import { EmptyState, LoadingView } from "@/components/ui/states";
import { Ident, RevisionTag, Verdict } from "@/components/ui/verdict";
import { formatDate, formatQuantity, formatTimestamp, humanise } from "@/lib/format";
import { Loaded, useResource } from "@/lib/use-resource";
import { cn } from "@/lib/utils";
import type {
  LabTestRecord,
  MetricSummary,
  NonConformance,
  QmsResponse,
  UnitGenealogy,
  UnitSummary,
} from "@/lib/types";

const DEFAULT_SERIAL = "ECL-M-097";

/** `temperature_span_delta_K` → `Temperature span`. The unit is shown separately. */
function metricLabel(metric: string): string {
  return humanise(metric.replace(/_(delta_K|mbar|W|hz|Hz)$/i, "").replace(/_/g, " "));
}

/**
 * Quality: one built article at a time.
 *
 * Acceptance metrics are drawn against their protocol limits rather than
 * printed as bare numbers, because "15.4" means nothing until you know the
 * floor is 15.0. The verdicts shown are the ones stored at the time of the
 * test — tightening a limit later does not retroactively fail a unit that
 * passed, and this screen must not imply otherwise.
 */
export default function QualityPage() {
  return (
    <React.Suspense fallback={<LoadingView />}>
      <Quality />
    </React.Suspense>
  );
}

function Quality() {
  const router = useRouter();
  const params = useSearchParams();
  const serial = params.get("serial") ?? DEFAULT_SERIAL;

  const units = useResource<UnitSummary[]>("/api/units");
  const qms = useResource<QmsResponse>(`/api/qms/${serial}`);
  const genealogy = useResource<UnitGenealogy>(`/api/units/${serial}/genealogy`);
  const ncrs = useResource<NonConformance[]>("/api/ncrs");

  const select = (next: string) => router.replace(`/qms?serial=${next}`, { scroll: false });

  return (
    <Shell
      eyebrow="Quality · per-unit traceability"
      title={`Built article ${serial}`}
      summary="Acceptance testing against the protocol in force, and the as-built record of what went into this individual article."
      cells={
        qms.data
          ? [
              { label: "Serial", value: <Ident>{qms.data.serial_number}</Ident> },
              { label: "Built to", value: <Ident>{qms.data.part_number ?? "—"}</Ident> },
              { label: "Revision", value: qms.data.built_to_revision ?? "—" },
              { label: "Status", value: humanise(qms.data.status) },
              {
                label: "Verdict",
                value: (
                  <span className={qms.data.fail_count > 0 ? "text-breach" : "text-verified"}>
                    {qms.data.pass_count} pass / {qms.data.fail_count} fail
                  </span>
                ),
              },
            ]
          : []
      }
      onRefresh={() => {
        qms.reload();
        genealogy.reload();
        ncrs.reload();
      }}
      refreshing={qms.refreshing || genealogy.refreshing}
    >
      <div className="space-y-4">
        <Loaded resource={units} loading={null}>
          {(rows) => <UnitPicker units={rows} selected={serial} onSelect={select} />}
        </Loaded>

        <Loaded resource={qms}>{(data) => <AcceptanceTesting qms={data} />}</Loaded>

        <Loaded resource={genealogy}>{(data) => <Genealogy genealogy={data} />}</Loaded>

        <Loaded resource={ncrs}>{(rows) => <NonConformances rows={rows} serial={serial} />}</Loaded>
      </div>
    </Shell>
  );
}

function UnitPicker({
  units,
  selected,
  onSelect,
}: {
  units: UnitSummary[];
  selected: string;
  onSelect: (serial: string) => void;
}) {
  return (
    <Panel>
      <PanelHeader eyebrow="Built units" title="Pick an article" meta={`${units.length} built`} />
      <PanelBody className="flex flex-wrap gap-2">
        {units.map((unit) => {
          const active = unit.serial_number === selected;
          return (
            <button
              key={unit.serial_number}
              type="button"
              onClick={() => onSelect(unit.serial_number)}
              aria-pressed={active}
              className={cn(
                "rounded-panel min-w-0 border px-3 py-2 text-left transition-colors",
                active
                  ? "border-cold bg-cold-wash"
                  : "border-rule hover:border-rule-strong hover:bg-sunken",
              )}
            >
              <span className="flex items-center gap-2">
                <Ident className={cn("text-[13px] font-semibold", active && "text-cold")}>
                  {unit.serial_number}
                </Ident>
                <Verdict
                  label={unit.fail_count > 0 ? `${unit.fail_count} fail` : "All pass"}
                  tone={unit.fail_count > 0 ? "breach" : "verified"}
                />
              </span>
              <span className="text-ink-faint mt-1 block text-[11px]">
                {humanise(unit.status)} · built {formatDate(unit.built_at)} · {unit.plant}
              </span>
            </button>
          );
        })}
      </PanelBody>
    </Panel>
  );
}

function AcceptanceTesting({ qms }: { qms: QmsResponse }) {
  return (
    <Panel>
      <PanelHeader
        eyebrow={qms.protocol ? `Protocol ${qms.protocol}` : "No protocol in force"}
        title="Acceptance testing"
        meta={`${qms.sample_count} samples`}
      />
      <PanelBody className="space-y-5">
        {qms.summaries.length === 0 ? (
          <EmptyState
            title="No measurements recorded"
            body="This article has not been through acceptance testing yet."
          />
        ) : qms.records.length >= 2 ? (
          // With a history to show, the trajectory against the limit band says
          // more than the latest reading does — degradation is the thing an
          // acceptance metric is watched for.
          <QMSMetricsChart records={qms.records} summaries={qms.summaries} />
        ) : (
          <div className="grid gap-x-8 gap-y-5 sm:grid-cols-2">
            {qms.summaries.map((summary: MetricSummary) => (
              <SpanBar
                key={summary.metric}
                label={metricLabel(summary.metric)}
                value={summary.latest}
                unit={summary.unit}
                lower={summary.lower_limit}
                upper={summary.upper_limit}
                digits={2}
              />
            ))}
          </div>
        )}

        <DataTable
          caption="Every acceptance sample recorded against this article"
          className="border-rule rounded-panel border"
          rows={qms.records}
          rowKey={(row) => row.recorded_at}
          emptyTitle="No samples recorded"
          columns={[
            {
              key: "when",
              header: "Recorded",
              cell: (row) => <span className="ident">{formatTimestamp(row.recorded_at)}</span>,
            },
            {
              key: "span",
              header: "Span (K)",
              align: "right",
              cell: (row) => <Reading row={row} field="temperature_span_delta_K" />,
            },
            {
              key: "pressure",
              header: "Δp (mbar)",
              align: "right",
              hideBelow: "sm",
              cell: (row) => <Reading row={row} field="pressure_drop_mbar" />,
            },
            {
              key: "hz",
              header: "Cycles (Hz)",
              align: "right",
              hideBelow: "md",
              cell: (row) => <Reading row={row} field="magnetization_cycles_hz" />,
            },
            {
              key: "watts",
              header: "Capacity (W)",
              align: "right",
              hideBelow: "md",
              cell: (row) => <Reading row={row} field="cooling_capacity_W" />,
            },
            {
              key: "rig",
              header: "Rig",
              hideBelow: "lg",
              cell: (row) => <Ident className="text-ink-dim">{row.test_rig ?? "—"}</Ident>,
            },
            { key: "result", header: "Verdict", cell: (row) => <Verdict status={row.result} /> },
          ]}
        />
      </PanelBody>
    </Panel>
  );
}

/** A single measurement, marked when it is the one that broke the verdict. */
function Reading({
  row,
  field,
}: {
  row: LabTestRecord;
  field: keyof Pick<
    LabTestRecord,
    | "temperature_span_delta_K"
    | "pressure_drop_mbar"
    | "magnetization_cycles_hz"
    | "cooling_capacity_W"
  >;
}) {
  const breached = row.breaches.some((breach) => breach.metric === field);
  return (
    <span className={cn("ident", breached && "text-breach font-semibold")}>
      {formatQuantity(row[field])}
    </span>
  );
}

function Genealogy({ genealogy }: { genealogy: UnitGenealogy }) {
  return (
    <Panel>
      <PanelHeader
        eyebrow="As-built record"
        title="What went into this article"
        meta={`${genealogy.line_count} lines · ${genealogy.lots.length} lots`}
      />
      <PanelBody className="space-y-3">
        <p className="text-ink-dim text-pretty text-xs leading-5">
          A snapshot taken at build time, not a view over today&apos;s bill of
          materials. If the design has changed since, this record does not move
          — which is the only reason a recall can be scoped to the units that
          actually contain the bad material.
        </p>
        <DataTable
          caption="Components installed in this article, with their lots"
          className="border-rule rounded-panel border"
          rows={genealogy.lines}
          rowKey={(row, index) => `${row.part_number}-${index}`}
          emptyTitle="No build record"
          emptyBody="This article was not booked through a build, so nothing was captured."
          columns={[
            {
              key: "part",
              header: "Part",
              cell: (row) => (
                <span className="flex items-center gap-1.5">
                  <Ident className="font-semibold">{row.part_number}</Ident>
                  <RevisionTag revision={row.revision} />
                </span>
              ),
            },
            {
              key: "desc",
              header: "Description",
              hideBelow: "lg",
              cell: (row) => <span className="text-ink-dim line-clamp-1">{row.description}</span>,
            },
            {
              key: "qty",
              header: "Qty",
              align: "right",
              cell: (row) => (
                <span className="ident">
                  {formatQuantity(row.quantity)}
                  <span className="text-ink-faint ml-1">{row.unit_of_measure}</span>
                </span>
              ),
            },
            {
              key: "lot",
              header: "Lot",
              cell: (row) =>
                row.lot_number ? (
                  <Ident className="text-cold font-semibold">{row.lot_number}</Ident>
                ) : (
                  <span className="text-ink-faint">not lot-controlled</span>
                ),
            },
            {
              key: "supplier",
              header: "Supplier lot",
              hideBelow: "md",
              cell: (row) => <Ident className="text-ink-dim">{row.supplier_lot ?? "—"}</Ident>,
            },
            {
              key: "op",
              header: "Op",
              align: "right",
              hideBelow: "sm",
              cell: (row) => <span className="ident text-ink-dim">{row.operation_seq ?? "—"}</span>,
            },
          ]}
        />
      </PanelBody>
    </Panel>
  );
}

function NonConformances({ rows, serial }: { rows: NonConformance[]; serial: string }) {
  // A lot-scoped NCR names the units the bad material reached, so it belongs on
  // this article's screen even though it was not raised against the serial.
  const relevant = rows.filter(
    (row) => row.serial_number === serial || row.affected_units.includes(serial),
  );

  return (
    <Panel>
      <PanelHeader
        eyebrow="Non-conformance"
        title="Findings against this article"
        meta={`${relevant.length} of ${rows.length} open records`}
      />
      {relevant.length === 0 ? (
        <EmptyState
          title="No findings against this article"
          body="Nothing raised against this serial, and no lot-scoped finding reaches it."
        />
      ) : (
        <PanelBody className="space-y-3">
          {relevant.map((ncr) => (
            <article key={ncr.id} className="border-rule rounded-panel border p-3">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <Ident className="text-cold text-[13px] font-semibold">{ncr.number}</Ident>
                <span className="min-w-0 flex-1 truncate text-sm font-semibold">{ncr.title}</span>
                <Verdict status={ncr.severity} tone={ncr.severity === "Critical" ? "breach" : "warm"} />
                <Verdict status={ncr.status} />
              </div>

              <p className="text-ink-dim mt-1.5 text-pretty text-xs leading-5">{ncr.description}</p>

              <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-[11px]">
                <div>
                  <dt className="eyebrow">Scope</dt>
                  <dd className="ident mt-0.5">
                    {ncr.lot_number
                      ? `lot ${ncr.lot_number}`
                      : (ncr.serial_number ?? ncr.part_number ?? "—")}
                  </dd>
                </div>
                <div>
                  <dt className="eyebrow">Disposition</dt>
                  <dd className="mt-0.5">{humanise(ncr.disposition)}</dd>
                </div>
                <div>
                  <dt className="eyebrow">Raised</dt>
                  <dd className="mt-0.5">
                    {formatDate(ncr.raised_at)} by {ncr.raised_by_label}
                  </dd>
                </div>
                {ncr.escalated_ecr_number && (
                  <div>
                    <dt className="eyebrow">Escalated to</dt>
                    <dd className="mt-0.5">
                      <Ident className="text-cold font-semibold">{ncr.escalated_ecr_number}</Ident>
                    </dd>
                  </div>
                )}
              </dl>

              {ncr.actions.length > 0 && (
                <ul className="border-rule mt-3 space-y-1.5 border-t pt-3">
                  {ncr.actions.map((action, index) => (
                    <li key={index} className="flex items-start gap-2 text-[11px] leading-4">
                      <Verdict
                        label={humanise(action.kind)}
                        tone={action.completed_at ? "verified" : "warm"}
                      />
                      <span className="text-ink-dim min-w-0 flex-1">
                        {action.description}
                        {action.owner_label && ` — ${action.owner_label}`}
                        {action.due_date && ` · due ${formatDate(action.due_date)}`}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </article>
          ))}
        </PanelBody>
      )}
    </Panel>
  );
}
