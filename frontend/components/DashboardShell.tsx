"use client";

import * as React from "react";
import { AlertTriangle, CircleCheck, CircleSlash } from "lucide-react";

import { AgentChatSidebar } from "@/components/AgentChatSidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { BOMViewer } from "@/components/BOMViewer";
import { QMSMetricsChart } from "@/components/QMSMetricsChart";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type {
  BomResponse,
  HealthResponse,
  KnowledgeResponse,
  QmsResponse,
} from "@/lib/types";

const PRODUCT_LINES = [
  {
    name: "POLARIS",
    capacity: "100 W",
    note: "Early commercial magnetic cooler",
    state: "Fielded",
  },
  {
    name: "ECLIPSE",
    capacity: "1 kW",
    note: "Flagship retail chiller — rotational NdFeB, work recovery",
    state: "Active",
  },
  {
    name: "STELLAR",
    capacity: "125 kW+",
    note: "Industrial scale, superconducting magnets",
    state: "Development",
  },
];

export function DashboardShell({
  initialBom,
  initialQms,
  knowledge,
  health,
}: {
  initialBom: BomResponse | null;
  initialQms: QmsResponse | null;
  knowledge: KnowledgeResponse | null;
  health: HealthResponse | null;
}) {
  // Seeded from the server render, then replaced live by whatever the agent's
  // tools return during a conversation.
  const [bom, setBom] = React.useState(initialBom);
  const [qms, setQms] = React.useState(initialQms);

  const backendDown = health === null;

  return (
    // Fixed side columns would squeeze the main content to nothing on a narrow
    // laptop, so the nav collapses to an icon rail and the chat narrows before
    // the dashboard gives up any width.
    <div className="grid h-dvh grid-cols-[3.5rem_minmax(0,1fr)_15rem] overflow-hidden lg:grid-cols-[3.5rem_minmax(0,1fr)_19rem] xl:grid-cols-[13rem_minmax(0,1fr)_22rem]">
      <AppSidebar />

      <main className="flex min-w-0 flex-col overflow-y-auto">
        <header className="border-border bg-surface/80 sticky top-0 z-10 flex flex-wrap items-center gap-3 border-b px-6 py-3 backdrop-blur">
          <div className="min-w-0">
            <h1 className="truncate text-base font-semibold tracking-tight">
              ECLIPSE 1kW — Engineering Overview
            </h1>
            <p className="text-muted-foreground truncate text-xs">
              Active Magnetic Regeneration · LaFeSi · water/alcohol &lt; 1 bar
            </p>
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            {backendDown ? (
              <Badge className="border-warning/40 text-warning bg-warning/10 gap-1">
                <CircleSlash className="size-3" /> Backend offline
              </Badge>
            ) : (
              <>
                <Badge className="border-accent/40 text-accent bg-accent/10 gap-1">
                  <CircleCheck className="size-3" /> API online
                </Badge>
                {!health.live_model && (
                  <Badge
                    className="border-warning/40 text-warning bg-warning/10 gap-1"
                    title="OPENAI_API_KEY is not set, so the agent answers from a stub client."
                  >
                    <AlertTriangle className="size-3" /> Stub model
                  </Badge>
                )}
                {!health.semantic_search && (
                  <Badge
                    className="border-warning/40 text-warning bg-warning/10 gap-1"
                    title="Embeddings are running on the deterministic fallback; knowledge ranking is not semantic."
                  >
                    <AlertTriangle className="size-3" /> Non-semantic search
                  </Badge>
                )}
              </>
            )}
          </div>
        </header>

        {backendDown && (
          <p className="border-warning/30 bg-warning/5 text-warning mx-6 mt-4 rounded-lg border px-3 py-2 text-xs">
            Could not reach the API. Start it with{" "}
            <code className="font-mono">
              uvicorn app.main:app --reload --port 8000
            </code>{" "}
            and make sure <code className="font-mono">DATABASE_URL</code> is set
            in <code className="font-mono">backend/.env</code>.
          </p>
        )}

        <div className="grid gap-4 p-6 xl:grid-cols-2">
          <Card className="xl:col-span-2">
            <CardHeader>
              <div>
                <CardTitle>QMS — Lab test metrics</CardTitle>
                <CardDescription>
                  Temperature span and pressure drop on independent axes; they
                  differ by ~2 orders of magnitude.
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <QMSMetricsChart qms={qms} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>PDM — Bill of materials</CardTitle>
                <CardDescription>
                  {bom
                    ? `Nested structure for ${bom.root_part_number}`
                    : "Nothing loaded"}
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <BOMViewer bom={bom} />
            </CardContent>
          </Card>

          <div className="flex flex-col gap-4">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Engineering knowledge</CardTitle>
                  <CardDescription>
                    {knowledge && !knowledge.semantic
                      ? "Fallback embeddings — ordering is not semantic"
                      : "Recent ECOs, test reports and spec excerpts"}
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {knowledge && knowledge.hits.length > 0 ? (
                  knowledge.hits.map((hit) => (
                    <div
                      key={hit.source_ref ?? hit.text_content.slice(0, 24)}
                      className="border-border border-b pb-3 last:border-0 last:pb-0"
                    >
                      <div className="mb-1 flex flex-wrap items-center gap-1.5">
                        <Badge className="bg-surface-muted text-muted-foreground">
                          {hit.document_type}
                        </Badge>
                        {hit.source_ref && (
                          <span className="font-mono text-[11px] font-semibold">
                            {hit.source_ref}
                          </span>
                        )}
                        {hit.related_part_number && (
                          <span className="text-muted-foreground font-mono text-[10px]">
                            {hit.related_part_number}
                          </span>
                        )}
                      </div>
                      <p className="text-muted-foreground line-clamp-3 text-xs leading-snug">
                        {hit.text_content}
                      </p>
                    </div>
                  ))
                ) : (
                  <p className="text-muted-foreground py-6 text-center text-xs">
                    No documents loaded.
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Product lines</CardTitle>
                  <CardDescription>Cooling capacity by platform</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="space-y-2">
                {PRODUCT_LINES.map((line) => (
                  <div
                    key={line.name}
                    className="bg-surface-muted flex items-start gap-3 rounded-lg p-2.5"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold">
                        {line.name}
                        <span className="text-muted-foreground ml-1.5 font-mono text-[11px] font-normal">
                          {line.capacity}
                        </span>
                      </p>
                      <p className="text-muted-foreground mt-0.5 text-[11px] leading-snug">
                        {line.note}
                      </p>
                    </div>
                    <Badge className="bg-surface text-muted-foreground shrink-0">
                      {line.state}
                    </Badge>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        </div>
      </main>

      <AgentChatSidebar onBom={setBom} onQms={setQms} />
    </div>
  );
}
