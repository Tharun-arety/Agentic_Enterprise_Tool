"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Shell } from "@/components/Shell";
import { useAuth } from "@/components/AuthProvider";
import { DataTable } from "@/components/ui/data-table";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { RecordView } from "@/components/ui/record-view";
import { EmptyState, LoadingView } from "@/components/ui/states";
import { Ident, Verdict } from "@/components/ui/verdict";
import { formatTimestamp, humanise } from "@/lib/format";
import { Loaded, useResource } from "@/lib/use-resource";
import { cn } from "@/lib/utils";
import type { Proposal, ProposedChange } from "@/lib/types";

const FILTERS = ["pending", "approved", "rejected", "applied"] as const;
type Filter = (typeof FILTERS)[number];

/**
 * The approval inbox.
 *
 * This is the screen the whole "operated by agents" claim rests on. An agent
 * tool that would change a record never applies it; it files the change here
 * with a dry-run preview, and a person holding the named role decides. So the
 * preview is rendered properly rather than dumped, and neither decision is a
 * single unguarded click — approving applies a real mutation, and rejecting
 * has to say why.
 */
export default function ApprovalInboxPage() {
  return (
    <React.Suspense fallback={<LoadingView />}>
      <ApprovalInbox />
    </React.Suspense>
  );
}

function ApprovalInbox() {
  const router = useRouter();
  const params = useSearchParams();
  const filter = (FILTERS as readonly string[]).includes(params.get("status") ?? "")
    ? (params.get("status") as Filter)
    : "pending";

  const proposals = useResource<Proposal[]>(`/api/proposals?status=${filter}`);

  return (
    <Shell
      eyebrow="Agents & control · write spine"
      title="Approval inbox"
      summary="Every change an agent proposes waits here with its dry-run preview until a person holding the required role decides."
      cells={proposals.data ? [{ label: humanise(filter), value: proposals.data.length }] : []}
      onRefresh={proposals.reload}
      refreshing={proposals.refreshing}
    >
      <div className="space-y-4">
        <Panel className="flex flex-wrap items-center gap-2 p-3">
          <span className="eyebrow mr-1">Show</span>
          {FILTERS.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => router.replace(`/approval-inbox?status=${option}`, { scroll: false })}
              aria-pressed={filter === option}
              className={cn(
                "rounded-chip border px-2.5 py-1 text-[11px] font-semibold transition-colors",
                filter === option
                  ? "border-cold bg-cold-wash text-cold"
                  : "border-rule text-ink-dim hover:bg-sunken",
              )}
            >
              {humanise(option)}
            </button>
          ))}
        </Panel>

        <Loaded resource={proposals}>
          {(rows) =>
            rows.length === 0 ? (
              <Panel>
                <EmptyState
                  title={
                    filter === "pending"
                      ? "Nothing is waiting for a decision"
                      : `No ${filter} proposals`
                  }
                  body={
                    filter === "pending"
                      ? "Ask the agent to change something — raise a change request, book a rig, disposition a finding — and the proposal will appear here instead of being applied."
                      : "Decisions made on agent proposals are kept permanently; none carries this outcome yet."
                  }
                />
              </Panel>
            ) : (
              <div className="space-y-4">
                {rows.map((proposal) => (
                  <ProposalCard key={proposal.id} proposal={proposal} onDecided={proposals.reload} />
                ))}
              </div>
            )
          }
        </Loaded>
      </div>
    </Shell>
  );
}

/**
 * The diff a reviewer is being asked to authorise.
 *
 * `changes` is a declared schema, not an open payload, so it gets a real table
 * with named columns rather than the generic renderer — the reviewer should be
 * able to read down the "field" column and compare before against after.
 */
function ChangeTable({ changes }: { changes: ProposedChange[] }) {
  if (changes.length === 0) {
    return (
      <p className="text-ink-faint text-[11px]">
        This tool reported no field-level differences.
      </p>
    );
  }

  return (
    <DataTable
      caption="Field-level changes this proposal would make"
      className="border-rule rounded-panel border"
      rows={changes}
      rowKey={(row, index) => `${row.target}-${row.field ?? index}`}
      columns={[
        {
          key: "kind",
          header: "Change",
          cell: (row) => (
            <Verdict
              status={row.kind}
              tone={row.kind === "add" ? "verified" : row.kind === "remove" ? "breach" : "cold"}
            />
          ),
        },
        { key: "target", header: "Target", cell: (row) => <Ident>{row.target}</Ident> },
        {
          key: "field",
          header: "Field",
          cell: (row) => (row.field ? humanise(row.field) : <span className="text-ink-faint">—</span>),
        },
        {
          key: "before",
          header: "From",
          cell: (row) =>
            row.before === null || row.before === undefined ? (
              <span className="text-ink-faint">—</span>
            ) : (
              <span className="text-ink-faint line-through">{String(row.before)}</span>
            ),
        },
        {
          key: "after",
          header: "To",
          cell: (row) =>
            row.after === null || row.after === undefined ? (
              <span className="text-ink-faint">—</span>
            ) : (
              <span className="text-verified">{String(row.after)}</span>
            ),
        },
      ]}
    />
  );
}

