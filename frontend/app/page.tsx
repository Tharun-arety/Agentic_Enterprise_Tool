"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Shell } from "@/components/Shell";
import { Panel, PanelBody, PanelHeader, Reading } from "@/components/ui/panel";
import { Ident, Verdict } from "@/components/ui/verdict";
import { formatTime } from "@/lib/format";
import { TONE_TEXT } from "@/lib/status";
import { Loaded, useResource } from "@/lib/use-resource";
import type { ShowcaseResponse } from "@/lib/types";

/**
 * The overview states the thesis, so it is built around the thesis.
 *
 * Everything this suite does hangs off one claim: a supplier receipt at one
 * end and a searchable change notice at the other, with no gap in between that
 * a person has to bridge from memory. Eight equal cards in a grid say nothing
 * about that. A single unbroken chain does, which is why this column does not
 * split into two at any width — breaking the thread would break the argument.
 */
export default function OverviewPage() {
  const showcase = useResource<ShowcaseResponse>("/api/showcase");

  return (
    <Shell
      eyebrow="Engineering operations"
      title={showcase.data?.product ?? "ECLIPSE 1 kW retail chiller"}
      summary="Configuration, change, quality and supply evidence for one magnetocaloric product line."
      cells={
        showcase.data
          ? [
              { label: "Product", value: <Ident>{showcase.data.product_number}</Ident> },
              { label: "Records", value: "Synthetic" },
              { label: "Read at", value: formatTime(showcase.data.generated_at) },
            ]
          : []
      }
      onRefresh={showcase.reload}
      refreshing={showcase.refreshing}
    >
      <Loaded resource={showcase}>
        {(data) => (
          <div className="mx-auto max-w-4xl space-y-4">
            <CountsStrip counts={data.counts} />
            <EvidenceChain steps={data.workflow} />
            <ApprovalNote pending={data.counts.pending_proposals} />
          </div>
        )}
      </Loaded>
    </Shell>
  );
}

function CountsStrip({ counts }: { counts: ShowcaseResponse["counts"] }) {
  const readings: Array<{ label: string; value: number; tone?: string }> = [
    { label: "Controlled parts", value: counts.controlled_parts },
    { label: "Units built", value: counts.built_units },
    { label: "Test samples", value: counts.test_samples },
    {
      label: "Failed samples",
      value: counts.failed_samples,
      tone: counts.failed_samples > 0 ? TONE_TEXT.breach : undefined,
    },
    {
      label: "Open NCRs",
      value: counts.open_ncrs,
      tone: counts.open_ncrs > 0 ? TONE_TEXT.warm : undefined,
    },
    {
      label: "Stock at risk",
      value: counts.low_stock_items,
      tone: counts.low_stock_items > 0 ? TONE_TEXT.warm : undefined,
    },
  ];

  return (
    <Panel>
      <div className="grid grid-cols-2 divide-x divide-y divide-[var(--rule)] sm:grid-cols-3 sm:divide-y-0 lg:grid-cols-6">
        {readings.map((reading) => (
          <div key={reading.label} className="p-4">
            <Reading label={reading.label} value={reading.value} tone={reading.tone} />
          </div>
        ))}
      </div>
    </Panel>
  );
}

function EvidenceChain({ steps }: { steps: ShowcaseResponse["workflow"] }) {
  return (
    <Panel>
      <PanelHeader
        eyebrow="Traceability"
        title="Receipt to searchable change notice"
        meta={`${steps.length} links`}
      />
      <PanelBody>
        <p className="text-ink-dim mb-5 max-w-2xl text-pretty text-xs leading-5">
          Each link is a record the services actually wrote, not a fixture. The
          numbering is the order the evidence was created in, and every link
          opens the screen that holds it.
        </p>

        <ol className="relative">
          {steps.map((step, index) => (
            <li key={`${step.domain}-${step.reference}`} className="relative pb-1 pl-11 last:pb-0">
              {index < steps.length - 1 && (
                <span
                  className="bg-rule absolute bottom-0 left-[15px] top-9 w-px"
                  aria-hidden="true"
                />
              )}
              <span
                className="border-rule bg-panel ident text-ink-dim absolute left-0 top-1.5 grid size-8 place-items-center rounded-full border text-[11px] font-semibold"
                aria-hidden="true"
              >
                {index + 1}
              </span>

              <Link
                href={step.href}
                className="group hover:bg-sunken rounded-panel -mx-2 flex items-start gap-3 px-2 py-2 transition-colors"
              >
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="eyebrow">{step.domain}</span>
                    <Verdict status={step.status} />
                  </span>
                  <span className="mt-1 block text-sm font-semibold">{step.title}</span>
                  <span className="text-ink-dim mt-0.5 block text-pretty text-xs leading-5">
                    <Ident className="text-cold font-semibold">{step.reference}</Ident>
                    {" · "}
                    {step.detail}
                  </span>
                </span>
                <ArrowRight
                  className="text-ink-faint group-hover:text-cold mt-1.5 size-4 shrink-0 transition-colors"
                  aria-hidden="true"
                />
              </Link>
            </li>
          ))}
        </ol>
      </PanelBody>
    </Panel>
  );
}

function ApprovalNote({ pending }: { pending: number }) {
  return (
    <Panel className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">Agents propose; people dispose</p>
        <p className="text-ink-dim mt-0.5 text-pretty text-xs leading-5">
          {pending === 0
            ? "No agent action is waiting for review. Tools that would change a record file a proposal instead of applying it."
            : `${pending} agent ${pending === 1 ? "action is" : "actions are"} waiting for a named reviewer. No agent tool applies a change directly.`}
        </p>
      </div>
      <Link
        href="/approval-inbox"
        className="border-rule rounded-chip hover:bg-sunken shrink-0 border px-3 py-1.5 text-xs font-semibold transition-colors"
      >
        Open Approval Inbox
      </Link>
    </Panel>
  );
}
