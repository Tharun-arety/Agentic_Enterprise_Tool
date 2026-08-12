"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search } from "lucide-react";
import { Shell } from "@/components/Shell";
import { DataTable } from "@/components/ui/data-table";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { EmptyState, LoadingView, Skeleton } from "@/components/ui/states";
import { Ident, Verdict } from "@/components/ui/verdict";
import { formatNumber, formatTimestamp } from "@/lib/format";
import { Loaded, useResource } from "@/lib/use-resource";
import type { KnowledgeResponse } from "@/lib/types";

interface IngestionRow {
  id: string;
  filename: string;
  title: string;
  document_key: string;
  acl_labels: string[];
  version: number;
  status: string;
  error: string | null;
  uploaded_at: string;
}

/**
 * Controlled knowledge.
 *
 * The corpus is not hand-curated: released change orders and notices embed
 * themselves, so the searchable record grows out of the transactional data
 * rather than beside it. The search box is here so that claim can be checked
 * rather than asserted — search for a change and the change notice comes back.
 */
export default function KnowledgePage() {
  const ingestion = useResource<IngestionRow[]>("/api/knowledge/ingestion");
  const indexed = ingestion.data?.filter((row) => row.status === "indexed").length ?? 0;

  return (
    <Shell
      eyebrow="Knowledge · retrieval"
      title="What the agents can cite"
      summary="The indexed corpus and the semantic search over it. Released change notices embed themselves, so the record grows from the transactions."
      cells={
        ingestion.data
          ? [
              { label: "Documents", value: ingestion.data.length },
              { label: "Indexed", value: indexed },
            ]
          : []
      }
      onRefresh={ingestion.reload}
      refreshing={ingestion.refreshing}
    >
      <div className="space-y-4">
        <React.Suspense fallback={<LoadingView />}>
          <SearchPanel />
        </React.Suspense>

        <Panel>
          <PanelHeader eyebrow="Corpus" title="Ingestion and access labels" />
          <Loaded resource={ingestion}>
            {(rows) => (
              <DataTable
                caption="Documents ingested into the retrieval index"
                rows={rows}
                rowKey={(row) => row.id}
                emptyTitle="Nothing indexed yet"
                emptyBody="Release a change order, or upload a controlled document, to populate the index."
                columns={[
                  {
                    key: "title",
                    header: "Document",
                    cell: (row) => (
                      <span className="block">
                        <span className="font-medium">{row.title}</span>
                        <Ident className="text-ink-faint block text-[11px]">{row.filename}</Ident>
                      </span>
                    ),
                  },
                  { key: "key", header: "Key", hideBelow: "lg", cell: (row) => <Ident className="text-ink-dim">{row.document_key}</Ident> },
                  { key: "version", header: "Version", align: "right", hideBelow: "sm", cell: (row) => <span className="ident">v{row.version}</span> },
                  {
                    key: "acl",
                    header: "Access",
                    hideBelow: "md",
                    cell: (row) => (
                      <span className="flex flex-wrap gap-1">
                        {row.acl_labels.map((label) => (
                          <span key={label} className="bg-sunken text-ink-dim rounded-chip px-1.5 py-0.5 text-[10px]">
                            {label}
                          </span>
                        ))}
                      </span>
                    ),
                  },
                  {
                    key: "uploaded",
                    header: "Ingested",
                    hideBelow: "lg",
                    cell: (row) => <span className="ident text-ink-dim">{formatTimestamp(row.uploaded_at)}</span>,
                  },
                  {
                    key: "status",
                    header: "Status",
                    cell: (row) => (
                      <span className="block">
                        <Verdict status={row.status} />
                        {row.error && <span className="text-breach mt-1 block text-[10px]">{row.error}</span>}
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

const DEFAULT_QUERY = "magnet array temperature margin";

/**
 * The query lives in the URL, which does two things: a search result becomes a
 * link you can paste into a change request, and the fetch is driven by the
 * same resource hook as every other read rather than by hand-rolled state.
 */
function SearchPanel() {
  const router = useRouter();
  const params = useSearchParams();
  const query = params.get("q") ?? DEFAULT_QUERY;
  const [draft, setDraft] = React.useState(query);

  const results = useResource<KnowledgeResponse>(
    `/api/knowledge?q=${encodeURIComponent(query)}&limit=5`,
  );

  return (
    <Panel>
      <PanelHeader
        eyebrow="Semantic search"
        title="Ask the corpus"
        meta={
          results.data
            ? results.data.semantic
              ? `${results.data.provider} embeddings`
              : "deterministic fallback"
            : undefined
        }
      />
      <PanelBody className="space-y-4">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const next = draft.trim();
            if (next) router.replace(`/knowledge?q=${encodeURIComponent(next)}`, { scroll: false });
          }}
        >
          <label htmlFor="knowledge-query" className="sr-only">
            Search the engineering corpus
          </label>
          <div className="border-rule rounded-panel focus-within:border-cold flex items-center gap-2 border px-3 py-2 transition-colors">
            <Search className="text-ink-faint size-3.5 shrink-0" aria-hidden="true" />
            <input
              id="knowledge-query"
              name="q"
              type="search"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              autoComplete="off"
              spellCheck={false}
              placeholder="Why did the regenerator matrix change…"
              className="min-w-0 flex-1 bg-transparent text-xs outline-none"
            />
            <button
              type="submit"
              className="bg-cold text-cold-ink rounded-chip shrink-0 px-2.5 py-1 text-[11px] font-semibold"
            >
              Search
            </button>
          </div>
        </form>

        <div aria-live="polite">
          <Loaded resource={results} loading={<Skeleton className="h-32" />}>
            {(data) =>
              data.hits.length === 0 ? (
                <EmptyState
                  title="Nothing matched"
                  body="Try a phrase from a change notice, a failure report or a specification."
                />
              ) : (
                <ul className="space-y-2">
                  {data.hits.map((hit, index) => (
                    <li key={`${hit.source_ref}-${index}`} className="border-rule rounded-panel border p-3">
                      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                        <Verdict status={hit.document_type} tone="cold" />
                        {hit.source_ref && (
                          <Ident className="text-[11px] font-semibold">{hit.source_ref}</Ident>
                        )}
                        {hit.related_part_number && (
                          <Ident className="text-ink-faint text-[11px]">{hit.related_part_number}</Ident>
                        )}
                        <span className="text-ink-faint ident ml-auto text-[11px]">
                          {hit.similarity === null
                            ? "keyword match"
                            : `${formatNumber(hit.similarity * 100, 1)}% similar`}
                        </span>
                      </div>
                      <p className="text-ink-dim mt-2 text-pretty text-xs leading-5">{hit.text_content}</p>
                    </li>
                  ))}
                </ul>
              )
            }
          </Loaded>
        </div>
      </PanelBody>
    </Panel>
  );
}
