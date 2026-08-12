"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart3,
  BookOpen,
  Boxes,
  Building2,
  CheckSquare,
  FileSearch,
  FlaskConical,
  GitPullRequest,
  Landmark,
  type LucideIcon,
  Menu,
  MessageSquare,
  PackageSearch,
  RefreshCw,
  ShieldCheck,
  Users,
  Wrench,
} from "lucide-react";
import { AgentChatSidebar } from "@/components/AgentChatSidebar";
import { useAgentChat } from "@/components/AgentChatProvider";
import { useAuth } from "@/components/AuthProvider";
import { cn } from "@/lib/utils";

/**
 * The application shell.
 *
 * Two changes of substance from what this replaced. The navigation was fifteen
 * flat entries, which is a wall rather than a menu; it is now grouped by the
 * function a person came to do. And the agent rail held a permanent 22rem of
 * every screen, crowding the engineering data that is the actual subject — it
 * now docks only on very wide displays and is a drawer everywhere else.
 */

type NavItem = { href: string; label: string; icon: LucideIcon; warm?: string };
type NavGroup = { group: string; items: NavItem[] };

const NAVIGATION: NavGroup[] = [
  {
    group: "Engineering",
    items: [
      { href: "/pdm", label: "Product data", icon: Boxes, warm: "/api/parts/ECL-SYS-1000/bom?bom_type=MBOM" },
      { href: "/ecm", label: "Engineering change", icon: GitPullRequest, warm: "/api/ecm/requests" },
      { href: "/knowledge", label: "Knowledge", icon: BookOpen, warm: "/api/knowledge/ingestion" },
    ],
  },
  {
    group: "Quality",
    items: [
      { href: "/qms", label: "Units & tests", icon: FlaskConical, warm: "/api/qms/ECL-M-104" },
      { href: "/assets", label: "Lab assets", icon: Wrench, warm: "/api/assets/calibration" },
    ],
  },
  {
    group: "Supply",
    items: [
      { href: "/procurement", label: "Procurement", icon: PackageSearch, warm: "/api/procurement/stock-risk" },
      { href: "/crm", label: "Customers", icon: Building2, warm: "/api/crm/opportunities" },
    ],
  },
  {
    group: "Business",
    items: [
      { href: "/controlling", label: "Controlling", icon: BarChart3, warm: "/api/controlling/rollup/ECL-SYS-1000?batch_size=10" },
      { href: "/programs", label: "Programmes", icon: Landmark, warm: "/api/programs/trl" },
      { href: "/resources", label: "Resourcing", icon: Users, warm: "/api/resources/capacity" },
    ],
  },
  {
    group: "Agents & control",
    items: [
      { href: "/approval-inbox", label: "Approvals", icon: CheckSquare, warm: "/api/proposals?status=pending" },
      { href: "/agent-runs", label: "Agent runs", icon: Activity, warm: "/api/agent-runs" },
      { href: "/evals", label: "Evaluations", icon: ShieldCheck, warm: "/api/evals" },
      { href: "/audit", label: "Audit trail", icon: FileSearch, warm: "/api/audit" },
    ],
  },
];

