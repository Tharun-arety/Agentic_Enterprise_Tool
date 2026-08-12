import { defineConfig } from "@playwright/test";

const localChrome = process.env.PLAYWRIGHT_CHROME_PATH;

/**
 * Point the suites at a deployed origin to smoke-test it:
 *
 *   PLAYWRIGHT_BASE_URL=https://agentic-enterprise-tool.vercel.app npx playwright test
 *
 * The local dev server is only started when no origin is supplied, so a remote
 * run neither needs nor waits for one.
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3001";
const isRemote = Boolean(process.env.PLAYWRIGHT_BASE_URL);

export default defineConfig({
  testDir: "./tests/e2e",
  use: {
    baseURL,
    launchOptions: localChrome ? { executablePath: localChrome } : undefined,
  },
  /*
   * Two projects, because the suites want different things.
   *
   * `behaviour` is what you run by default. `visual` walks all seventeen
   * routes and writes a full-page image of each — a design-review tool whose
   * coverage duplicates `ui-health`, and which on its own pushes the API close
   * to its 120-requests-a-minute limit. Running both together tips it over and
   * fails the run on a 429, so they are kept apart:
   *
   *   npx playwright test                       the behavioural suites
   *   npx playwright test --project=visual      the image sweep
   */
  projects: [
    { name: "behaviour", grepInvert: /@visual/ },
    { name: "visual", grep: /@visual/ },
  ],
  webServer: isRemote
    ? undefined
    : {
        command: "npm run dev -- --port 3001",
        url: "http://localhost:3001",
        reuseExistingServer: true,
      },
});