function ProposalCard({
  proposal,
  onDecided,
}: {
  proposal: Proposal;
  onDecided: () => void;
}) {
  const { request, user } = useAuth();
  const [note, setNote] = React.useState("");
  const [busy, setBusy] = React.useState<"approve" | "reject" | null>(null);
  const [error, setError] = React.useState("");

  const pending = proposal.status === "pending";
  const permitted = user?.roles.includes(proposal.required_role) || user?.roles.includes("admin");

  const decide = async (decision: "approve" | "reject") => {
    setBusy(decision);
    setError("");
    try {
      await request(`/api/proposals/${proposal.id}/${decision}`, {
        method: "POST",
        body: JSON.stringify({ note: note.trim() || null }),
      });
      onDecided();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Panel>
      <PanelHeader
        eyebrow={`${proposal.proposed_by_agent} · ${formatTimestamp(proposal.created_at)}`}
        title={proposal.summary}
        action={
          <span className="flex shrink-0 items-center gap-1.5">
            <Verdict label={humanise(proposal.required_role)} tone="cold" />
            <Verdict status={proposal.status} />
          </span>
        }
      />

      <PanelBody className="space-y-5">
        <div>
          <p className="eyebrow mb-2">
            What would change · {proposal.preview.entity_type}
            {proposal.preview.entity_ref ? ` ${proposal.preview.entity_ref}` : ""}
          </p>
          <ChangeTable changes={proposal.preview.changes} />
          {proposal.preview.warnings.length > 0 && (
            <ul className="bg-warm-wash rounded-panel mt-2 space-y-1 p-3 text-[11px] leading-4">
              {proposal.preview.warnings.map((warning) => (
                <li key={warning} className="text-warm">
                  {warning}
                </li>
              ))}
            </ul>
          )}
        </div>

        <details className="group">
          <summary className="text-ink-dim hover:text-ink cursor-pointer list-none text-[11px] font-semibold transition-colors">
            <span className="group-open:hidden">Show the call that produced this ▸</span>
            <span className="hidden group-open:inline">Hide the call ▾</span>
          </summary>
          <div className="border-rule mt-2 border-t pt-3">
            <Ident className="text-cold mb-2 block text-xs font-semibold">
              {proposal.tool_name}
            </Ident>
            <RecordView value={proposal.arguments} />
          </div>
        </details>

        {proposal.result && (
          <div className="border-rule border-t pt-4">
            <p className="eyebrow mb-2">Result after applying</p>
            <RecordView value={proposal.result} />
          </div>
        )}

        {!pending && (
          <div className="border-rule border-t pt-4 text-xs">
            <p className="text-ink-dim">
              {humanise(proposal.status)} {proposal.reviewed_at && `on ${formatTimestamp(proposal.reviewed_at)}`}
              {proposal.applied_at && ` · applied ${formatTimestamp(proposal.applied_at)}`}
            </p>
            {proposal.review_note && (
              <p className="text-ink-dim mt-1 text-pretty leading-5">“{proposal.review_note}”</p>
            )}
          </div>
        )}

        {pending && (
          <div className="border-rule border-t pt-4">
            {!permitted ? (
              <p className="text-warm text-xs">
                This decision belongs to the {humanise(proposal.required_role)} role. Sign in as
                someone holding it to approve or reject.
              </p>
            ) : (
              <>
                <label htmlFor={`note-${proposal.id}`} className="eyebrow mb-1.5 block">
                  Decision note — required to reject
                </label>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    id={`note-${proposal.id}`}
                    name="note"
                    type="text"
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    autoComplete="off"
                    placeholder="Why this is right, or why it is not…"
                    className="border-rule rounded-chip focus:border-cold min-w-0 flex-1 border bg-transparent px-2.5 py-1.5 text-xs outline-none transition-colors"
                  />
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void decide("approve")}
                    className="bg-cold text-cold-ink rounded-chip shrink-0 px-3 py-1.5 text-xs font-semibold transition-opacity disabled:opacity-50"
                  >
                    {busy === "approve" ? "Applying…" : "Approve & Apply"}
                  </button>
                  <button
                    type="button"
                    disabled={busy !== null || note.trim().length === 0}
                    onClick={() => void decide("reject")}
                    title={note.trim() ? undefined : "A rejection has to say why"}
                    className="border-breach text-breach rounded-chip hover:bg-breach-wash shrink-0 border px-3 py-1.5 text-xs font-semibold transition-colors disabled:opacity-40"
                  >
                    {busy === "reject" ? "Rejecting…" : "Reject"}
                  </button>
                </div>
                <p className="text-ink-faint mt-2 text-[11px]">
                  Approving runs the tool for real, inside one transaction, with your name on it.
                </p>
              </>
            )}
            <div aria-live="polite">
              {error && <p className="text-breach mt-2 text-[11px]">{error}</p>}
            </div>
          </div>
        )}
      </PanelBody>
    </Panel>
  );
}
