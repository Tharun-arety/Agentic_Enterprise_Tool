"use client";

import * as React from "react";
import { ChevronRight } from "lucide-react";
import { Shell } from "@/components/Shell";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/states";
import { Ident, RevisionTag, Verdict } from "@/components/ui/verdict";
import { formatMoney, formatTimestamp, humanise } from "@/lib/format";
import { toneFor } from "@/lib/status";
import { Loaded, useResource } from "@/lib/use-resource";
import { cn } from "@/lib/utils";
import type { ChangeRequest, ImpactAssessment, Quorum } from "@/lib/types";

/**
 * Engineering change.
 *
 * The board seats are the point of this screen. A change request is not a
 * ticket with a status field — it is four named functions each of which can
 * stop it, and the reason one of them stopped it matters more than the count
 * of approvals. So the seats are drawn as seats, including the empty ones.
 */
export default function EngineeringChangePage() {
  const requests = useResource<ChangeRequest[]>("/api/ecm/requests");

  const open = requests.data?.filter((request) => request.quorum && !request.quorum.satisfied).length ?? 0;

  return (
    <Shell
      eyebrow="Engineering change · ISO 10007"
      title="Change requests and the board"
      summary="Every configuration change passes a request, a generated impact assessment and four board seats before an order releases it."
      cells={
        requests.data
          ? [
              { label: "Requests", value: requests.data.length },
              { label: "Awaiting board", value: open },
            ]
          : []
      }
      onRefresh={requests.reload}
      refreshing={requests.refreshing}
    >
      <Loaded resource={requests}>
        {(data) =>
          data.length === 0 ? (
            <Panel>
              <EmptyState
                title="No change requests raised"
                body="A non-conformance can escalate into a change request from the quality screen."
              />
            </Panel>
          ) : (
            <div className="space-y-4">
              {data.map((request) => (
                <RequestPanel key={request.id} request={request} />
              ))}
            </div>
          )
        }
      </Loaded>
    </Shell>
  );
}

function RequestPanel({ request }: { request: ChangeRequest }) {
  return (
    <Panel>
      <PanelHeader
        eyebrow={`${humanise(request.origin)} origin · raised by ${request.originator_label ?? "unknown"}`}
        title={
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <Ident className="text-cold">{request.number}</Ident>
            <span>{request.title}</span>
          </span>
        }
        action={
          <span className="flex shrink-0 items-center gap-1.5">
            <Verdict
              status={request.priority}
              tone={request.priority.toLowerCase() === "urgent" ? "breach" : "warm"}
            />
            <Verdict status={request.status} />
          </span>
        }
      />

      <PanelBody className="space-y-5">
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <p className="eyebrow mb-1.5">Problem</p>
            <p className="text-ink-dim text-pretty text-xs leading-5">{request.problem_statement}</p>
          </div>
          <div>
            <p className="eyebrow mb-1.5">Proposed solution</p>
            <p className="text-ink-dim text-pretty text-xs leading-5">
              {request.proposed_solution ?? "Not yet proposed."}
            </p>
          </div>
        </div>

        {request.affected_part_numbers.length > 0 && (
          <div>
            <p className="eyebrow mb-1.5">Configuration items named</p>
            <div className="flex flex-wrap gap-1.5">
              {request.affected_part_numbers.map((part) => (
                <Ident
                  key={part}
                  className="border-rule rounded-chip bg-sunken px-1.5 py-0.5 text-[11px] font-semibold"
                >
                  {part}
                </Ident>
              ))}
            </div>
          </div>
        )}

        {request.quorum && <BoardSeats quorum={request.quorum} reviews={request.reviews} />}

        {request.latest_assessment && <Impact assessment={request.latest_assessment} />}
      </PanelBody>
    </Panel>
  );
}

