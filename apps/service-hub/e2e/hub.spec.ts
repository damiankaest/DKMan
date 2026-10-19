import { expect, test } from '@playwright/test';

// Deliberate browser component integration. This is NOT a live Keycloak login test.
test('renders a signed-out hub on desktop and mobile', async ({ page }) => {
  await page.route('**/src/auth.ts', route => route.fulfill({
    contentType: 'text/javascript',
    body: 'export async function initializeAuth() { return { authenticated: false, login: async()=>{}, logout:async()=>{}, token:async()=>{throw Error("not logged in")} }; }',
  }));
  await page.route('**/health/ready', route => route.fulfill({
    json: { status: 'healthy', database: 'ready', schema: 'current', checked_at: new Date().toISOString() },
  }));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Dein Hub beginnt mit dir.' })).toBeVisible();
  await expect(page.getByRole('button', { name: /Mit DKMan anmelden/ })).toBeVisible();
  await expect(page.getByText('Core bereit')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath('hub.png'), fullPage: true });
});
