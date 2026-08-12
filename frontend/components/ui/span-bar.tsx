import * as React from "react";
import { formatNumber } from "@/lib/format";
import { TONE_FILL, TONE_TEXT, type Tone } from "@/lib/status";
import { cn } from "@/lib/utils";

/**
 * A value drawn against the limits it is judged by.
 *
 * Nearly everything this company records is a quantity measured against a
 * bound: temperature span above a floor, pressure drop below a ceiling, stock
 * above a reorder level, allocated hours under capacity, cost under budget.
 * Printing `{"on_hand": 2, "reorder_level": 4}` makes the reader do the
 * comparison. Drawing it does the comparison for them.
 *
 * The form is borrowed from an inspection report rather than invented: a
 * tinted band marks the acceptable region, hairline ticks mark the limits, and
 * a stem marks where the measurement actually landed.
 */

export interface SpanBarProps {
  label: string;
  value: number;
  unit?: string;
  /** Floor the value must stay above. */
  lower?: number | null;
  /** Ceiling the value must stay below. */
  upper?: number | null;
  digits?: number;
  /** Override the computed verdict — for values the backend already judged. */
  tone?: Tone;
  /** Extra context printed under the label, e.g. a lead time. */
  note?: string;
  className?: string;
}

function verdictFor(value: number, lower?: number | null, upper?: number | null): Tone {
  const belowFloor = lower !== null && lower !== undefined && value < lower;
  const aboveCeiling = upper !== null && upper !== undefined && value > upper;
  if (belowFloor || aboveCeiling) return "breach";

  // Within a tenth of the tolerance width of either limit: worth a look before
  // it becomes a non-conformance.
  const width =
    lower !== null && lower !== undefined && upper !== null && upper !== undefined
      ? upper - lower
      : Math.abs(value) || 1;
  const margin = width * 0.1;
  const nearFloor = lower !== null && lower !== undefined && value - lower <= margin;
  const nearCeiling = upper !== null && upper !== undefined && upper - value <= margin;
  if (nearFloor || nearCeiling) return "warm";

  return "verified";
}

export function SpanBar({
  label,
  value,
  unit,
  lower,
  upper,
  digits = 1,
  tone,
  note,
  className,
}: SpanBarProps) {
  const hasLower = lower !== null && lower !== undefined && Number.isFinite(lower);
  const hasUpper = upper !== null && upper !== undefined && Number.isFinite(upper);
  const resolved = tone ?? verdictFor(value, hasLower ? lower : null, hasUpper ? upper : null);

  const marks = [value, hasLower ? lower! : null, hasUpper ? upper! : null].filter(
    (mark): mark is number => mark !== null,
  );
  const low = Math.min(...marks);
  const high = Math.max(...marks);
  // A one-sided limit gives a degenerate range; pad from the magnitude instead
  // so the single tick does not sit on the very edge of the track.
  const pad = (high - low || Math.abs(high) || 1) * 0.3;
  const from = low - pad;
  const to = high + pad;
  const at = (mark: number) => ((mark - from) / (to - from)) * 100;

  const bandStart = hasLower ? at(lower!) : 0;
  const bandEnd = hasUpper ? at(upper!) : 100;

  const reading = `${formatNumber(value, digits)}${unit ? ` ${unit}` : ""}`;
  const boundText = [
    hasLower ? `min ${formatNumber(lower!, digits)}` : null,
    hasUpper ? `max ${formatNumber(upper!, digits)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className={cn("min-w-0", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-ink-dim min-w-0 truncate text-xs">{label}</span>
        <span className={cn("ident shrink-0 text-sm font-semibold", TONE_TEXT[resolved])}>
          {reading}
        </span>
      </div>

      <div
        role="meter"
        aria-label={label}
        aria-valuenow={value}
        aria-valuemin={hasLower ? lower! : undefined}
        aria-valuemax={hasUpper ? upper! : undefined}
        aria-valuetext={boundText ? `${reading} (${boundText})` : reading}
        className="bg-sunken relative mt-2 h-2 w-full overflow-hidden rounded-full"
      >
        {/* The acceptable region. */}
        <div
          className={cn("absolute inset-y-0 opacity-20", TONE_FILL.verified)}
          style={{ left: `${bandStart}%`, width: `${Math.max(bandEnd - bandStart, 0)}%` }}
        />
        {/* Limit ticks. */}
        {hasLower && (
          <div
            className="bg-rule-strong absolute inset-y-0 w-px"
            style={{ left: `${at(lower!)}%` }}
          />
        )}
        {hasUpper && (
          <div
            className="bg-rule-strong absolute inset-y-0 w-px"
            style={{ left: `${at(upper!)}%` }}
          />
        )}
        {/* Where the measurement landed. */}
        <div
          className={cn("absolute inset-y-0 w-[3px] -translate-x-1/2 rounded-full", TONE_FILL[resolved])}
          style={{ left: `${at(value)}%` }}
        />
      </div>

      {(boundText || note) && (
        <div className="text-ink-faint mt-1.5 flex items-center justify-between gap-3 text-[10px]">
          <span className="min-w-0 truncate">{note ?? ""}</span>
          {boundText && <span className="ident shrink-0">{boundText}</span>}
        </div>
      )}
    </div>
  );
}
