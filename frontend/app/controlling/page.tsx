"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Shell } from "@/components/Shell";
import { DataTable } from "@/components/ui/data-table";
import { Panel, PanelBody, PanelHeader, Reading } from "@/components/ui/panel";
import { LoadingView } from "@/components/ui/states";
import { Ident } from "@/components/ui/verdict";
import { formatMoney, formatNumber, formatQuantity } from "@/lib/format";
import { Loaded, useResource } from "@/lib/use-resource";
import { cn } from "@/lib/utils";
import type { CostRollup } from "@/lib/types";

const PRODUCT = "ECL-SYS-1000";
const BATCHES = [1, 10, 50, 250] as const;

/**
 * Controlling.
 *
 * The rollup is recursive over the manufacturing bill, so the interesting fact
 * is never the total — it is which handful of lines carry it. The composition
 * bar answers that before the tables do: on this product two components are
 * most of the cost, and every sourcing conversation starts there.
 */
export default function ControllingPage() {
  return (
    <React.Suspense fallback={<LoadingView />}>
      <Controlling />
    </React.Suspense>
  );
}

function Controlling() {
  const router = useRouter();
  const params = useSearchParams();
  const batch = Number(params.get("batch")) || 10;

  const rollup = useResource<CostRollup>(
    `/api/controlling/rollup/${PRODUCT}?batch_size=${batch}`,
  );

  return (
    <Shell
      eyebrow="Controlling · standard cost"
      title="Product cost rollup"
      summary="Material cost from the manufacturing bill and labour from the routing, compounded through every level of the structure."
      cells={
        rollup.data
          ? [
              { label: "Product", value: <Ident>{rollup.data.part_number}</Ident> },
              { label: "Revision", value: rollup.data.revision },
              { label: "Batch", value: formatQuantity(rollup.data.batch_size) },
              {
                label: "Unit cost",
                value: formatMoney(rollup.data.total_cost, rollup.data.currency),
              },
            ]
          : []
      }
      onRefresh={rollup.reload}
      refreshing={rollup.refreshing}
    >
      <Loaded resource={rollup}>
        {(data) => (
          <div className="space-y-4">
            <Panel>
              <PanelHeader
                eyebrow="Cost composition"
                title="Where the money goes"
                action={
                  <div className="border-rule rounded-chip flex shrink-0 border p-0.5" role="group" aria-label="Batch size">
                    {BATCHES.map((size) => (
                      <button
                        key={size}
                        type="button"
                        onClick={() => router.replace(`/controlling?batch=${size}`, { scroll: false })}
                        aria-pressed={batch === size}
                        className={cn(
                          "rounded-chip px-2 py-1 text-[11px] font-semibold transition-colors",
                          batch === size ? "bg-cold text-cold-ink" : "text-ink-dim hover:text-ink",
                        )}
                      >
                        ×{size}
                      </button>
                    ))}
                  </div>
                }
              />
              <PanelBody className="space-y-5">
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <Reading label="Material" value={formatMoney(data.material_cost, data.currency)} />
                  <Reading label="Labour" value={formatMoney(data.labour_cost, data.currency)} />
                  <Reading
                    label="Total per unit"
                    value={formatMoney(data.total_cost, data.currency)}
                    tone="text-cold"
                  />
                  <Reading
                    label={`Batch of ${formatQuantity(data.batch_size)}`}
                    value={formatMoney(data.total_cost * data.batch_size, data.currency)}
                    hint="material and labour at standard"
                  />
                </div>
                <CompositionBar rollup={data} />
              </PanelBody>
            </Panel>

            <Panel>
              <PanelHeader
                eyebrow="Material"
                title="Components at standard cost"
                meta={`${data.materials.length} lines`}
              />
              <DataTable
                caption="Material lines contributing to the rollup"
                rows={[...data.materials].sort((a, b) => (b.extended_cost ?? 0) - (a.extended_cost ?? 0))}
                rowKey={(row, index) => `${row.part_number}-${index}`}
                columns={[
                  {
                    key: "part",
                    header: "Part",
                    cell: (row) => <Ident className="font-semibold">{row.part_number}</Ident>,
                  },
                  {
                    key: "qty",
                    header: "Extended qty",
                    align: "right",
                    cell: (row) => <span className="ident">{formatQuantity(row.extended_quantity)}</span>,
                  },
                  {
                    key: "unit",
                    header: "Standard",
                    align: "right",
                    hideBelow: "sm",
                    cell: (row) => formatMoney(row.standard_cost, data.currency),
                  },
                  {
                    key: "ext",
                    header: "Extended",
                    align: "right",
                    cell: (row) => (
                      <span className="font-semibold">{formatMoney(row.extended_cost, data.currency)}</span>
                    ),
                  },
                  {
                    key: "share",
                    header: "Share",
                    align: "right",
                    hideBelow: "md",
                    cell: (row) => (
                      <span className="text-ink-dim">
                        {formatNumber(((row.extended_cost ?? 0) / data.total_cost) * 100, 1)}%
                      </span>
                    ),
                  },
                ]}
              />
            </Panel>

            <Panel>
              <PanelHeader
                eyebrow="Labour"
                title="Routing operations"
                meta={`${data.labour.length} operations`}
              />
              <DataTable
                caption="Routing operations and their labour cost"
                rows={data.labour}
                rowKey={(row) => String(row.operation_seq)}
                columns={[
                  {
                    key: "seq",
                    header: "Op",
                    cell: (row) => <Ident className="font-semibold">{row.operation_seq}</Ident>,
                  },
                  {
                    key: "wc",
                    header: "Work centre",
                    cell: (row) => <Ident>{row.work_center}</Ident>,
                  },
                  {
                    key: "minutes",
                    header: "Minutes/unit",
                    align: "right",
                    cell: (row) => <span className="ident">{formatQuantity(row.minutes_per_unit)}</span>,
                  },
                  {
                    key: "rate",
                    header: "Rate/hour",
                    align: "right",
                    hideBelow: "sm",
                    cell: (row) => formatMoney(row.hourly_rate, data.currency),
                  },
                  {
                    key: "cost",
                    header: "Cost",
                    align: "right",
                    cell: (row) => (
                      <span className="font-semibold">{formatMoney(row.cost, data.currency)}</span>
                    ),
                  },
                ]}
              />
            </Panel>
          </div>
        )}
      </Loaded>
    </Shell>
  );
}

