import { defineConfig } from "@playwright/test";

const localChrome = process.env.PLAYWRIGHT_CHROME_PATH;

export default defineConfig({
  testDir: "./tests/e2e",
  use: {
    baseURL: "http://localhost:3001",
    launchOptions: localChrome ? { executablePath: localChrome } : undefined,
  },
  webServer: {
    command: "npm run dev -- --port 3001",
    url: "http://localhost:3001",
    reuseExistingServer: true,
  },
});