/** Matches Tailwind's 2xl. Below this the agent rail would crowd the data. */
function useDockedAgent() {
  const [docked, setDocked] = React.useState(false);
  React.useEffect(() => {
    const query = window.matchMedia("(min-width: 1536px)");
    const sync = () => setDocked(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);
  return docked;
}

export function Shell({
  children,
  ...title
}: TitleBlockProps & { children: React.ReactNode }) {
  const docked = useDockedAgent();
  const [navOpen, setNavOpen] = React.useState(false);
  const [agentOpen, setAgentOpen] = React.useState(false);
  const agentVisible = docked || agentOpen;
  const { reset: resetAgentChat } = useAgentChat();

  /*
   * Reloading the view is the one deliberate "start again" gesture on the
   * screen, so it starts the conversation again too. Everything else — above
   * all moving between sections — leaves the thread alone, because checking an
   * answer somewhere else is the reason to have asked it.
   */
  const pageRefresh = title.onRefresh;
  const onRefresh = React.useMemo(
    () =>
      pageRefresh
        ? () => {
            resetAgentChat();
            pageRefresh();
          }
        : undefined,
    [pageRefresh, resetAgentChat],
  );

  return (
    <div
      className={cn(
        "grid h-dvh grid-cols-1 overflow-hidden",
        "lg:grid-cols-[14rem_minmax(0,1fr)]",
        docked && "2xl:grid-cols-[14rem_minmax(0,1fr)_23rem]",
      )}
    >
      {/* Docked navigation. */}
      <div className="hidden lg:block">
        <NavRail />
      </div>

      {/* Navigation drawer, below lg. */}
      {navOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setNavOpen(false)}
            className="absolute inset-0 bg-black/50"
          />
          <div className="absolute inset-y-0 left-0 w-64 overscroll-contain">
            <NavRail onNavigate={() => setNavOpen(false)} />
          </div>
        </div>
      )}

      <main id="work-surface" className="min-w-0 overflow-y-auto">
        <TitleBlock
          {...title}
          onRefresh={onRefresh}
          onOpenNav={() => setNavOpen(true)}
          onToggleAgent={docked ? undefined : () => setAgentOpen((open) => !open)}
        />
        <div className="p-4 sm:p-6">{children}</div>
      </main>

      {/* Agent rail: docked at 2xl, drawer below. */}
      {docked ? (
        <div className="hidden min-h-0 overflow-hidden 2xl:block">
          <AgentChatSidebar />
        </div>
      ) : (
        agentVisible && (
          <div className="fixed inset-0 z-40">
            <button
              type="button"
              aria-label="Close agent"
              onClick={() => setAgentOpen(false)}
              className="absolute inset-0 bg-black/50"
            />
            <div className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col overflow-hidden overscroll-contain">
              <AgentChatSidebar onClose={() => setAgentOpen(false)} />
            </div>
          </div>
        )
      )}
    </div>
  );
}

function NavRail({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  const { prefetch } = useAuth();

  return (
    <nav
      aria-label="Sections"
      className="bg-rail border-rule flex h-full flex-col border-r"
    >
      <Link
        href="/"
        onClick={onNavigate}
        className="border-rule hover:bg-sunken flex items-center gap-2.5 border-b px-4 py-3.5 transition-colors"
      >
        <Coil />
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold tracking-tight">
            Magnotherm
          </span>
          <span className="text-ink-faint block truncate text-[10px]">
            Engineering operations
          </span>
        </span>
      </Link>

      <div className="flex-1 overflow-y-auto overscroll-contain py-2">
        <ul className="px-2 pb-2">
          <NavLink
            item={{ href: "/", label: "Overview", icon: Landmark, warm: "/api/showcase" }}
            active={path === "/"}
            onNavigate={onNavigate}
            prefetch={prefetch}
          />
        </ul>
        {NAVIGATION.map(({ group, items }) => (
          <div key={group} className="border-rule border-t pt-2.5">
            <p className="eyebrow px-4 pb-1.5">{group}</p>
            <ul className="px-2 pb-2">
              {items.map((item) => (
                <NavLink
                  key={item.href}
                  item={item}
                  active={path.startsWith(item.href)}
                  onNavigate={onNavigate}
                  prefetch={prefetch}
                />
              ))}
            </ul>
          </div>
        ))}
      </div>

      <p className="border-rule text-ink-faint border-t px-4 py-3 text-[10px] leading-4">
        Synthetic records. Public product facts only.
      </p>
    </nav>
  );
}

function NavLink({
  item,
  active,
  onNavigate,
  prefetch,
}: {
  item: NavItem;
  active: boolean;
  onNavigate?: () => void;
  prefetch: (path: string) => void;
}) {
  const Icon = item.icon;
  return (
    <li>
      <Link
        href={item.href}
        onClick={onNavigate}
        onMouseEnter={() => item.warm && prefetch(item.warm)}
        onFocus={() => item.warm && prefetch(item.warm)}
        aria-current={active ? "page" : undefined}
        className={cn(
          "rounded-chip relative flex items-center gap-2.5 px-2.5 py-1.5 text-[13px] transition-colors",
          active
            ? "bg-cold-wash text-cold font-semibold"
            : "text-ink-dim hover:bg-sunken hover:text-ink",
        )}
      >
        {active && (
          <span className="bg-cold absolute inset-y-1 left-0 w-0.5 rounded-full" aria-hidden="true" />
        )}
        <Icon className="size-3.5 shrink-0" aria-hidden="true" />
        <span className="truncate">{item.label}</span>
      </Link>
    </li>
  );
}

/**
 * The mark: a regenerator between two poles. Drawn rather than imported,
 * because a generic snowflake said "cold" and nothing else about this machine.
 */
function Coil() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="size-6 shrink-0"
      aria-hidden="true"
      fill="none"
      strokeWidth="1.75"
      strokeLinecap="round"
    >
      <rect x="2.5" y="5" width="4" height="14" rx="1" className="stroke-cold" />
      <rect x="17.5" y="5" width="4" height="14" rx="1" className="stroke-warm" />
      <path d="M9.5 8.5h5M9.5 12h5M9.5 15.5h5" className="stroke-ink-dim" />
    </svg>
  );
}

