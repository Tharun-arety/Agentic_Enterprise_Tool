/**
 * Backend access helpers.
 *
 * Every read is failure-tolerant on purpose: the dashboard must still render if
 * the FastAPI service is down or the database has not been seeded yet. A blank
 * card with an honest empty state beats a crashed page.
 */

import type {
  BomResponse,
  HealthResponse,
  KnowledgeResponse,
  QmsResponse,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

/** The seeded demo unit — the ECLIPSE regenerator module instance under test. */
export const DEMO_SERIAL = "ECL-M-104";
/** The seeded top-level product. */
export const DEMO_PART = "ECL-SYS-1000";

async function getJson<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      // Engineering data changes when someone re-seeds or a test completes;
      // caching it would show stale figures on the dashboard.
      cache: "no-store",
    });
    if (!response.ok) {
      console.warn(`GET ${path} -> ${response.status}`);
      return null;
    }
    return (await response.json()) as T;
  } catch (error) {
    console.warn(`GET ${path} failed:`, error);
    return null;
  }
}

export const fetchHealth = () => getJson<HealthResponse>("/api/health");

export const fetchBom = (partNumber: string = DEMO_PART) =>
  getJson<BomResponse>(`/api/parts/${encodeURIComponent(partNumber)}/bom`);

export const fetchQms = (serialNumber: string = DEMO_SERIAL) =>
  getJson<QmsResponse>(`/api/qms/${encodeURIComponent(serialNumber)}`);

export const fetchKnowledge = (query = "engineering change", limit = 5) =>
  getJson<KnowledgeResponse>(
    `/api/knowledge?q=${encodeURIComponent(query)}&limit=${limit}`,
  );
