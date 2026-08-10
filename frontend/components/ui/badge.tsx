import * as React from "react";

import { cn } from "@/lib/utils";
import type { MaterialType } from "@/lib/types";

/**
 * Material colours come from CSS custom properties rather than being hard-coded
 * per component, so light and dark themes stay in sync from one definition.
 */
const MATERIAL_STYLE: Record<MaterialType, string> = {
  LaFeSi: "border-lafesi/40 text-lafesi bg-lafesi/10",
  Neodymium: "border-neodymium/40 text-neodymium bg-neodymium/10",
  Polymer: "border-polymer/40 text-polymer bg-polymer/10",
  Fluid: "border-fluid/40 text-fluid bg-fluid/10",
  Composite: "border-assembly/40 text-assembly bg-assembly/10",
  Steel: "border-assembly/40 text-assembly bg-assembly/10",
  Assembly: "border-assembly/30 text-muted-foreground bg-surface-muted",
};

export function Badge({
  className,
  ...props
}: React.ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "border-border inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap",
        className,
      )}
      {...props}
    />
  );
}

export function MaterialBadge({
  material,
  className,
}: {
  material: MaterialType;
  className?: string;
}) {
  return (
    <Badge className={cn(MATERIAL_STYLE[material], className)}>{material}</Badge>
  );
}
