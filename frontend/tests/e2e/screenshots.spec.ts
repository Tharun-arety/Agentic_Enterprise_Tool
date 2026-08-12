import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * A visual pass over every route.
 *
 * Not an assertion suite — its job is to produce one full-page image per
 * screen at a fixed viewport so the design can be reviewed as a set rather
 * than one page at a time. It fails only on a client-side exception or a view
 * that never finishes loading, both of which are worth failing on.
 */

const ROUTES = [
  ["overview", "/"],
  ["pdm-mbom", "/pdm?view=MBOM"],
  ["pdm-ebom", "/pdm?view=EBOM"],
  ["ecm", "/ecm"],
  ["knowledge", "/knowledge"],
  ["qms-failed", "/qms?serial=ECL-M-097"],
  ["qms-passed", "/qms?serial=ECL-M-104"],
  ["assets", "/assets"],
  ["procurement", "/procurement"],
  ["crm", "/crm"],
  ["controlling", "/controlling"],
  ["programs", "/programs"],
  ["resources", "/resources"],
  ["approval-inbox", "/approval-inbox"],
  ["agent-runs", "/agent-runs"],
  ["evals", "/evals"],
  ["audit", "/audit"],
] as const;

test.use({ viewport: { width: 1440, height: 900 } });

// Seventeen routes, each a live round trip to Postgres over the network. The
// default 30s cap is for a single interaction, not a whole sweep.
test.setTimeout(5 * 60_000);

async function signIn(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Admin/ }).click();
  // The sidebar only exists once a session is established, so this is the
  // assertion that actually proves sign-in worked.
  const sidebar = page.getByRole("navigation", { name: "Sections" });
  await expect(sidebar).toBeVisible({ timeout: 30_000 });
  return sidebar;
}

async function settle(page: Page, sidebar: Locator) {
  await expect(sidebar).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  // Skeletons carry `animate-pulse`; none should survive a settled view.
  await expect(page.locator(".animate-pulse")).toHaveCount(0, { timeout: 20_000 });
}

test("every route renders without a client error @visual", async ({ page }, testInfo) => {
  const errors: string[] = [];
  let current = "sign-in";
  page.on("pageerror", (error) => errors.push(`${current}: ${error.message}`));

  const sidebar = await signIn(page);

  for (const [name, route] of ROUTES) {
    current = name;
    // The API allows 120 requests a minute per client. Seventeen routes back
    // to back, each firing several reads plus the sidebar's prefetches, trips
    // that in a way no person clicking through ever would — so pace the sweep
    // rather than loosening a limit that is doing its job.
    await page.waitForTimeout(1_200);
    await page.goto(route);
    await settle(page, sidebar);
    await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: true });
  }

  expect(errors).toEqual([]);
});

/**
 * Dark mode is a designed set of steps against a dark surface, not an
 * automatic inversion of the light one, so it needs looking at rather than
 * assuming. Three routes are enough to catch a token that was only ever
 * checked on paper: the chain, the charts, and the diff tables.
 */
test.describe("dark mode", () => {
  test.use({ colorScheme: "dark" });

  test("renders on the dark surface @visual", async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));

    const sidebar = await signIn(page);

    for (const [name, route] of [
      ["dark-overview", "/"],
      ["dark-qms", "/qms?serial=ECL-M-097"],
      ["dark-approvals", "/approval-inbox"],
    ] as const) {
      await page.waitForTimeout(1_200);
      await page.goto(route);
      await settle(page, sidebar);
      await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: true });
    }

    expect(errors).toEqual([]);
  });
});
