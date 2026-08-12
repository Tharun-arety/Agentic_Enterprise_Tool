import { expect, test } from "@playwright/test";

/**
 * The quality seat's route through the evidence thread: the lot arrives, the
 * unit that got it fails acceptance, the change board acts, the cost moves and
 * the notice becomes searchable.
 *
 * This asserts on the records themselves rather than on headings, so it fails
 * if the story stops hanging together — which is the only thing worth testing
 * about a demo dataset.
 */
test.setTimeout(3 * 60_000);

test("the quality seat can follow the evidence from lot to change notice", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /^Quality/ }).click();
  await expect(page.getByRole("navigation", { name: "Sections" })).toBeVisible();

  // The failed article, its breach, and the lot it was built from.
  await page.goto("/qms?serial=ECL-M-097");
  await expect(page.getByRole("heading", { name: /ECL-M-097/ })).toBeVisible();
  await expect(page.getByText("2 fail").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("MAG-L-2312").first()).toBeVisible();
  await expect(page.getByText("NCR-26-001").first()).toBeVisible();

  // The change board reached quorum on the corrective request.
  await page.goto("/ecm");
  await expect(page.getByText("ECR-26-002").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("4 of 4 seats voted")).toBeVisible();

  // The notice the release wrote is retrievable from the corpus.
  await page.goto("/knowledge?q=thermally%20stabilised%20magnet");
  await expect(page.getByText("ECN-26-001").first()).toBeVisible({ timeout: 30_000 });
});
