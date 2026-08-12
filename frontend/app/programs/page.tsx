"use client";

import * as React from "react";
import { Shell } from "@/components/Shell";
import { DataTable } from "@/components/ui/data-table";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/states";
import { Ident, Verdict } from "@/components/ui/verdict";
import { formatDate, formatMoney, humanise } from "@/lib/format";
import { toneFor } from "@/lib/status";
import { Loaded, useResource } from "@/lib/use-resource";
import { cn } from "@/lib/utils";
import type { Deliverable, TrlGate } from "@/lib/types";

interface Programme {
  code: string;
  name: string;
  status: string;
  work_package_count: number;
  partners: Array<{ name: string; role: string }>;
  milestones: Array<{ name: string; due_date: string; status: string }>;
}

interface WorkPackage {
  code: string;
  title: string;
  programme: string;
  programme_code: string;
  budget: number;
  trl_target: number;
}

/**
 * Programmes.
 *
 * Readiness is a ladder, not a status field, so it is drawn as one. A funded
 * programme reports against numbered TRL gates and a reviewer needs to see
 * which rungs are cleared, which is under review and how far the target still
 * is — three facts a chip saying "in_review" cannot carry.
 */
export default function ProgrammesPage() {
  const programmes = useResource<Programme[]>("/api/programs");
  const packages = useResource<WorkPackage[]>("/api/programs/work-packages");
  const gates = useResource<TrlGate[]>("/api/programs/trl");
  const deliverables = useResource<Deliverable[]>("/api/programs/deliverables");

  return (
    <Shell
      eyebrow="Programmes · funded work"
      title="Readiness and delivery"
      summary="Work packages, technology readiness gates and consortium deliverables across the funded programmes."
      cells={
        programmes.data
          ? [
              { label: "Programmes", value: programmes.data.length },
              { label: "Work packages", value: packages.data?.length ?? "—" },
              { label: "Gates recorded", value: gates.data?.length ?? "—" },
            ]
          : []
      }
      onRefresh={() => {
        programmes.reload();
        packages.reload();
        gates.reload();
        deliverables.reload();
      }}
      refreshing={programmes.refreshing || gates.refreshing}
    >
      <div className="space-y-4">
        <Loaded resource={gates}>
          {(rows) =>
            rows.length === 0 ? (
              <Panel>
                <EmptyState
                  title="No readiness gates recorded"
                  body="A work package reports against numbered TRL gates; none has been assessed."
                />
              </Panel>
            ) : (
              <GateLadders gates={rows} />
            )
          }
        </Loaded>

        <Panel>
          <PanelHeader eyebrow="Work packages" title="Scope and budget" />
          <Loaded resource={packages}>
            {(rows) => (
              <DataTable
                caption="Work packages with their budget and readiness target"
                rows={rows}
                rowKey={(row) => `${row.programme_code}-${row.code}`}
                emptyTitle="No work packages"
                columns={[
                  { key: "code", header: "Package", cell: (row) => <Ident className="font-semibold">{row.code}</Ident> },
                  { key: "title", header: "Title", cell: (row) => row.title },
                  { key: "prog", header: "Programme", hideBelow: "md", cell: (row) => <span className="text-ink-dim">{row.programme}</span> },
                  { key: "trl", header: "TRL target", align: "right", hideBelow: "sm", cell: (row) => <span className="ident">{row.trl_target}</span> },
                  { key: "budget", header: "Budget", align: "right", cell: (row) => formatMoney(row.budget, "EUR", 0) },
                ]}
              />
            )}
          </Loaded>
        </Panel>

        <Panel>
          <PanelHeader eyebrow="Deliverables" title="What is owed, and when" />
          <Loaded resource={deliverables}>
            {(rows) => (
              <DataTable
                caption="Consortium deliverables and their due dates"
                rows={rows}
                rowKey={(row) => row.code}
                emptyTitle="No deliverables"
                emptyBody="Deliverables are owed per work package; none has been scheduled."
                columns={[
                  { key: "code", header: "Ref", cell: (row) => <Ident className="text-cold font-semibold">{row.code}</Ident> },
                  { key: "title", header: "Deliverable", cell: (row) => row.title },
                  { key: "wp", header: "Package", hideBelow: "sm", cell: (row) => <Ident>{row.work_package}</Ident> },
                  { key: "due", header: "Due", cell: (row) => <span className="ident">{formatDate(row.due_date)}</span> },
                  { key: "status", header: "Status", cell: (row) => <Verdict status={humanise(row.status)} /> },
                ]}
              />
            )}
          </Loaded>
        </Panel>

        <Loaded resource={programmes} loading={null}>
          {(rows) => (
            <div className="grid gap-4 lg:grid-cols-2">
              {rows.map((programme) => (
                <Panel key={programme.code}>
                  <PanelHeader
                    eyebrow={programme.code}
                    title={programme.name}
                    action={<Verdict status={programme.status} />}
                  />
                  <PanelBody className="space-y-4">
                    <div>
                      <p className="eyebrow mb-2">Consortium</p>
                      {programme.partners.length === 0 ? (
                        <p className="text-ink-faint text-[11px]">No partners recorded.</p>
                      ) : (
                        <ul className="space-y-1">
                          {programme.partners.map((partner) => (
                            <li key={partner.name} className="text-xs">
                              <span className="font-medium">{partner.name}</span>
                              <span className="text-ink-faint"> — {partner.role}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <div>
                      <p className="eyebrow mb-2">Milestones</p>
                      {programme.milestones.length === 0 ? (
                        <p className="text-ink-faint text-[11px]">No milestones scheduled.</p>
                      ) : (
                        <ul className="space-y-1.5">
                          {programme.milestones.map((milestone) => (
                            <li key={milestone.name} className="flex items-baseline gap-2 text-xs">
                              <span className="ident text-ink-faint shrink-0 text-[11px]">
                                {formatDate(milestone.due_date)}
                              </span>
                              <span className="min-w-0 flex-1 truncate">{milestone.name}</span>
                              <Verdict status={humanise(milestone.status)} />
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </PanelBody>
                </Panel>
              ))}
            </div>
          )}
        </Loaded>
      </div>
    </Shell>
  );
}

function GateLadders({ gates }: { gates: TrlGate[] }) {
  const byPackage = new Map<string, TrlGate[]>();
  for (const gate of gates) {
    const existing = byPackage.get(gate.work_package) ?? [];
    existing.push(gate);
    byPackage.set(gate.work_package, existing);
  }

  return (
    <Panel>
      <PanelHeader eyebrow="Technology readiness" title="Gates cleared and gates open" />
      <PanelBody className="space-y-6">
        {[...byPackage.entries()].map(([workPackage, packageGates]) => (
          <GateLadder key={workPackage} workPackage={workPackage} gates={packageGates} />
        ))}
      </PanelBody>
    </Panel>
  );
}

/** TRL runs 1 to 9. Rungs below the lowest recorded gate are inferred cleared. */
const RUNGS = [1, 2, 3, 4, 5, 6, 7, 8, 9] as const;

function GateLadder({ workPackage, gates }: { workPackage: string; gates: TrlGate[] }) {
  const byLevel = new Map(gates.map((gate) => [gate.trl, gate]));
  const target = gates[0]?.trl_target ?? 9;
  const approved = gates.filter((gate) => toneFor(gate.status) === "verified");
  // Zero is not a readiness level. A package with nothing signed off has not
  // cleared a gate, and saying "TRL 0" invents a rung that does not exist.
  const cleared = approved.length > 0 ? Math.max(...approved.map((gate) => gate.trl)) : null;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-semibold">{workPackage}</p>
        <p className="text-ink-faint text-[11px]">
          {cleared === null ? (
            <span className="text-warm font-semibold">No gate cleared</span>
          ) : (
            <>
              <span className="text-verified font-semibold">TRL {cleared}</span> cleared
            </>
          )}{" "}
          · target <span className="text-cold font-semibold">TRL {target}</span>
        </p>
      </div>

      <ol className="flex gap-1">
        {RUNGS.map((rung) => {
          const gate = byLevel.get(rung);
          const tone = gate ? toneFor(gate.status) : "neutral";
          return (
            <li key={rung} className="min-w-0 flex-1">
              <div
                title={gate ? `TRL ${rung}: ${humanise(gate.status)}` : `TRL ${rung}`}
                className={cn(
                  "h-1.5 rounded-full",
                  tone === "verified" && "bg-verified",
                  tone === "warm" && "bg-warm",
                  tone === "breach" && "bg-breach",
                  tone === "cold" && "bg-cold",
                  tone === "neutral" &&
                    (rung <= (cleared ?? 0)
                      ? "bg-verified"
                      : rung <= target
                        ? "bg-sunken"
                        : "bg-transparent"),
                )}
              />
              <span
                className={cn(
                  "ident mt-1 block text-center text-[10px]",
                  rung === target ? "text-cold font-semibold" : "text-ink-faint",
                )}
              >
                {rung}
              </span>
            </li>
          );
        })}
      </ol>

      <ul className="mt-2 space-y-1">
        {gates.map((gate) => (
          <li key={gate.id} className="flex items-baseline gap-2 text-[11px] leading-4">
            <Ident className="shrink-0 font-semibold">TRL&nbsp;{gate.trl}</Ident>
            <Verdict status={humanise(gate.status)} />
            <span className="text-ink-dim min-w-0 flex-1">{gate.evidence ?? "No evidence recorded."}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