/**
 * The whole unit cost as one bar, biggest contributors first. Anything under
 * two percent is folded into a remainder rather than drawn as a sliver nobody
 * can see or click.
 */
function CompositionBar({ rollup }: { rollup: CostRollup }) {
  const segments = [
    ...rollup.materials.map((line) => ({
      label: line.part_number,
      value: line.extended_cost ?? 0,
      kind: "material" as const,
    })),
    {
      label: "Labour",
      value: rollup.labour_cost,
      kind: "labour" as const,
    },
  ].sort((a, b) => b.value - a.value);

  const threshold = rollup.total_cost * 0.02;
  const major = segments.filter((segment) => segment.value >= threshold);
  const minorTotal = segments
    .filter((segment) => segment.value < threshold)
    .reduce((sum, segment) => sum + segment.value, 0);
  if (minorTotal > 0) {
    major.push({ label: "Everything else", value: minorTotal, kind: "material" });
  }

  return (
    <div>
      <div className="bg-sunken flex h-3 w-full overflow-hidden rounded-full">
        {major.map((segment, index) => (
          <div
            key={segment.label}
            title={`${segment.label}: ${formatMoney(segment.value, rollup.currency)}`}
            style={{ width: `${(segment.value / rollup.total_cost) * 100}%` }}
            className={cn(
              segment.kind === "labour"
                ? "bg-warm"
                : index === 0
                  ? "bg-cold"
                  : index === 1
                    ? "bg-mat-fluid"
                    : "bg-mat-steel",
              "border-panel border-r last:border-r-0",
            )}
          />
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
        {major.map((segment, index) => (
          <li key={segment.label} className="flex items-center gap-1.5 text-[11px]">
            <span
              aria-hidden="true"
              className={cn(
                "size-2 rounded-full",
                segment.kind === "labour"
                  ? "bg-warm"
                  : index === 0
                    ? "bg-cold"
                    : index === 1
                      ? "bg-mat-fluid"
                      : "bg-mat-steel",
              )}
            />
            <Ident className="font-semibold">{segment.label}</Ident>
            <span className="text-ink-faint">
              {formatNumber((segment.value / rollup.total_cost) * 100, 0)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