function BoardSeats({
  quorum,
  reviews,
}: {
  quorum: Quorum;
  reviews: ChangeRequest["reviews"];
}) {
  const bySeat = new Map(reviews.map((review) => [review.seat, review]));

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <p className="eyebrow">Change control board</p>
        <p className="text-ink-faint text-[11px]">
          {quorum.voted_seats.length} of {quorum.required_seats.length} seats voted ·{" "}
          <span className={cn("font-semibold", quorum.satisfied ? "text-verified" : "text-warm")}>
            {humanise(quorum.verdict)}
          </span>
        </p>
      </div>

      <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {quorum.required_seats.map((seat) => {
          const review = bySeat.get(seat);
          const tone = review ? toneFor(review.decision) : "neutral";
          return (
            <li
              key={seat}
              className={cn(
                "border-rule rounded-panel border p-3",
                // The seat's own edge carries its ruling, so the board reads at
                // a glance without hunting for four small chips.
                tone === "verified" && "border-l-verified border-l-2",
                tone === "breach" && "border-l-breach border-l-2",
                tone === "warm" && "border-l-warm border-l-2",
              )}
            >
              <p className="eyebrow">{humanise(seat)}</p>
              <div className="mt-1.5">
                {review ? (
                  <Verdict status={review.decision} />
                ) : (
                  <span className="text-ink-faint text-[11px] font-semibold">Not yet voted</span>
                )}
              </div>
              {review && (
                <>
                  <p className="text-ink-faint mt-1.5 truncate text-[11px]">{review.reviewer_label}</p>
                  {review.comment && (
                    <p className="text-ink-dim mt-1.5 text-pretty text-[11px] leading-4">
                      {review.comment}
                    </p>
                  )}
                </>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Impact({ assessment }: { assessment: ImpactAssessment }) {
  const { findings } = assessment;
  const costRows = findings.cost_impact.filter((row) => row.delta !== null);

  return (
    <details className="border-rule rounded-panel group border">
      <summary className="hover:bg-sunken flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 transition-colors">
        <ChevronRight
          className="text-ink-faint size-3.5 shrink-0 transition-transform group-open:rotate-90"
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1">
          <span className="eyebrow">Impact assessment · generated {formatTimestamp(assessment.generated_at)}</span>
          <span className="mt-0.5 block text-pretty text-xs leading-5">{assessment.summary}</span>
        </span>
      </summary>

      <div className="border-rule space-y-4 border-t p-3">
        <div className="grid gap-4 md:grid-cols-2">
          <ImpactList
            title="Products reached"
            empty="No finished product reaches this item."
            items={findings.affected_products.map((product) => ({
              key: product.part_number,
              primary: (
                <>
                  <Ident className="font-semibold">{product.part_number}</Ident>{" "}
                  <RevisionTag revision={product.revision} />
                </>
              ),
              secondary: `via ${product.reached_via.join(", ")}`,
            }))}
          />
          <ImpactList
            title="Assemblies to re-release"
            empty="No parent assembly is affected."
            items={findings.affected_assemblies.map((assembly) => ({
              key: `${assembly.part_number}-${assembly.depth}`,
              primary: (
                <>
                  <Ident className="font-semibold">{assembly.part_number}</Ident>{" "}
                  <RevisionTag revision={assembly.revision} />
                </>
              ),
              secondary: `level ${assembly.depth} · quantity ${assembly.quantity}`,
            }))}
          />
          <ImpactList
            title="Documents to revise"
            empty="No controlled document references this item."
            items={findings.affected_documents.map((document) => ({
              key: document.document_number,
              primary: (
                <>
                  <Ident className="font-semibold">{document.document_number}</Ident>{" "}
                  <RevisionTag revision={document.latest_revision} />
                </>
              ),
              secondary: `${document.kind} · ${document.title}`,
            }))}
          />
          <ImpactList
            title="Baselines affected"
            empty="No frozen baseline contains this item."
            items={findings.affected_baselines.map((baseline) => ({
              key: baseline,
              primary: baseline,
            }))}
          />
        </div>

        <div>
          <p className="eyebrow mb-2">Units needing revalidation</p>
          <DataTable
            caption="Built units whose acceptance testing must be repeated"
            className="border-rule rounded-panel border"
            rows={findings.revalidation_required}
            rowKey={(row) => row.serial_number}
            emptyTitle="Nothing to revalidate"
            emptyBody="No built unit carries the affected item, so no acceptance test has to be repeated."
            columns={[
              {
                key: "serial",
                header: "Serial",
                cell: (row) => <Ident className="text-cold font-semibold">{row.serial_number}</Ident>,
              },
              { key: "part", header: "Built to", cell: (row) => <Ident>{row.part_number}</Ident> },
              { key: "samples", header: "Samples", align: "right", cell: (row) => row.sample_count },
              {
                key: "last",
                header: "Last tested",
                hideBelow: "sm",
                cell: (row) => (
                  <span className="text-ink-dim">{formatTimestamp(row.latest_recorded_at)}</span>
                ),
              },
            ]}
          />
        </div>

        {costRows.length > 0 && (
          <div>
            <p className="eyebrow mb-2">Cost exposure</p>
            <DataTable
              caption="Rollup delta between the baselines this change moves between"
              className="border-rule rounded-panel border"
              rows={costRows}
              rowKey={(row, index) => `${row.part_number}-${index}`}
              columns={[
                { key: "part", header: "Part", cell: (row) => <Ident className="font-semibold">{row.part_number}</Ident> },
                { key: "before", header: "Before", align: "right", cell: (row) => formatMoney(row.before) },
                { key: "after", header: "After", align: "right", cell: (row) => formatMoney(row.after) },
                {
                  key: "delta",
                  header: "Delta",
                  align: "right",
                  cell: (row) => (
                    <span
                      className={cn(
                        "font-semibold",
                        (row.delta ?? 0) > 0 ? "text-breach" : "text-verified",
                      )}
                    >
                      {(row.delta ?? 0) > 0 ? "+" : ""}
                      {formatMoney(row.delta)}
                    </span>
                  ),
                },
              ]}
            />
          </div>
        )}

        {findings.gaps.length > 0 && (
          <div className="bg-warm-wash rounded-panel p-3">
            <p className="eyebrow mb-1.5">Gaps in the assessment</p>
            <ul className="text-ink-dim space-y-1 text-[11px] leading-4">
              {findings.gaps.map((gap) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}

function ImpactList({
  title,
  items,
  empty,
}: {
  title: string;
  items: Array<{ key: string; primary: React.ReactNode; secondary?: string }>;
  empty: string;
}) {
  return (
    <div>
      <p className="eyebrow mb-2">
        {title} <span className="text-ink-faint">({items.length})</span>
      </p>
      {items.length === 0 ? (
        <p className="text-ink-faint text-[11px] leading-4">{empty}</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((item) => (
            <li key={item.key} className="min-w-0 text-xs">
              <span className="block truncate">{item.primary}</span>
              {item.secondary && (
                <span className="text-ink-faint block truncate text-[11px]">{item.secondary}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
