import { expect, test } from "@playwright/test";

/**
 * Every section reachable from the sidebar, driven the way a person drives it —
 * by clicking the navigation rather than by re-entering URLs.
 */
const SECTIONS = [
  "Product data",
  "Engineering change",
  "Knowledge",
  "Units & tests",
  "Lab assets",
  "Procurement",
  "Customers",
  "Controlling",
  "Programmes",
  "Resourcing",
  "Approvals",
  "Agent runs",
  "Evaluations",
  "Audit trail",
];

test.setTimeout(3 * 60_000);

test("admin can load every section without a client error", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("/");
  await page.getByRole("button", { name: /^Admin/ }).click();

  // Sign-in is a round trip to Postgres, which is slower than the 5s default
  // expectation window when the database is cold.
  const sidebar = page.getByRole("navigation", { name: "Sections" });
  await expect(sidebar).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: /ECLIPSE/ })).toBeVisible();

  // The overview's evidence chain is the product thesis; if these references
  // stop appearing the seed has drifted away from the story it tells.
  await expect(page.getByText("GR-2026-0018")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("MAG-L-2312").first()).toBeVisible();
  await expect(page.getByText("ECR-26-002").first()).toBeVisible();

  for (const section of SECTIONS) {
    await sidebar.getByRole("link", { name: section, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator(".animate-pulse")).toHaveCount(0, { timeout: 20_000 });
    // No view should be reporting a failed read. Scoped to the work surface:
    // the Next.js dev overlay mounts an empty `role="alert"` of its own.
    await expect(page.locator("#work-surface").getByRole("alert")).toHaveCount(0);
  }

  expect(errors).toEqual([]);
});
