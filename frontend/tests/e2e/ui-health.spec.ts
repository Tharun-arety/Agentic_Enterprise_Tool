import { expect, test } from "@playwright/test";

const sections = ["PDM", "QMS", "Procurement", "CRM", "Programs", "Assets", "Resources", "Controlling", "Knowledge", "ECM", "Agent runs", "Evals", "Audit", "Approvals"];

test("admin can load every enterprise page without client errors", async ({ page }) => {
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));

  await page.goto("/");
  await page.getByLabel("Email").fill("admin@magnotherm.test");
  await page.getByLabel("Password").fill("magnotherm");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("heading", { name: "Engineering operations" }),
  ).toBeVisible();
  await expect(page.getByText("PUBLIC PRODUCT BASELINE · SYNTHETIC OPERATIONS")).toBeVisible();
  await expect(page.getByText("GR-2026-0018")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("MAG-L-2312").first()).toBeVisible();
  await expect(page.getByText("ECR-26-002").first()).toBeVisible();

  for (const section of sections) {
    await page.getByTitle(section).click();
    await expect(page.locator("h1")).toBeVisible();
    await expect(page.locator(".animate-pulse")).toHaveCount(0, { timeout: 15_000 });
    await expect(page.locator(".text-warning")).toHaveCount(0);
  }

  expect(browserErrors).toEqual([]);
});
