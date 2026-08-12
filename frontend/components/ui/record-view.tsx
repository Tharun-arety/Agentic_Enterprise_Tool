import * as React from "react";
import { humanise } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Structured rendering for payloads whose shape is genuinely not known ahead
 * of time — an agent tool's dry-run preview, an audit event's before and after.
 *
 * These are the only places in the suite where the shape really is open, and
 * they are exactly where the old screens gave up and printed
 * `JSON.stringify(value)`. A generic renderer is the right answer here; a
 * generic renderer that emits braces and quotes is not. Scalars become
 * labelled readings, lists of records become small tables, and nesting becomes
 * indentation.
 */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function Scalar({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-ink-faint">—</span>;
  }
  if (typeof value === "boolean") {
    return (
      <span className={value ? "text-verified font-semibold" : "text-ink-dim"}>
        {value ? "Yes" : "No"}
      </span>
    );
  }
  if (typeof value === "number") {
    return <span className="ident">{value}</span>;
  }
  const text = String(value);
  // Identifiers, dates and codes read better monospaced; prose does not.
  const looksLikeIdentifier = /^[A-Z0-9][A-Z0-9._:/-]{2,}$/.test(text) || /^\d{4}-\d{2}-\d{2}/.test(text);
  return <span className={cn("break-words", looksLikeIdentifier && "ident")}>{text}</span>;
}

export function RecordView({
  value,
  depth = 0,
}: {
  value: unknown;
  depth?: number;
}) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-ink-faint text-xs">none</span>;

    // A list of same-shaped records is a table; anything else is a list.
    if (value.every(isRecord)) {
      const columns = [...new Set(value.flatMap((row) => Object.keys(row)))];
      return (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-[11px]">
            <thead>
              <tr className="border-rule border-b">
                {columns.map((column) => (
                  <th key={column} scope="col" className="eyebrow whitespace-nowrap py-1.5 pr-4 font-semibold">
                    {humanise(column)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {value.map((row, index) => (
                <tr key={index} className="border-rule border-b last:border-b-0">
                  {columns.map((column) => (
                    <td key={column} className="max-w-xs py-1.5 pr-4 align-top">
                      <RecordView value={row[column]} depth={depth + 1} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }

    return (
      <span className="flex flex-wrap gap-1">
        {value.map((entry, index) => (
          <span key={index} className="bg-sunken rounded-chip px-1.5 py-0.5 text-[11px]">
            <RecordView value={entry} depth={depth + 1} />
          </span>
        ))}
      </span>
    );
  }

  if (isRecord(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) return <span className="text-ink-faint text-xs">empty</span>;
    return (
      <dl className={cn("grid gap-x-4 gap-y-2", depth === 0 && "sm:grid-cols-2")}>
        {entries.map(([key, entry]) => (
          <div key={key} className="min-w-0">
            <dt className="eyebrow mb-1">{humanise(key)}</dt>
            <dd className="min-w-0 text-xs">
              <RecordView value={entry} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }

  return <Scalar value={value} />;
}

/**
 * What actually changed between two states of a record. Fields that did not
 * move are omitted — a reviewer looking at an audit entry wants the delta, and
 * printing every unchanged column buries it.
 */
export function DiffView({
  before,
  after,
}: {
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}) {
  if (!before && !after) {
    return <p className="text-ink-faint text-[11px]">No field-level detail was captured.</p>;
  }

  if (!before) {
    return (
      <div>
        <p className="eyebrow text-verified mb-2">Created</p>
        <RecordView value={after} />
      </div>
    );
  }

  if (!after) {
    return (
      <div>
        <p className="eyebrow text-breach mb-2">Removed</p>
        <RecordView value={before} />
      </div>
    );
  }

  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].filter(
    (key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]),
  );

  if (keys.length === 0) {
    return <p className="text-ink-faint text-[11px]">Recorded, but no field changed value.</p>;
  }

  return (
    <table className="w-full border-collapse text-left text-[11px]">
      <caption className="sr-only">Fields changed by this event</caption>
      <thead>
        <tr className="border-rule border-b">
          <th scope="col" className="eyebrow py-1.5 pr-4">Field</th>
          <th scope="col" className="eyebrow py-1.5 pr-4">From</th>
          <th scope="col" className="eyebrow py-1.5">To</th>
        </tr>
      </thead>
      <tbody>
        {keys.map((key) => (
          <tr key={key} className="border-rule border-b last:border-b-0">
            <td className="py-1.5 pr-4 align-top font-medium">{humanise(key)}</td>
            <td className="text-ink-faint max-w-[16rem] py-1.5 pr-4 align-top line-through">
              <RecordView value={before[key]} depth={1} />
            </td>
            <td className="text-verified max-w-[16rem] py-1.5 align-top">
              <RecordView value={after[key]} depth={1} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
