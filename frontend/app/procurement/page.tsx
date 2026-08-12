"use client";

import { Shell } from "@/components/Shell";
import { DataTable } from "@/components/ui/data-table";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { SpanBar } from "@/components/ui/span-bar";
import { EmptyState } from "@/components/ui/states";
import { Ident, Verdict } from "@/components/ui/verdict";
import { formatDate, formatMoney, formatQuantity, humanise } from "@/lib/format";
import { Loaded, useResource } from "@/lib/use-resource";
import { cn } from "@/lib/utils";
import type { PurchaseOrder, StockRisk } from "@/lib/types";

/**
 * Procurement.
 *
 * Cover is drawn against the reorder level, and the list is ordered by lead
 * time rather than by part number: a shortfall on a ninety-day magnet array is
 * this morning's problem, and a shortfall on a stock seal is not.
 */
export default function ProcurementPage() {
  const stock = useResource<StockRisk[]>("/api/procurement/stock-risk");
  const orders = useResource<PurchaseOrder[]>("/api/procurement/purchase-orders");

  const atRisk = stock.data?.filter((row) => row.low_stock).length ?? 0;
  const committed =
    orders.data
      ?.filter((order) => order.status !== "received")
      .reduce((sum, order) => sum + order.value, 0) ?? 0;

  return (
    <Shell
      eyebrow="Supply · stock and orders"
      title="Cover and commitment"
      summary="Available stock against reorder levels, and the open purchase orders that will close the gap."
      cells={
        stock.data
          ? [
              { label: "Items tracked", value: stock.data.length },
              {
                label: "Below reorder",
                value: <span className={atRisk > 0 ? "text-warm" : "text-verified"}>{atRisk}</span>,
              },
              { label: "Committed", value: formatMoney(committed) },
            ]
          : []
      }
      onRefresh={() => {
        stock.reload();
        orders.reload();
      }}
      refreshing={stock.refreshing || orders.refreshing}
    >
      <div className="space-y-4">
        <Panel>
          <PanelHeader
            eyebrow="Stock cover"
            title="Available against reorder level"
            meta="Longest lead time first"
          />
          <Loaded resource={stock}>
            {(rows) =>
              rows.length === 0 ? (
                <EmptyState
                  title="No stock positions"
                  body="Receive a purchase order to open a stock position."
                />
              ) : (
                <PanelBody className="grid gap-x-8 gap-y-5 lg:grid-cols-2">
                  {rows.map((row) => (
                    <SpanBar
                      key={row.part_number}
                      label={row.part_number}
                      value={row.available}
                      unit="pcs"
                      lower={row.reorder_level}
                      digits={0}
                      tone={row.low_stock ? "breach" : undefined}
                      note={
                        row.lead_time_days
                          ? `${row.on_hand} on hand · ${row.allocated} allocated · ${row.lead_time_days}-day lead`
                          : `${row.on_hand} on hand · ${row.allocated} allocated`
                      }
                    />
                  ))}
                </PanelBody>
              )
            }
          </Loaded>
        </Panel>

        <Loaded resource={orders}>
          {(rows) =>
            rows.length === 0 ? (
              <Panel>
                <PanelHeader eyebrow="Purchase orders" title="What is on order" />
                <EmptyState
                  title="Nothing on order"
                  body="No purchase order is open against this product line."
                />
              </Panel>
            ) : (
              <div className="space-y-4">
                {rows.map((order) => (
                  <Panel key={order.order_number}>
                    <PanelHeader
                      eyebrow={`${order.supplier_code} · ${order.supplier}`}
                      title={
                        <span className="flex flex-wrap items-baseline gap-x-2">
                          <Ident className="text-cold">{order.order_number}</Ident>
                          <span className="text-ink-dim text-xs font-normal">
                            ordered {formatDate(order.ordered_at)} · required{" "}
                            {formatDate(order.required_date)}
                          </span>
                        </span>
                      }
                      action={
                        <span className="flex shrink-0 items-center gap-2">
                          <span className="ident text-sm font-semibold">
                            {formatMoney(order.value, order.currency)}
                          </span>
                          <Verdict status={humanise(order.status)} />
                        </span>
                      }
                    />
                    <DataTable
                      caption={`Lines on purchase order ${order.order_number}`}
                      rows={order.lines}
                      rowKey={(line) => String(line.line_number)}
                      emptyTitle="No lines on this order"
                      columns={[
                        {
                          key: "line",
                          header: "Line",
                          cell: (line) => <Ident className="text-ink-faint">{line.line_number}</Ident>,
                        },
                        {
                          key: "part",
                          header: "Part",
                          cell: (line) => <Ident className="font-semibold">{line.part_number}</Ident>,
                        },
                        {
                          key: "qty",
                          header: "Ordered",
                          align: "right",
                          cell: (line) => <span className="ident">{formatQuantity(line.quantity)}</span>,
                        },
                        {
                          key: "received",
                          header: "Received",
                          align: "right",
                          cell: (line) => (
                            <span
                              className={cn(
                                "ident",
                                line.received_quantity >= line.quantity ? "text-verified" : "text-warm",
                              )}
                            >
                              {formatQuantity(line.received_quantity)}
                            </span>
                          ),
                        },
                        {
                          key: "price",
                          header: "Unit price",
                          align: "right",
                          hideBelow: "sm",
                          cell: (line) => formatMoney(line.unit_price, order.currency),
                        },
                        {
                          key: "ext",
                          header: "Extended",
                          align: "right",
                          hideBelow: "md",
                          cell: (line) => (
                            <span className="font-semibold">
                              {formatMoney(line.quantity * line.unit_price, order.currency)}
                            </span>
                          ),
                        },
                      ]}
                    />
                  </Panel>
                ))}
              </div>
            )
          }
        </Loaded>
      </div>
    </Shell>
  );
}
