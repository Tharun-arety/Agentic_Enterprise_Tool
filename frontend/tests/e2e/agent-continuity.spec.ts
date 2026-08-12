import { expect, test } from "@playwright/test";

/**
 * The agent rail is a place to ask a question and then go and check the answer.
 * Checking it means changing section, so the thread has to survive that — it
 * used to be thrown away the moment the route changed, taking the question with
 * it. Clearing is deliberate: the reload control, or the panel's own button.
 */
test.setTimeout(3 * 60_000);

// Wide enough that the rail docks rather than opening as a drawer.
test.use({ viewport: { width: 1680, height: 1000 } });

test("the conversation survives changing section and clears only on demand", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /^Admin/ }).click();

  const sidebar = page.getByRole("navigation", { name: "Sections" });
  await expect(sidebar).toBeVisible({ timeout: 30_000 });

  await sidebar.getByRole("link", { name: "Product data", exact: true }).click();
  await expect(page.getByRole("heading", { name: /ECLIPSE/ })).toBeVisible({ timeout: 30_000 });

  const prompt = page.getByRole("textbox", { name: "Ask the engineering agent" });
  const transcript = page.getByTestId("agent-transcript");

  // Ask, and wait for an answer rather than for the request to have been sent.
  // Deliberately not one of the panel's suggestion chips: those come back when
  // the thread is cleared, and would satisfy a "still on screen" assertion.
  const question = "Which revision of the AMR module does the product resolve to?";
  await prompt.fill(question);
  await prompt.press("Enter");
  await expect(transcript.getByText("Agent", { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(transcript.getByText(question)).toBeVisible();

  // The reported defect: verifying the answer elsewhere used to erase it.
  await sidebar.getByRole("link", { name: "Units & tests", exact: true }).click();
  await expect(page).toHaveURL(/\/qms/);
  await expect(transcript.getByText(question)).toBeVisible();
  await expect(prompt).toBeVisible();

  // And the follow-up, asked from the section we moved to.
  const followUp = "And which built units contain it?";
  await prompt.fill(followUp);
  await prompt.press("Enter");
  await expect(transcript.getByText(followUp)).toBeVisible({ timeout: 60_000 });
  await expect(transcript.getByText("Agent", { exact: true })).toHaveCount(2, { timeout: 60_000 });

  // Reloading the view is the gesture that starts again.
  await page.getByRole("button", { name: "Reload this view" }).click();
  await expect(transcript.getByText(question)).toHaveCount(0);
  await expect(transcript.getByText(followUp)).toHaveCount(0);
  await expect(transcript.getByRole("button", { name: /Trace lot MAG-L-2312/ })).toBeVisible();
});

test("a long answer scrolls inside the panel and leaves the composer reachable", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /^Admin/ }).click();
  await expect(page.getByRole("navigation", { name: "Sections" })).toBeVisible({ timeout: 30_000 });

  const prompt = page.getByRole("textbox", { name: "Ask the engineering agent" });
  const transcript = page.getByTestId("agent-transcript");

  await prompt.fill("Trace lot MAG-L-2312 to affected units and quality findings");
  await prompt.press("Enter");
  await expect(transcript.getByText("Agent", { exact: true })).toBeVisible({ timeout: 60_000 });

  // The composer stays on screen however long the answer runs; it used to be
  // pushed out of the panel by a scroll region that grew instead of scrolling.
  await expect(prompt).toBeInViewport();

  // The transcript is its own scrolling region, not the page.
  const overflows = await transcript.evaluate(
    (el) => el.scrollHeight - el.clientHeight,
  );
  if (overflows > 0) {
    await transcript.evaluate((el) => el.scrollTo({ top: 0 }));
    await expect
      .poll(async () => transcript.evaluate((el) => el.scrollTop))
      .toBeLessThan(8);
  }
});
