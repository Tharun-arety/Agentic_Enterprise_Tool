import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * The panel is the only container in the suite.
 *
 * Hairline border, 4px radius, no shadow: this is instrumentation, and a
 * soft-cornered floating card would be borrowed from a marketing page. Depth
 * comes from the surface colour alone.
 */
export function Panel({
  className,
  children,
  ...rest
}: React.ComponentProps<"section">) {
  return (
    <section
      className={cn("bg-panel border-rule rounded-panel border", className)}
      {...rest}
    >
      {children}
    </section>
  );
}

export function PanelHeader({
  eyebrow,
  title,
  meta,
  action,
  className,
}: {
  /** The classification, not a decoration — a domain code or record class. */
  eyebrow?: string;
  title: React.ReactNode;
  meta?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "border-rule flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b px-4 py-3",
        className,
      )}
    >
      <div className="min-w-0 flex-1">
        {eyebrow && <p className="eyebrow mb-1.5">{eyebrow}</p>}
        <h2 className="truncate text-sm font-semibold tracking-tight">{title}</h2>
      </div>
      {meta && <div className="text-ink-faint shrink-0 text-xs">{meta}</div>}
      {action}
    </header>
  );
}

export function PanelBody({ className, children }: React.ComponentProps<"div">) {
  return <div className={cn("p-4", className)}>{children}</div>;
}

/**
 * A labelled reading. Callers pass curated pairs — never an object spread,
 * which is how the old screens ended up printing raw column names.
 */
export function Field({
  label,
  children,
  mono,
  className,
}: {
  label: string;
  children: React.ReactNode;
  mono?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <dt className="eyebrow mb-1">{label}</dt>
      <dd className={cn("min-w-0 break-words text-sm", mono && "ident")}>{children}</dd>
    </div>
  );
}

export function FieldGrid({ className, children }: React.ComponentProps<"dl">) {
  return (
    <dl className={cn("grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3", className)}>
      {children}
    </dl>
  );
}

/**
 * A figure with its label, for the row of readings under a title block.
 * Deliberately not a "stat card" — no border, no icon, no gradient. The number
 * carries it.
 */
export function Reading({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  tone?: string;
  hint?: string;
}) {
  return (
    <div className="min-w-0">
      <p className="eyebrow">{label}</p>
      <p className={cn("ident mt-1.5 truncate text-xl font-semibold", tone)}>{value}</p>
      {hint && <p className="text-ink-faint mt-0.5 truncate text-[11px]">{hint}</p>}
    </div>
  );
}
