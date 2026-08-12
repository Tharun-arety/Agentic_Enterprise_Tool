"use client";

import * as React from "react";
import { ChevronRight } from "lucide-react";
import { Shell } from "@/components/Shell";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { DiffView } from "@/components/ui/record-view";
import { EmptyState, LoadingView } from "@/components/ui/states";
import { Ident, Verdict } from "@/components/ui/verdict";
import { formatDate, formatTime, formatTimestamp, humanise } from "@/lib/format";
import { Loaded, useResource } from "@/lib/use-resource";
import { cn } from "@/lib/utils";
import type { AuditEvent } from "@/lib/types";

const ACTORS = ["all", "human", "agent", "system"] as const;
type ActorFilter = (typeof ACTORS)[number];

/**
 * The audit trail.
 *
 * Grouped by day and shown as a timeline, because "what happened on the
 * eighth" is the question, not "give me row 412". Events that carry a before
 * and after open into a field-level diff — the unchanged columns are dropped,
 * since the whole point of opening an audit entry is to see what moved.
 */
export default function AuditPage() {
  const events = useResource<AuditEvent[]>("/api/audit");
  const [actor, setActor] = React.useState<ActorFilter>("all");

  return (
    <Shell
      eyebrow="Agents & control · accountability"
      title="Audit trail"
      summary="Append-only. Every mutation lands in the same transaction as the change it records, attributed to the person or agent that caused it."
      cells={
        events.data
          ? [
              { label: "Events", value: events.data.length },
              {
                label: "By agents",
                value: events.data.filter((event) => event.actor_type === "agent").length,
              },
            ]
          : []
      }
      onRefresh={events.reload}
      refreshing={events.refreshing}
    >
      <Loaded resource={events} loading={<LoadingView />}>
        {(rows) => {
          const filtered = actor === "all" ? rows : rows.filter((event) => event.actor_type === actor);
          const byDay = new Map<string, AuditEvent[]>();
          for (const event of filtered) {
            const day = event.occurred_at.slice(0, 10);
            const existing = byDay.get(day) ?? [];
            existing.push(event);
            byDay.set(day, existing);
          }

          return (
            <div className="space-y-4">
              <Panel className="flex flex-wrap items-center gap-2 p-3">
                <span className="eyebrow mr-1">Actor</span>
                {ACTORS.map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setActor(option)}
                    aria-pressed={actor === option}
                    className={cn(
                      "rounded-chip border px-2.5 py-1 text-[11px] font-semibold transition-colors",
                      actor === option
                        ? "border-cold bg-cold-wash text-cold"
                        : "border-rule text-ink-dim hover:bg-sunken",
                    )}
                  >
                    {humanise(option)}
                  </button>
                ))}
                <span className="text-ink-faint ml-auto text-[11px]">
                  {filtered.length} of {rows.length} events
                </span>
              </Panel>

              {filtered.length === 0 ? (
                <Panel>
                  <EmptyState
                    title={`No ${actor === "all" ? "" : actor} activity recorded`}
                    body="The trail records mutations as they happen; nothing matches this filter."
                  />
                </Panel>
              ) : (
                [...byDay.entries()].map(([day, dayEvents]) => (
                  <Panel key={day}>
                    <PanelHeader
                      eyebrow="Day"
                      title={formatDate(day)}
                      meta={`${dayEvents.length} events`}
                    />
                    <PanelBody className="p-0">
                      <ul>
                        {dayEvents.map((event) => (
                          <AuditRow key={event.id} event={event} />
                        ))}
                      </ul>
                    </PanelBody>
                  </Panel>
                ))
              )}
            </div>
          );
        }}
      </Loaded>
    </Shell>
  );
}

function AuditRow({ event }: { event: AuditEvent }) {
  const expandable = event.before !== null || event.after !== null;

  const summary = (
    <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-1">
      <span className="ident text-ink-faint w-11 shrink-0 text-[11px]">
        {formatTime(event.occurred_at)}
      </span>
      <Verdict
        label={humanise(event.actor_type)}
        tone={event.actor_type === "agent" ? "cold" : event.actor_type === "system" ? "neutral" : "verified"}
      />
      <span className="text-sm font-medium">{humanise(event.action)}</span>
      <Ident className="text-ink-dim text-[11px]">{event.entity_type}</Ident>
      <span className="text-ink-faint min-w-0 truncate text-[11px]">
        {event.actor_label ?? "—"}
      </span>
    </span>
  );

  if (!expandable) {
    return (
      <li className="border-rule flex items-baseline gap-2 border-b px-4 py-2.5 last:border-b-0">
        <span className="w-3.5 shrink-0" aria-hidden="true" />
        {summary}
      </li>
    );
  }

  return (
    <li className="border-rule border-b last:border-b-0">
      <details className="group">
        <summary className="hover:bg-sunken flex cursor-pointer list-none items-baseline gap-2 px-4 py-2.5 transition-colors">
          <ChevronRight
            className="text-ink-faint size-3.5 shrink-0 translate-y-0.5 transition-transform group-open:rotate-90"
            aria-hidden="true"
          />
          {summary}
        </summary>
        <div className="bg-sunken border-rule overflow-x-auto border-t px-4 py-3">
          {event.reason && (
            <p className="text-ink-dim mb-3 text-pretty text-[11px] leading-4">
              Reason: {event.reason}
            </p>
          )}
          <DiffView before={event.before} after={event.after} />
          <p className="text-ink-faint mt-3 text-[10px]">
            Recorded {formatTimestamp(event.occurred_at)}
            {event.correlation_id && ` · correlation ${event.correlation_id.slice(0, 8)}`}
          </p>
        </div>
      </details>
    </li>
  );
}
