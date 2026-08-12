"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/ui/states";

/**
 * A real table with declared columns.
 *
 * The column list is required and typed, which is the whole point: the screens
 * this replaced iterated `Object.entries(record).slice(0, 14)` and printed
 * whatever the API happened to send, snake_case keys and stringified JSON
 * included. Making the caller name each column forces a decision about what a
 * reader needs and what a reader does not.
 */

export interface Column<Row> {
  key: string;
  header: string;
  align?: "left" | "right";
  /** Tailwind width utility, for columns that should not flex. */
  width?: string;
  /** Hide below the given breakpoint on narrow screens. */
  hideBelow?: "sm" | "md" | "lg" | "xl";
  cell: (row: Row, index: number) => React.ReactNode;
}

const HIDE_CLASS: Record<NonNullable<Column<unknown>["hideBelow"]>, string> = {
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
  xl: "hidden xl:table-cell",
};

export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  caption,
  emptyTitle = "Nothing recorded yet",
  emptyBody,
  initialRows = 40,
  className,
}: {
  columns: Array<Column<Row>>;
  rows: Row[];
  rowKey: (row: Row, index: number) => string;
  /** Screen-reader description of what the table holds. */
  caption: string;
  emptyTitle?: string;
  emptyBody?: string;
  /** Rows shown before the reveal control appears. Keeps long logs cheap. */
  initialRows?: number;
  className?: string;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const visible = expanded ? rows : rows.slice(0, initialRows);
  const hidden = rows.length - visible.length;

  if (rows.length === 0) {
    return <EmptyState title={emptyTitle} body={emptyBody} />;
  }

  return (
    <div className={className}>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-xs">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="border-rule border-b">
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  className={cn(
                    "eyebrow whitespace-nowrap px-4 py-2.5 font-semibold",
                    column.align === "right" && "text-right",
                    column.width,
                    column.hideBelow && HIDE_CLASS[column.hideBelow],
                  )}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, index) => (
              <tr
                key={rowKey(row, index)}
                className="border-rule hover:bg-sunken border-b transition-colors last:border-b-0"
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      "px-4 py-2.5 align-top",
                      column.align === "right" && "text-right",
                      column.hideBelow && HIDE_CLASS[column.hideBelow],
                    )}
                  >
                    {column.cell(row, index)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {hidden > 0 && (
        <div className="border-rule border-t px-4 py-2.5">
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="text-cold hover:text-ink text-xs font-semibold transition-colors"
          >
            Show {hidden} More {hidden === 1 ? "Row" : "Rows"}
          </button>
        </div>
      )}
    </div>
  );
}
