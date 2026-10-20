import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './journey', workers: 1, timeout: 240_000,
  use: {baseURL: 'http://localhost:8080', trace: 'off', screenshot: 'off'},
});
