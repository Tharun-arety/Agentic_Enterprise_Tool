"use client";

import Link from "next/link";
import { Shell } from "@/components/Shell";
import { DataTable } from "@/components/ui/data-table";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { Ident, Verdict } from "@/components/ui/verdict";
import { formatDate, formatMoney, formatTimestamp, humanise } from "@/lib/format";
import { Loaded, useResource } from "@/lib/use-resource";
import type { DeployedUnit, FieldEvent, Opportunity } from "@/lib/types";

/**
 * Customers.
 *
 * The reason this domain lives beside engineering rather than in a separate
 * sales tool is the deployed-unit table: each row is a serial, and the serial
 * links straight to the acceptance testing and as-built record for that exact
 * article. An account conversation and a quality investigation are looking at
 * the same object.
 */
export default function CustomersPage() {
  const opportunities = useResource<Opportunity[]>("/api/crm/opportunities");
  const deployed = useResource<DeployedUnit[]>("/api/crm/deployed-units");
  const history = useResource<FieldEvent[]>("/api/crm/field-history");

  const pipeline = opportunities.data?.reduce((sum, row) => sum + row.value, 0) ?? 0;

  return (
    <Shell
      eyebrow="Customers · pipeline and field"
      title="Accounts and installed base"
      summary="Open opportunities, the units running at customer sites and everything that has happened to them since commissioning."
      cells={
        opportunities.data
          ? [
              { label: "Opportunities", value: opportunities.data.length },
              { label: "Pipeline", value: formatMoney(pipeline, "EUR", 0) },
              { label: "Units in field", value: deployed.data?.length ?? "—" },
            ]
          : []
      }
      onRefresh={() => {
        opportunities.reload();
        deployed.reload();
        history.reload();
      }}
      refreshing={opportunities.refreshing || deployed.refreshing}
    >
      <div className="space-y-4">
        <Panel>
          <PanelHeader eyebrow="Pipeline" title="Open opportunities" />
          <Loaded resource={opportunities}>
            {(rows) => (
              <DataTable
                caption="Open sales opportunities"
                rows={rows}
                rowKey={(row) => row.id}
                emptyTitle="No open opportunities"
                emptyBody="Qualify a lead to open an opportunity."
                columns={[
                  { key: "title", header: "Opportunity", cell: (row) => <span className="font-medium">{row.title}</span> },
                  { key: "customer", header: "Customer", cell: (row) => row.customer_name },
                  { key: "stage", header: "Stage", cell: (row) => <Verdict status={row.stage} /> },
                  {
                    key: "value",
                    header: "Value",
                    align: "right",
                    cell: (row) => (
                      <span className="font-semibold">{formatMoney(row.value, row.currency, 0)}</span>
                    ),
                  },
                  {
                    key: "close",
                    header: "Expected close",
                    hideBelow: "sm",
                    cell: (row) => <span className="ident">{formatDate(row.expected_close)}</span>,
                  },
                ]}
              />
            )}
          </Loaded>
        </Panel>

        <Panel>
          <PanelHeader
            eyebrow="Installed base"
            title="Units at customer sites"
            meta="Each serial links to its own test evidence"
          />
          <Loaded resource={deployed}>
            {(rows) => (
              <DataTable
                caption="Units commissioned at customer sites"
                rows={rows}
                rowKey={(row) => row.serial_number}
                emptyTitle="Nothing commissioned"
                emptyBody="No built unit has been commissioned at a customer site."
                columns={[
                  {
                    key: "serial",
                    header: "Serial",
                    cell: (row) => (
                      <Link
                        href={`/qms?serial=${row.serial_number}`}
                        className="text-cold hover:text-ink font-semibold transition-colors"
                      >
                        <Ident>{row.serial_number}</Ident>
                      </Link>
                    ),
                  },
                  { key: "part", header: "Built to", hideBelow: "sm", cell: (row) => <Ident>{row.part_number}</Ident> },
                  { key: "customer", header: "Customer", cell: (row) => row.customer_name },
                  {
                    key: "site",
                    header: "Site",
                    hideBelow: "md",
                    cell: (row) => (
                      <span className="block">
                        {row.site_name}
                        <span className="text-ink-faint block text-[11px]">{row.address ?? ""}</span>
                      </span>
                    ),
                  },
                  {
                    key: "commissioned",
                    header: "Commissioned",
                    hideBelow: "lg",
                    cell: (row) => <span className="ident">{formatDate(row.commissioned_at)}</span>,
                  },
                  { key: "status", header: "Site status", cell: (row) => <Verdict status={humanise(row.status)} /> },
                  {
                    key: "unit",
                    header: "Unit status",
                    hideBelow: "sm",
                    cell: (row) => <Verdict status={row.unit_status} />,
                  },
                ]}
              />
            )}
          </Loaded>
        </Panel>

        <Panel>
          <PanelHeader eyebrow="Field history" title="What has happened since" />
          <Loaded resource={history}>
            {(rows) => (
              <DataTable
                caption="Field events recorded against deployed units"
                rows={rows}
                rowKey={(row) => row.id}
                emptyTitle="Nothing reported from the field"
                emptyBody="No service visit, fault or return has been recorded."
                columns={[
                  { key: "when", header: "Occurred", cell: (row) => <span className="ident">{formatTimestamp(row.occurred_at)}</span> },
                  {
                    key: "serial",
                    header: "Serial",
                    cell: (row) => (
                      <Link
                        href={`/qms?serial=${row.serial_number}`}
                        className="text-cold hover:text-ink font-semibold transition-colors"
                      >
                        <Ident>{row.serial_number}</Ident>
                      </Link>
                    ),
                  },
                  { key: "type", header: "Event", cell: (row) => <Verdict status={humanise(row.event_type)} /> },
                  { key: "summary", header: "Summary", cell: (row) => <span className="text-ink-dim">{row.summary}</span> },
                  {
                    key: "resolution",
                    header: "Resolution",
                    hideBelow: "lg",
                    cell: (row) => (
                      <span className="text-ink-dim">
                        {row.resolution ?? <span className="text-warm">still open</span>}
                      </span>
                    ),
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