export interface TitleBlockProps {
  /** The domain classification — the drawing frame's zone label. */
  eyebrow: string;
  title: string;
  /** What this screen is for, in one line. */
  summary: string;
  /** Fixed cells on the right, like a drawing's title block. */
  cells?: Array<{ label: string; value: React.ReactNode }>;
  onRefresh?: () => void;
  refreshing?: boolean;
}

function TitleBlock({
  eyebrow,
  title,
  summary,
  cells = [],
  onRefresh,
  refreshing,
  onOpenNav,
  onToggleAgent,
}: TitleBlockProps & { onOpenNav: () => void; onToggleAgent?: () => void }) {
  const { user, logout } = useAuth();

  return (
    <header className="bg-panel/85 border-rule sticky top-0 z-20 border-b backdrop-blur">
      <div className="flex items-start gap-3 px-4 py-3 sm:px-6">
        <button
          type="button"
          onClick={onOpenNav}
          aria-label="Open navigation"
          className="border-rule rounded-chip hover:bg-sunken -ml-1 mt-0.5 border p-1.5 transition-colors lg:hidden"
        >
          <Menu className="size-4" aria-hidden="true" />
        </button>

        <div className="min-w-0 flex-1">
          <p className="eyebrow">{eyebrow}</p>
          <h1 className="mt-1 truncate text-lg font-semibold tracking-tight">{title}</h1>
          <p className="text-ink-dim mt-0.5 text-pretty text-xs leading-5">{summary}</p>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          {onRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              aria-label="Reload this view"
              className="border-rule rounded-chip hover:bg-sunken border p-1.5 transition-colors"
            >
              <RefreshCw
                className={cn("size-3.5", refreshing && "animate-spin")}
                aria-hidden="true"
              />
            </button>
          )}
          {onToggleAgent && (
            <button
              type="button"
              onClick={onToggleAgent}
              aria-label="Open the agent"
              className="border-rule rounded-chip hover:bg-sunken border p-1.5 transition-colors"
            >
              <MessageSquare className="size-3.5" aria-hidden="true" />
            </button>
          )}
          <button
            type="button"
            onClick={() => void logout()}
            className="border-rule rounded-chip hover:bg-sunken hidden max-w-[14rem] truncate border px-2.5 py-1.5 text-xs transition-colors sm:block"
            title={`Sign out ${user?.email ?? ""}`}
          >
            {user?.full_name?.split(" — ")[0] ?? user?.email ?? "Sign out"}
          </button>
        </div>
      </div>

      {cells.length > 0 && (
        <dl className="border-rule tick-rule flex divide-x divide-[var(--rule)] overflow-x-auto border-t bg-[length:8px_1px] bg-repeat-x">
          {cells.map((cell) => (
            <div key={cell.label} className="min-w-0 shrink-0 px-4 py-2 sm:px-6">
              <dt className="eyebrow">{cell.label}</dt>
              <dd className="ident mt-1 whitespace-nowrap text-sm font-semibold">
                {cell.value}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </header>
  );
}
