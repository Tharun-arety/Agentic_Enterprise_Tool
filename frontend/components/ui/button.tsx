import * as React from "react";

import { cn } from "@/lib/utils";

type Variant = "primary" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-foreground hover:opacity-90 disabled:opacity-40",
  ghost:
    "text-muted-foreground hover:bg-surface-muted hover:text-foreground disabled:opacity-40",
};

export function Button({
  className,
  variant = "primary",
  ...props
}: React.ComponentProps<"button"> & { variant?: Variant }) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed",
        VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
}
