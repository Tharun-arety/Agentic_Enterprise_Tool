"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, BookOpen, Boxes, Building2, CheckSquare, Factory, FileSearch, FlaskConical, Gauge, GitPullRequest, Landmark, PackageSearch, ShieldCheck, Snowflake, Users } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { cn } from "@/lib/utils";

const sections = [
  ["/", "Overview", Gauge, "/api/showcase"],
  ["/pdm", "PDM", Boxes, "/api/parts/ECL-SYS-1000/bom?bom_type=MBOM"],
  ["/ecm", "ECM", GitPullRequest, "/api/ecm/requests"],
  ["/qms", "QMS", FlaskConical, "/api/qms/ECL-M-104"],
  ["/procurement", "Procurement", PackageSearch, "/api/procurement/stock-risk"],
  ["/crm", "CRM", Building2, "/api/crm/opportunities"],
  ["/programs", "Programs", Landmark, "/api/programs/trl"],
  ["/assets", "Assets", Factory, "/api/assets/calibration"],
  ["/resources", "Resources", Users, "/api/resources/capacity"],
  ["/controlling", "Controlling", BarChart3, "/api/controlling/rollup/ECL-SYS-1000?batch_size=10"],
  ["/knowledge", "Knowledge", BookOpen, "/api/knowledge/ingestion"],
  ["/agent-runs", "Agent runs", Activity, "/api/agent-runs"],
  ["/evals", "Evals", ShieldCheck, "/api/evals"],
  ["/audit", "Audit", FileSearch, "/api/audit"],
  ["/approval-inbox", "Approvals", CheckSquare, "/api/proposals?status=pending"],
] as const;

export function AppSidebar() {
  const path = usePathname();
  const { prefetch } = useAuth();
  return (
    <nav className="bg-surface border-border flex h-full flex-col border-r">
      <div className="border-border flex items-center gap-2 border-b px-3 py-3">
        <span className="bg-accent/10 text-accent rounded-md p-1.5"><Snowflake className="size-4" /></span>
        <div className="hidden xl:block"><p className="text-sm font-semibold">Magnotherm</p><p className="text-muted-foreground text-[10px]">Enterprise toolchain</p></div>
      </div>
      <ul className="flex-1 space-y-0.5 overflow-y-auto p-2">
        {sections.map(([href, label, Icon, apiPath]) => {
          const active = href === "/" ? path === href : path.startsWith(href);
          return (
            <li key={href}>
              <Link
                href={href}
                title={label}
                onMouseEnter={() => prefetch(apiPath)}
                onFocus={() => prefetch(apiPath)}
                className={cn("flex items-center justify-center gap-2 rounded-md px-2 py-1.5 text-xs xl:justify-start", active ? "bg-accent/10 text-accent" : "text-muted-foreground hover:bg-surface-muted")}
              >
                <Icon className="size-3.5" /><span className="hidden xl:inline">{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="border-border text-muted-foreground hidden border-t p-3 text-[10px] xl:block">Refrigerant-free engineering operations</div>
    </nav>
  );
}
