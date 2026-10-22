import { expect, test } from '@playwright/test';

// Browser component integration with explicit HTTP/auth fixtures, separate from the live journey.
test('creates and reads a planning draft without overflow on desktop and mobile', async ({page}) => {
  await page.route('**/src/auth.ts', route => route.fulfill({contentType:'text/javascript',body:'export async function initializeAuth(){return{authenticated:true,login:async()=>{},logout:async()=>{},token:async()=>"browser-test-token"}}'}));
  await page.route('**/health/ready', route => route.fulfill({json:{status:'healthy',database:'ready',schema:'current',checked_at:'2026-10-22T10:00:00Z'}}));
  let request: Record<string,unknown> | null = null;
  let plan: Record<string,unknown> | null = null;
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (path === '/api/v1/me') body = {subject:'alice',display_name:'Alice',roles:['admin']};
    else if (path === '/api/v1/me/profile') body = {id:'alice',subject:'alice',display_name:'Alice'};
    else if (path === '/api/v1/app-requests' && route.request().method() === 'POST') {
      const input = route.request().postDataJSON();
      expect(route.request().headers()['idempotency-key']).toBeTruthy();
      request = {id:'request-1',title:input.requirements.title,household_id:null,requested_by:'alice',current_revision:1,created_at:'2026-10-22T10:00:00Z',updated_at:'2026-10-22T10:00:00Z'};
      plan = {id:'plan-1',request_id:'request-1',revision:1,document:{schema_version:1,planning_mode:'manual',household_id:null,requirements:input.requirements},content_hash:'a'.repeat(64),created_by:'alice',created_at:'2026-10-22T10:00:00Z',approved_job_id:null};
      body = request;
    } else if (path === '/api/v1/app-requests') body = request ? [request] : [];
    else if (path === '/api/v1/app-requests/request-1') body = request;
    else if (path === '/api/v1/app-requests/request-1/plans') body = plan ? [plan] : [];
    else if (['/api/v1/apps','/api/v1/catalog','/api/v1/households','/api/v1/app-plans/plan-1/jobs'].includes(path)) body = [];
    else throw new Error(`Unexpected browser fixture route ${path}`);
    await route.fulfill({status:path === '/api/v1/app-requests' && route.request().method() === 'POST' ? 201 : 200,json:body});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'App planen',exact:true}).click();
  await page.getByLabel('Name der App').fill('Unser Garten');
  await page.getByLabel('Was soll die App erreichen?').fill('Pflanzen, Fotos und gemeinsame Aufgaben an einem Ort.');
  await page.getByLabel('Funktionen',{exact:true}).fill('Pflanzen verwalten\nGießen planen\nFotos sammeln');
  await page.getByLabel('Daten und Entitäten',{exact:true}).fill('Pflanze\nPflegeaufgabe');
  await page.getByLabel('Ansichten',{exact:true}).fill('Pflanzenübersicht\nKalender');
  await page.getByLabel('Abnahmekriterien',{exact:true}).fill('Pflanzen bleiben nach einem Neustart erhalten');
  await page.getByRole('button',{name:'App-Idee speichern'}).click();
  await expect(page.getByRole('article',{name:'Gespeicherter App-Plan'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Freigabe vorbereiten'})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath('planning.png'),fullPage:true});
  await page.getByRole('article',{name:'Gespeicherter App-Plan'}).scrollIntoViewIfNeeded();
  await page.screenshot({path:test.info().outputPath('planning-detail.png')});
});
