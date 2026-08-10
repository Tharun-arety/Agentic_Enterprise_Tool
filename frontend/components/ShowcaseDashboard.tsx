"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Boxes, CircleDollarSign, ClipboardCheck, FileSearch, FlaskConical, PackageCheck, RefreshCw, ShieldAlert, Sparkles } from "lucide-react";
import { AgentChatSidebar } from "@/components/AgentChatSidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { useAuth } from "@/components/AuthProvider";

type Showcase = {
  generated_at: string;
  product: string;
  product_number: string;
  counts: {
    controlled_parts: number;
    built_units: number;
    test_samples: number;
    failed_samples: number;
    open_ncrs: number;
    low_stock_items: number;
    indexed_documents: number;
    pending_proposals: number;
  };
  workflow: Array<{ domain: string; title: string; reference: string; detail: string; status: string; href: string }>;
};

const metrics = [
  ["controlled_parts", "Controlled parts", Boxes],
  ["built_units", "Built units", PackageCheck],
  ["test_samples", "Test samples", FlaskConical],
  ["failed_samples", "Failed samples", ShieldAlert],
  ["low_stock_items", "Stock risks", CircleDollarSign],
  ["indexed_documents", "Indexed documents", FileSearch],
] as const;

export function ShowcaseDashboard() {
  const { request, user, logout } = useAuth();
  const [data, setData] = React.useState<Showcase | null>(null);
  const [error, setError] = React.useState("");
  const [refreshing, setRefreshing] = React.useState(false);
  const load = React.useCallback(async (force = false) => {
    setError(""); setRefreshing(force);
    try { setData(await request<Showcase>("/api/showcase", force ? { cache: "reload" } : {})); }
    catch (reason) { setError(String(reason)); }
    finally { setRefreshing(false); }
  }, [request]);
  React.useEffect(() => {
    let active = true;
    request<Showcase>("/api/showcase").then((value) => { if (active) setData(value); }).catch((reason) => { if (active) setError(String(reason)); });
    return () => { active = false; };
  }, [request]);

  return <div className="grid h-dvh grid-cols-[3.5rem_minmax(0,1fr)_16rem] overflow-hidden xl:grid-cols-[13rem_minmax(0,1fr)_22rem]">
    <AppSidebar />
    <main className="min-w-0 overflow-y-auto">
      <header className="bg-surface/90 border-border sticky top-0 z-10 flex items-center gap-3 border-b px-6 py-3 backdrop-blur">
        <div><div className="flex items-center gap-2"><h1 className="text-base font-semibold">Engineering operations</h1><span className="bg-accent/10 text-accent rounded-full px-2 py-0.5 text-[9px] font-semibold">PUBLIC PRODUCT BASELINE · SYNTHETIC OPERATIONS</span></div><p className="text-muted-foreground text-xs">The complete ECLIPSE enterprise evidence thread</p></div>
        <button onClick={() => void load(true)} className="border-border ml-auto rounded-md border p-2" title="Refresh live data"><RefreshCw className={`size-3.5 ${refreshing ? "animate-spin" : ""}`} /></button>
        <button onClick={() => void logout()} className="text-muted-foreground text-xs">{user?.email}</button>
      </header>
      <div className="space-y-6 p-6">
        {error ? <div className="border-warning/30 bg-warning/5 text-warning rounded-lg border p-4 text-sm">{error}</div> : null}
        {!data ? <DashboardSkeleton /> : <DashboardContent data={data} />}
      </div>
    </main>
    <AgentChatSidebar />
  </div>;
}

