"use client";

import * as React from "react";
import { AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";
import { AgentChatSidebar } from "@/components/AgentChatSidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { useAuth } from "@/components/AuthProvider";

export function EnterprisePage({ title, subtitle, path }: { title: string; subtitle: string; path: string }) {
  const { request, user, logout } = useAuth();
  const [data, setData] = React.useState<unknown>(null);
  const [error, setError] = React.useState("");
  const [refreshing, setRefreshing] = React.useState(false);

  const load = React.useCallback(async (force = false) => {
    setError(""); setRefreshing(force);
    try { setData(await request(path, force ? { cache: "reload" } : {})); }
    catch (reason) { setError(String(reason)); }
    finally { setRefreshing(false); }
  }, [path, request]);

  React.useEffect(() => {
    let active = true;
    request(path).then((value) => { if (active) setData(value); }).catch((reason) => { if (active) setError(String(reason)); });
    return () => { active = false; };
  }, [path, request]);

  return <div className="grid h-dvh grid-cols-[3.5rem_minmax(0,1fr)_16rem] overflow-hidden xl:grid-cols-[13rem_minmax(0,1fr)_22rem]">
    <AppSidebar />
    <main className="min-w-0 overflow-y-auto">
      <header className="bg-surface/90 border-border sticky top-0 z-10 flex items-center gap-3 border-b px-6 py-3 backdrop-blur">
        <div><div className="flex items-center gap-2"><h1 className="text-base font-semibold">{title}</h1><span className="bg-accent/10 text-accent rounded-full px-2 py-0.5 text-[9px] font-semibold">SYNTHETIC</span></div><p className="text-muted-foreground text-xs">{subtitle}</p></div>
        <button onClick={() => void load(true)} className="border-border ml-auto rounded-md border p-2" title="Refresh"><RefreshCw className={`size-3.5 ${refreshing ? "animate-spin" : ""}`} /></button>
        <button onClick={() => void logout()} className="text-muted-foreground text-xs">{user?.email}</button>
      </header>
      <div className="p-6">{error ? <div className="border-warning/30 bg-warning/5 text-warning flex gap-2 rounded-lg border p-3 text-xs"><AlertTriangle className="size-4" />{error}</div> : data === null ? <LoadingCards /> : <DataView data={data} />}</div>
    </main>
    <AgentChatSidebar />
  </div>;
}

function LoadingCards() {
  return <div className="grid gap-3 lg:grid-cols-2">{Array.from({ length: 4 }, (_, index) => <div key={index} className="bg-surface-muted h-36 animate-pulse rounded-lg" />)}</div>;
}

function DataView({ data }: { data: unknown }) {
  if (Array.isArray(data)) return <div className="grid gap-3 lg:grid-cols-2">{data.length ? data.map((value, index) => <RecordCard key={index} value={value} />) : <Empty />}</div>;
  if (data && typeof data === "object") return <RecordCard value={data} />;
  return <pre>{String(data)}</pre>;
}

function RecordCard({ value }: { value: unknown }) {
  const object = value as Record<string, unknown>;
  return <article className="bg-surface border-border overflow-hidden rounded-lg border"><div className="border-border flex items-center gap-2 border-b px-4 py-2"><CheckCircle2 className="text-accent size-3.5" /><span className="text-xs font-semibold">{String(object.title ?? object.name ?? object.part_number ?? object.number ?? object.code ?? object.id ?? "Record")}</span></div><dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-2 p-4 text-xs">{Object.entries(object).slice(0, 14).map(([key, field]) => <React.Fragment key={key}><dt className="text-muted-foreground truncate">{key.replaceAll("_", " ")}</dt><dd className="min-w-0 break-words font-mono text-[11px]">{typeof field === "object" ? JSON.stringify(field) : String(field ?? "—")}</dd></React.Fragment>)}</dl></article>;
}

function Empty() {
  return <div className="border-border text-muted-foreground rounded-lg border border-dashed p-10 text-center text-sm">No records yet.</div>;
}
