"use client";

import * as React from "react";
import { Shell } from "@/components/Shell";
import { useAuth } from "@/components/AuthProvider";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/states";
import { Verdict } from "@/components/ui/verdict";
import { formatNumber, formatTimestamp, humanise } from "@/lib/format";
import { Loaded, useResource } from "@/lib/use-resource";
import { cn } from "@/lib/utils";
import type { EvalRun } from "@/lib/types";

/**
 * Evaluations.
 *
 * A run reports its cases, grouped by what each case is actually checking —
 * routing, retrieval, citation, permission. A suite that reports only
 * "12 passed, 1 failed" is a number nobody can act on; the useful screen names
 * the failing case and what it expected.
 */
export default function EvaluationsPage() {
  const runs = useResource<EvalRun[]>("/api/evals");
  const { request, user } = useAuth();
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState("");

  const latest = runs.data?.[0];
  const isAdmin = user?.roles.includes("admin");

  const runSuite = async () => {
    setRunning(true);
    setError("");
    try {
      await request("/api/evals/offline", { method: "POST" });
      runs.reload();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setRunning(false);
    }
  };

  return (
    <Shell
      eyebrow="Agents & control · regression"
      title="Agent evaluations"
      summary="Offline golden cases run against the stub model client, so agent behaviour can be regression-tested without spending a token."
      cells={
        latest
          ? [
              { label: "Last run", value: formatTimestamp(latest.started_at) },
              {
                label: "Result",
                value: (
                  <span className={latest.failed === 0 ? "text-verified" : "text-breach"}>
                    {latest.passed} pass / {latest.failed} fail
                  </span>
                ),
              },
            ]
          : []
      }
      onRefresh={runs.reload}
      refreshing={runs.refreshing}
    >
      <div className="space-y-4">
        <Panel className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">Run the offline suite</p>
            <p className="text-ink-dim mt-0.5 text-pretty text-xs leading-5">
              {isAdmin
                ? "Executes every golden case against the deterministic client and records the results below."
                : "Running the suite is an admin action. Sign in as admin to execute it."}
            </p>
          </div>
          <button
            type="button"
            disabled={running || !isAdmin}
            onClick={() => void runSuite()}
            className="bg-cold text-cold-ink rounded-chip shrink-0 px-3 py-1.5 text-xs font-semibold transition-opacity disabled:opacity-40"
          >
            {running ? "Running…" : "Run Suite"}
          </button>
          <div aria-live="polite" className="w-full">
            {error && <p className="text-breach text-[11px]">{error}</p>}
          </div>
        </Panel>

        <Loaded resource={runs}>
          {(rows) =>
            rows.length === 0 ? (
              <Panel>
                <EmptyState
                  title="No suite has been run"
                  body="Run the offline suite to record a baseline for agent behaviour."
                />
              </Panel>
            ) : (
              <div className="space-y-4">
                {rows.map((run) => (
                  <RunPanel key={run.id} run={run} />
                ))}
              </div>
            )
          }
        </Loaded>
      </div>
    </Shell>
  );
}

function RunPanel({ run }: { run: EvalRun }) {
  const total = run.passed + run.failed;
  const byCategory = new Map<string, EvalRun["cases"]>();
  for (const testCase of run.cases) {
    const existing = byCategory.get(testCase.category) ?? [];
    existing.push(testCase);
    byCategory.set(testCase.category, existing);
  }

  return (
    <Panel>
      <PanelHeader
        eyebrow={`${humanise(run.suite)} suite · ${formatTimestamp(run.started_at)}`}
        title={`${run.passed} of ${total} cases passed`}
        action={<Verdict status={run.status} />}
      />
      <PanelBody className="space-y-4">
        {/* Every case as one tick, failures in red — the shape of the run at a glance. */}
        <div className="flex flex-wrap gap-1">
          {run.cases.map((testCase) => (
            <span
              key={testCase.case_name}
              title={`${testCase.case_name}: ${testCase.passed ? "passed" : "failed"}`}
              className={cn("h-6 w-1.5 rounded-full", testCase.passed ? "bg-verified" : "bg-breach")}
            />
          ))}
        </div>

        {run.cases.length === 0 ? (
          <p className="text-ink-faint text-[11px]">
            This run recorded totals but no individual cases.
          </p>
        ) : (
          [...byCategory.entries()].map(([category, cases]) => (
            <div key={category}>
              <p className="eyebrow mb-2">
                {humanise(category)}{" "}
                <span className="text-ink-faint">
                  ({cases.filter((testCase) => testCase.passed).length}/{cases.length})
                </span>
              </p>
              <ul className="space-y-1.5">
                {cases.map((testCase) => (
                  <li key={testCase.case_name} className="flex items-baseline gap-2 text-xs">
                    <Verdict
                      label={testCase.passed ? "Pass" : "Fail"}
                      tone={testCase.passed ? "verified" : "breach"}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="font-medium">{humanise(testCase.case_name)}</span>
                      {testCase.detail && (
                        <span className="text-ink-dim block text-[11px] leading-4">{testCase.detail}</span>
                      )}
                    </span>
                    <span className="ident text-ink-faint shrink-0 text-[11px]">
                      {formatNumber(testCase.score * 100, 0)}%
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
      </PanelBody>
    </Panel>
  );
}
