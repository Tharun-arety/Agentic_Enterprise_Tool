import * as React from "react";
import { humanise } from "@/lib/format";
import { TONE_CHIP, materialClass, toneFor, type Tone } from "@/lib/status";
import { cn } from "@/lib/utils";

/**
 * A settled outcome, rendered at the weight the outcome deserves.
 *
 * Pass the raw enum the API returned; the vocabulary in `lib/status.ts` sorts
 * it into a tone and `humanise` makes it readable. Callers should not be
 * mapping status strings themselves — that is how `technical_validation` ends
 * up on screen.
 */
export function Verdict({
  status,
  tone,
  label,
  className,
}: {
  status?: string | null;
  tone?: Tone;
  label?: string;
  className?: string;
}) {
  const resolved = tone ?? toneFor(status);
  return (
    <span
      className={cn(
        "rounded-chip inline-flex items-center whitespace-nowrap px-1.5 py-0.5 text-[11px] font-semibold",
        TONE_CHIP[resolved],
        className,
      )}
    >
      {label ?? humanise(status)}
    </span>
  );
}

/**
 * An identifier: part number, serial, lot, certificate, revision. Always
 * monospaced, and never machine-translated — a part number that Chrome decides
 * to localise is a part number nobody can search for.
 */
export function Ident({
  children,
  className,
  title,
}: {
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span translate="no" title={title} className={cn("ident", className)}>
      {children}
    </span>
  );
}

/** A revision letter, set apart from the part number it qualifies. */
export function RevisionTag({ revision }: { revision?: string | null }) {
  if (!revision) return null;
  return (
    <span
      translate="no"
      className="bg-sunken text-ink-dim rounded-chip ident px-1 py-px text-[10px] font-semibold"
    >
      rev&nbsp;{revision}
    </span>
  );
}

export function MaterialBadge({ material }: { material?: string | null }) {
  if (!material) return null;
  return (
    <span className={cn("text-[11px] font-medium", materialClass(material))}>
      {material}
    </span>
  );
}