function DashboardContent({ data }: { data: Showcase }) {
  return <>
    <section className="from-accent/15 via-surface to-surface border-border relative overflow-hidden rounded-2xl border bg-gradient-to-br p-6">
      <Sparkles className="text-accent/20 absolute -right-5 -top-6 size-32" />
      <p className="text-accent text-xs font-semibold uppercase tracking-[0.18em]">{data.product_number}</p>
      <h2 className="mt-2 max-w-2xl text-2xl font-semibold tracking-tight">{data.product}</h2>
      <p className="text-muted-foreground mt-2 max-w-3xl text-sm leading-6">A working portfolio replica grounded in Magnotherm&apos;s public ECLIPSE product and technology facts. Transactional suppliers, lots, serials, costs, failures, approvals, and documents are coherent synthetic records generated through the application services.</p>
      <div className="mt-5 flex flex-wrap gap-2 text-xs"><Link href="/pdm" className="bg-accent text-accent-foreground rounded-md px-3 py-2 font-semibold">Explore MBOM</Link><Link href="/qms" className="border-border bg-surface rounded-md border px-3 py-2 font-semibold">Inspect unit evidence</Link><Link href="/ecm" className="border-border bg-surface rounded-md border px-3 py-2 font-semibold">Open CCB impact</Link></div>
    </section>
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {metrics.map(([key, label, Icon]) => <article key={key} className="bg-surface border-border rounded-xl border p-4"><div className="flex items-center gap-2"><Icon className="text-accent size-4" /><p className="text-muted-foreground text-xs">{label}</p></div><p className="mt-3 text-2xl font-semibold tabular-nums">{data.counts[key]}</p></article>)}
    </section>
    <section>
      <div className="mb-3 flex items-end justify-between gap-4"><div><p className="text-accent text-[10px] font-semibold uppercase tracking-[0.18em]">Golden workflow</p><h2 className="mt-1 text-lg font-semibold">Receipt to searchable change evidence</h2></div><p className="text-muted-foreground hidden text-[10px] sm:block">Updated {new Date(data.generated_at).toLocaleTimeString()}</p></div>
      <div className="grid gap-3 lg:grid-cols-2">{data.workflow.map((step, index) => <Link key={`${step.domain}-${step.reference}`} href={step.href} className="bg-surface border-border hover:border-accent/50 group rounded-xl border p-4 transition-colors"><div className="flex gap-3"><span className="bg-accent/10 text-accent grid size-8 shrink-0 place-items-center rounded-full text-xs font-bold">{index + 1}</span><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><p className="text-muted-foreground text-[10px] font-semibold uppercase tracking-wider">{step.domain}</p><span className="bg-surface-muted rounded-full px-2 py-0.5 text-[10px]">{step.status}</span></div><h3 className="mt-1 text-sm font-semibold">{step.title}</h3><p className="text-accent mt-2 font-mono text-xs font-semibold">{step.reference}</p><p className="text-muted-foreground mt-1 text-xs">{step.detail}</p></div><ArrowRight className="text-muted-foreground group-hover:text-accent mt-1 size-4 transition-colors" /></div></Link>)}</div>
    </section>
    <section className="bg-surface border-border flex flex-wrap items-center gap-3 rounded-xl border p-4"><ClipboardCheck className="text-accent size-5" /><div><p className="text-sm font-semibold">Human approval remains mandatory</p><p className="text-muted-foreground text-xs">{data.counts.pending_proposals} agent proposal(s) currently await review; agent tools never apply mutations directly.</p></div><Link href="/approval-inbox" className="text-accent ml-auto text-xs font-semibold">Open approval inbox →</Link></section>
  </>;
}

function DashboardSkeleton() {
  return <div className="space-y-4" aria-label="Loading showcase data"><div className="bg-surface-muted h-48 animate-pulse rounded-2xl" /><div className="grid gap-3 sm:grid-cols-3">{Array.from({ length: 6 }, (_, index) => <div key={index} className="bg-surface-muted h-24 animate-pulse rounded-xl" />)}</div><div className="grid gap-3 lg:grid-cols-2">{Array.from({ length: 4 }, (_, index) => <div key={index} className="bg-surface-muted h-32 animate-pulse rounded-xl" />)}</div></div>;
}
