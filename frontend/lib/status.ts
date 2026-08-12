/**
 * One vocabulary for every verdict in the suite.
 *
 * The API surfaces status enums from nine domains — test results, CCB
 * decisions, lifecycle states, proposal outcomes, calibration verdicts. They
 * mean different things but they resolve to the same four questions a reader
 * actually has: is this settled and good, is it settled and bad, is it waiting
 * on someone, or is it merely a fact? Mapping them once here keeps a `Fail` in
 * quality and a `Rejected` at the change board reading as the same weight of
 * news, which is the point.
 */

export type Tone = "verified" | "breach" | "warm" | "cold" | "neutral";

const BY_TONE: Record<Exclude<Tone, "neutral">, readonly string[]> = {
  verified: [
    "pass",
    "passed",
    "approve",
    "approved",
    "released",
    "closed",
    "completed",
    "complete",
    "indexed",
    "applied",
    "ok",
    "compliant",
    "proven",
    "received",
    "shipped",
    "in field",
    "traceable",
    "satisfied",
    "won",
  ],
  breach: [
    "fail",
    "failed",
    "reject",
    "rejected",
    "breach",
    "overdue",
    "error",
    "scrapped",
    "returned",
    "non-compliant",
    "violated",
    "cancelled",
    "obsolete",
    "lost",
    "blocked",
    "rma",
    "quarantine",
    "scrap",
  ],
  warm: [
    "pending",
    "open",
    "in review",
    "in_review",
    "awaiting approval",
    "awaiting_approval",
    "due soon",
    "request info",
    "request_info",
    "unproven",
    "unknown",
    "not evaluated",
    "low stock",
    "at risk",
    "escalated",
    "abstain",
    "draft",
    "at risk",
    "at_risk",
    "partially_received",
    "partially received",
    "rework",
  ],
  cold: [
    "in design",
    "in_design",
    "in production",
    "in_production",
    "in test",
    "in_test",
    "prototype",
    "submitted",
    "converted",
    "running",
    "technical_validation",
    "technical validation",
    "negotiation",
    "qualification",
    "exempt",
  ],
};

const LOOKUP = new Map<string, Tone>();
for (const [tone, members] of Object.entries(BY_TONE)) {
  for (const member of members) LOOKUP.set(member, tone as Tone);
}

export function toneFor(status: string | null | undefined): Tone {
  if (!status) return "neutral";
  return LOOKUP.get(status.trim().toLowerCase()) ?? "neutral";
}

/** Tailwind classes per tone, for the chip form. */
export const TONE_CHIP: Record<Tone, string> = {
  verified: "bg-verified-wash text-verified",
  breach: "bg-breach-wash text-breach",
  warm: "bg-warm-wash text-warm",
  cold: "bg-cold-wash text-cold",
  neutral: "bg-sunken text-ink-dim",
};

/** Tailwind text colour per tone, for bare figures. */
export const TONE_TEXT: Record<Tone, string> = {
  verified: "text-verified",
  breach: "text-breach",
  warm: "text-warm",
  cold: "text-cold",
  neutral: "text-ink",
};

/** Tailwind background per tone, for bars and rules. */
export const TONE_FILL: Record<Tone, string> = {
  verified: "bg-verified",
  breach: "bg-breach",
  warm: "bg-warm",
  cold: "bg-cold",
  neutral: "bg-ink-faint",
};

/** Material classes get their own hues — engineers scan a BOM by material. */
export function materialClass(material: string | null | undefined): string {
  switch (material) {
    case "LaFeSi":
      return "text-mat-lafesi";
    case "Neodymium":
      return "text-mat-neodymium";
    case "Polymer":
      return "text-mat-polymer";
    case "Fluid":
      return "text-mat-fluid";
    case "Steel":
      return "text-mat-steel";
    case "Composite":
      return "text-mat-composite";
    default:
      return "text-mat-assembly";
  }
}
