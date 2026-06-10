import { defineConfig, devices } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(currentDir, '..');

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is required for Playwright smoke tests`);
  }
  return value;
}

function resolveBackendCommand() {
  if (process.env.FA_WEB_SMOKE_BACKEND_CMD) {
    return process.env.FA_WEB_SMOKE_BACKEND_CMD;
  }

  const backendHost = requiredEnv('FA_WEB_SMOKE_BACKEND_HOST');
  const backendPort = requiredEnv('FA_WEB_SMOKE_BACKEND_PORT');
  const unixVenvPython = path.join(repoRoot, '.venv', 'bin', 'python');
  if (fs.existsSync(unixVenvPython)) {
    return `${unixVenvPython} main.py --webui-only --host ${backendHost} --port ${backendPort}`;
  }

  const windowsVenvPython = path.join(repoRoot, '.venv', 'Scripts', 'python.exe');
  if (fs.existsSync(windowsVenvPython)) {
    return `"${windowsVenvPython}" main.py --webui-only --host ${backendHost} --port ${backendPort}`;
  }

  return `python main.py --webui-only --host ${backendHost} --port ${backendPort}`;
}

const backendUrl = requiredEnv('FA_WEB_SMOKE_BACKEND_URL');
const frontendHost = requiredEnv('FA_WEB_SMOKE_FRONTEND_HOST');
const frontendPort = requiredEnv('FA_WEB_SMOKE_FRONTEND_PORT');
const frontendUrl = requiredEnv('FA_WEB_SMOKE_FRONTEND_URL');

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  reporter: 'list',
  use: {
    baseURL: frontendUrl,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: [
    {
      command: resolveBackendCommand(),
      cwd: repoRoot,
      url: backendUrl,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --host ${frontendHost} --port ${frontendPort}`,
      cwd: currentDir,
      url: frontendUrl,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
