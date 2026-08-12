"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { BOMViewer } from "@/components/BOMViewer";
import { Shell } from "@/components/Shell";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState, LoadingView } from "@/components/ui/states";
import { Ident, Verdict } from "@/components/ui/verdict";
import { formatDate, formatNumber } from "@/lib/format";
import { Loaded, useResource } from "@/lib/use-resource";
import { cn } from "@/lib/utils";
import type { BomResponse, BomType, ComplianceRollup, ComplianceVerdict } from "@/lib/types";

const PRODUCT = "ECL-SYS-1000";

/**
 * Product data.
 *
 * The EBOM/MBOM choice lives in the URL rather than in component state: which
 * view of the structure you are looking at is the single most important fact
 * about a BOM screenshot, and a link that does not carry it is a link that
 * cannot be sent to a colleague.
 */
export default function ProductDataPage() {
  return (
    <React.Suspense fallback={<LoadingView />}>
      <ProductData />
    </React.Suspense>
  );
}

function ProductData() {
  const router = useRouter();
  const params = useSearchParams();
  const view: BomType = params.get("view") === "EBOM" ? "EBOM" : "MBOM";

  const bom = useResource<BomResponse>(
    `/api/parts/${PRODUCT}/bom?bom_type=${view}`,
  );
  const compliance = useResource<ComplianceRollup>(
    `/api/parts/${PRODUCT}/compliance?bom_type=${view}`,
  );

  const setView = (next: BomType) => {
    const search = new URLSearchParams(params.toString());
    search.set("view", next);
    router.replace(`/pdm?${search.toString()}`, { scroll: false });
  };

  return (
    <Shell
      eyebrow="Product data · DIN 199"
      title="ECLIPSE product structure"
      summary="The engineering bill and the manufacturing bill it derives into, resolved to the revisions in force on the query date."
      cells={
        bom.data
          ? [
              { label: "Product", value: <Ident>{bom.data.root_part_number}</Ident> },
              { label: "Revision", value: bom.data.root_revision },
              { label: "Effective", value: formatDate(bom.data.as_of) },
              { label: "Items", value: bom.data.total_nodes },
              { label: "Levels", value: bom.data.max_depth + 1 },
            ]
          : []
      }
      onRefresh={() => {
        bom.reload();
        compliance.reload();
      }}
      refreshing={bom.refreshing || compliance.refreshing}
    >
      <div className="space-y-4">
        <Panel>
          <PanelHeader
            eyebrow={view === "MBOM" ? "Manufacturing bill" : "Engineering bill"}
            title={
              view === "MBOM"
                ? "As it is built, in operation sequence"
                : "As it is designed, by function"
            }
            action={<ViewToggle view={view} onChange={setView} />}
          />
          <Loaded resource={bom}>{(data) => <BOMViewer bom={data} />}</Loaded>
        </Panel>

        <Loaded resource={compliance} loading={<LoadingView />}>
          {(data) => <CompliancePanel rollup={data} />}
        </Loaded>
      </div>
    </Shell>
  );
}

function ViewToggle({
  view,
  onChange,
}: {
  view: BomType;
  onChange: (next: BomType) => void;
}) {
  return (
    <div className="border-rule rounded-chip flex shrink-0 border p-0.5" role="group" aria-label="Bill of materials view">
      {(["EBOM", "MBOM"] as const).map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          aria-pressed={view === option}
          className={cn(
            "rounded-chip px-2.5 py-1 text-[11px] font-semibold transition-colors",
            view === option ? "bg-cold text-cold-ink" : "text-ink-dim hover:text-ink",
          )}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

const VERDICT_COPY: Record<ComplianceVerdict, string> = {
  proven: "Proven",
  violated: "Violated",
  unproven: "Cannot prove",
};

function CompliancePanel({ rollup }: { rollup: ComplianceRollup }) {
  const claims: Array<{ label: string; verdict: ComplianceVerdict }> = [
    { label: "PFAS-free", verdict: rollup.pfas_free },
    { label: "Heavy rare-earth free", verdict: rollup.heavy_rare_earth_free },
    { label: "RoHS / REACH", verdict: rollup.rohs_reach },
  ];

  return (
    <Panel>
      <PanelHeader
        eyebrow="Compliance rollup"
        title="Claims traced to components"
        meta={`${rollup.components_assessed} assessed`}
      />
      <PanelBody className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          {claims.map((claim) => (
            <div key={claim.label} className="border-rule rounded-panel border p-3">
              <p className="eyebrow">{claim.label}</p>
              <div className="mt-2">
                <Verdict
                  label={VERDICT_COPY[claim.verdict]}
                  tone={
                    claim.verdict === "proven"
                      ? "verified"
                      : claim.verdict === "violated"
                        ? "breach"
                        : "warm"
                  }
                />
              </div>
            </div>
          ))}
        </div>

        <p className="text-ink-dim text-pretty text-xs leading-5">
          A claim is only proven when every component in the structure declares
          it. One unassessed part makes the whole claim unprovable — which is
          the honest answer, and the one an auditor needs.
          {rollup.total_direct_gwp !== null && (
            <>
              {" "}
              Direct global warming potential across the structure totals{" "}
              <Ident className="text-ink font-semibold">
                {formatNumber(rollup.total_direct_gwp, 2)}&nbsp;kg&nbsp;CO₂e
              </Ident>
              .
            </>
          )}
        </p>

        {rollup.violations.length > 0 && (
          <div>
            <p className="eyebrow mb-2">Violations</p>
            <DataTable
              caption="Components that violate a declared claim"
              className="border-rule rounded-panel border"
              rows={rollup.violations}
              rowKey={(row, index) => `${row.part_number}-${row.attribute}-${index}`}
              columns={[
                { key: "part", header: "Part", cell: (row) => <Ident className="font-semibold">{row.part_number}</Ident> },
                { key: "desc", header: "Description", hideBelow: "md", cell: (row) => <span className="text-ink-dim line-clamp-1">{row.description}</span> },
                { key: "attr", header: "Attribute", cell: (row) => row.attribute },
                { key: "value", header: "Declared", cell: (row) => <Verdict status={row.value} /> },
              ]}
            />
          </div>
        )}

        <div>
          <p className="eyebrow mb-2">Undeclared components</p>
          {rollup.gaps.length === 0 ? (
            <EmptyState
              title="Every component is declared"
              body="No part in this structure is missing a compliance declaration."
            />
          ) : (
            <DataTable
              caption="Components with no compliance declaration"
              className="border-rule rounded-panel border"
              rows={rollup.gaps}
              rowKey={(row, index) => `${row.part_number}-${row.attribute}-${index}`}
              columns={[
                { key: "part", header: "Part", cell: (row) => <Ident className="font-semibold">{row.part_number}</Ident> },
                { key: "desc", header: "Description", hideBelow: "md", cell: (row) => <span className="text-ink-dim line-clamp-1">{row.description}</span> },
                { key: "attr", header: "Attribute", cell: (row) => row.attribute },
                { key: "value", header: "Declared", cell: (row) => <Verdict status={row.value} /> },
              ]}
            />
          )}
        </div>
      </PanelBody>
    </Panel>
  );
}
