"use client";

import * as React from "react";
import { ChevronDown, ChevronRight, Package } from "lucide-react";

import { MaterialBadge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { BomNode, BomResponse } from "@/lib/types";

/**
 * Renders a bill of materials as a tree.
 *
 * The recursion is the component itself: `BomRow` renders one node and maps its
 * children back through `BomRow`. Depth is whatever the data says it is — the
 * component never assumes three levels.
 */

function BomRow({ node }: { node: BomNode }) {
  const hasChildren = node.children.length > 0;
  // Assemblies open by default so the LaFeSi and Neodymium parts are visible on
  // first paint rather than hidden behind a disclosure.
  const [open, setOpen] = React.useState(true);

  return (
    <li className="relative">
      <div className="group flex items-start gap-2 py-1.5">
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-label={`${open ? "Collapse" : "Expand"} ${node.part_number}`}
            className="text-muted-foreground hover:text-foreground mt-0.5 shrink-0 rounded p-0.5 transition"
          >
            {open ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
          </button>
        ) : (
          <span className="mt-0.5 flex size-[18px] shrink-0 items-center justify-center">
            <span className="bg-border size-1.5 rounded-full" />
          </span>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-mono text-[13px] font-semibold">
              {node.part_number}
            </span>
            <MaterialBadge material={node.material_type} />
            {node.quantity !== 1 && (
              <span className="text-muted-foreground text-[11px] font-medium">
                {/* Trailing zeros dropped: a Numeric(12,4) column arrives as
                    1.8, not 1.8000, and "×2" reads better than "×2.0000". */}
                ×{Number(node.quantity.toFixed(4))} {node.unit_of_measure}
              </span>
            )}
            {node.is_phantom && (
              <span
                className="text-muted-foreground text-[10px] uppercase tracking-wide"
                title="Kitted and issued pre-assembled; exploded through rather than stocked."
              >
                phantom
              </span>
            )}
            {node.coating_status !== "N/A" && (
              <span className="text-muted-foreground text-[11px]">
                {node.coating_status}
              </span>
            )}
            <span className="text-muted-foreground ml-auto text-[11px] font-mono">
              rev {node.revision}
            </span>
          </div>
          <p className="text-muted-foreground mt-0.5 text-xs leading-snug">
            {node.description}
          </p>
        </div>
      </div>

      {hasChildren && open && (
        <ul className="border-border relative ml-[9px] border-l pl-4">
          {node.children.map((child, index) => (
            <BomRow
              key={`${child.part_number}-${child.find_number ?? index}`}
              node={child}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

export function BOMViewer({ bom }: { bom: BomResponse | null }) {
  if (!bom) {
    return (
      <div className="text-muted-foreground flex flex-col items-center gap-2 py-10 text-center text-xs">
        <Package className="size-5 opacity-40" />
        <p>
          No BOM loaded. Start the backend and seed the database, or ask the
          agent about the ECLIPSE 1kW unit.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="text-muted-foreground mb-3 flex items-center gap-3 text-[11px]">
        <span>
          <span className="text-foreground font-semibold">{bom.total_nodes}</span>{" "}
          items
        </span>
        <span>
          <span className="text-foreground font-semibold">
            {bom.max_depth + 1}
          </span>{" "}
          levels
        </span>
      </div>
      <ul className={cn("text-sm")} data-testid="bom-tree">
        <BomRow node={bom.tree} />
      </ul>
    </div>
  );
}
