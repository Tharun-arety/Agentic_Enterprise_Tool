import * as React from "react";

import { cn } from "@/lib/utils";

export function Card({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "bg-surface border-border rounded-xl border shadow-sm",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "border-border flex items-start justify-between gap-3 border-b px-4 py-3",
        className,
      )}
      {...props}
    />
  );
}

export function CardTitle({ className, ...props }: React.ComponentProps<"h3">) {
  return (
    <h3
      className={cn("text-sm font-semibold tracking-tight", className)}
      {...props}
    />
  );
}

export function CardDescription({
  className,
  ...props
}: React.ComponentProps<"p">) {
  return (
    <p
      className={cn("text-muted-foreground mt-0.5 text-xs", className)}
      {...props}
    />
  );
}

export function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("p-4", className)} {...props} />;
}
