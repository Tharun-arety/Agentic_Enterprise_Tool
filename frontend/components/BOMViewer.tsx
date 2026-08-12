"use client";

import * as React from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Ident, MaterialBadge, RevisionTag } from "@/components/ui/verdict";
import { formatQuantity } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { BomNode, BomResponse } from "@/lib/types";

/**
 * A bill of materials as a structure table, not a bulleted tree.
 *
 * Engineers read a BOM in columns — find number, part, quantity, extended
 * quantity — and compare down the column. The previous rendering wrapped every
 * description under its part and made that comparison impossible. The tree is
 * flattened to rows here so the columns line up; indentation and the guide
 * rules carry the hierarchy.
 */

interface Row {
  node: BomNode;
  path: string;
  depth: number;
  hasChildren: boolean;
  expanded: boolean;
}

function flatten(
  node: BomNode,
  collapsed: ReadonlySet<string>,
  path = node.part_number,
  depth = 0,
  rows: Row[] = [],
): Row[] {
  const hasChildren = node.children.length > 0;
  const expanded = hasChildren && !collapsed.has(path);
  rows.push({ node, path, depth, hasChildren, expanded });
  if (expanded) {
    node.children.forEach((child, index) => {
      flatten(child, collapsed, `${path}/${child.find_number ?? index}`, depth + 1, rows);
    });
  }
  return rows;
}

export function BOMViewer({ bom }: { bom: BomResponse }) {
  const [collapsed, setCollapsed] = React.useState<ReadonlySet<string>>(new Set());
  const rows = React.useMemo(() => flatten(bom.tree, collapsed), [bom.tree, collapsed]);

  const toggle = (path: string) =>
    setCollapsed((current) => {
      const next = new Set(current);
      if (!next.delete(path)) next.add(path);
      return next;
    });

  return (
    <div className="overflow-x-auto" data-testid="bom-tree">
      <table className="w-full border-collapse text-left text-xs">
        <caption className="sr-only">
          {bom.bom_type} structure for {bom.root_part_number} revision {bom.root_revision}
        </caption>
        <thead>
          <tr className="border-rule border-b">
            <th scope="col" className="eyebrow px-4 py-2.5">
              Find / part
            </th>
            <th scope="col" className="eyebrow hidden px-4 py-2.5 lg:table-cell">
              Description
            </th>
            <th scope="col" className="eyebrow hidden px-4 py-2.5 sm:table-cell">
              Material
            </th>
            <th scope="col" className="eyebrow px-4 py-2.5 text-right">
              Qty
            </th>
            <th scope="col" className="eyebrow px-4 py-2.5 text-right" title="Per finished unit, with scrap compounded down the tree">
              Extended
            </th>
            <th scope="col" className="eyebrow hidden px-4 py-2.5 md:table-cell">
              Flags
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ node, path, depth, hasChildren, expanded }) => (
            <tr key={path} className="border-rule hover:bg-sunken border-b transition-colors last:border-b-0">
              <td className="whitespace-nowrap py-2 pr-4" style={{ paddingLeft: `${depth * 1.125 + 1}rem` }}>
                <span className="flex items-center gap-1.5">
                  {hasChildren ? (
                    <button
                      type="button"
                      onClick={() => toggle(path)}
                      aria-expanded={expanded}
                      aria-label={`${expanded ? "Collapse" : "Expand"} ${node.part_number}`}
                      className="text-ink-faint hover:text-ink -ml-1 rounded p-0.5 transition-colors"
                    >
                      {expanded ? (
                        <ChevronDown className="size-3.5" aria-hidden="true" />
                      ) : (
                        <ChevronRight className="size-3.5" aria-hidden="true" />
                      )}
                    </button>
                  ) : (
                    <span className="bg-rule-strong ml-1 size-1 shrink-0 rounded-full" aria-hidden="true" />
                  )}
                  {node.find_number && (
                    <Ident className="text-ink-faint w-6 text-[11px]">{node.find_number}</Ident>
                  )}
                  <Ident className={cn("text-[13px] font-semibold", node.is_configuration_item && "text-cold")}>
                    {node.part_number}
                  </Ident>
                  <RevisionTag revision={node.revision} />
                </span>
              </td>

              <td className="text-ink-dim hidden max-w-md px-4 py-2 lg:table-cell">
                <span className="line-clamp-2">{node.description}</span>
              </td>

              <td className="hidden whitespace-nowrap px-4 py-2 sm:table-cell">
                <MaterialBadge material={node.material_type} />
              </td>

              <td className="ident whitespace-nowrap px-4 py-2 text-right">
                {formatQuantity(node.quantity)}
                <span className="text-ink-faint ml-1">{node.unit_of_measure}</span>
              </td>

              <td className="ident text-ink-dim whitespace-nowrap px-4 py-2 text-right">
                {formatQuantity(node.extended_quantity)}
              </td>

              <td className="hidden whitespace-nowrap px-4 py-2 md:table-cell">
                <span className="text-ink-faint flex gap-2 text-[10px] uppercase tracking-wide">
                  {node.is_configuration_item && (
                    <span className="text-cold" title="Configuration item under ISO 10007 change control">
                      CI
                    </span>
                  )}
                  {node.is_phantom && (
                    <span title="Kitted pre-assembled; exploded through rather than stocked">
                      phantom
                    </span>
                  )}
                  {node.scrap_factor > 0 && (
                    <span title="Scrap allowance applied to the extended quantity">
                      +{Math.round(node.scrap_factor * 100)}% scrap
                    </span>
                  )}
                  {node.operation_seq !== null && <span>op&nbsp;{node.operation_seq}</span>}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
