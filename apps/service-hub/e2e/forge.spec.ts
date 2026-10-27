import { expect, test } from '@playwright/test';

// Explicit HTTP fixtures exercise the UI; real OIDC remains a separate journey.
test('prepares and downloads an approved plan workspace on desktop and mobile', async ({page}) => {
  await page.route('**/src/auth.ts', route => route.fulfill({contentType:'text/javascript',body:'export async function initializeAuth(){return{authenticated:true,login:async()=>{},logout:async()=>{},token:async()=>"browser-test-token"}}'}));
  await page.route('**/health/ready', route => route.fulfill({json:{status:'healthy',database:'ready',schema:'current',checked_at:'2026-10-27T10:00:00Z'}}));
  const requirements = {title:'Unser Garten',goal:'Pflanzen pflegen',features:['Fotos'],entities:[],screens:[],acceptance_checks:[],deployment_requirements:[]};
  const request = {id:'request-1',title:requirements.title,household_id:null,requested_by:'alice',current_revision:1,created_at:'2026-10-27T10:00:00Z',updated_at:'2026-10-27T10:00:00Z'};
  const plan = {id:'plan-1',request_id:'request-1',revision:1,document:{schema_version:1,planning_mode:'manual',household_id:null,requirements},content_hash:'a'.repeat(64),created_by:'alice',created_at:'2026-10-27T10:00:00Z',approved_job_id:'approved-job'};
  const workspace = {id:'12345678-1234-1234-1234-123456789abc',plan_id:plan.id,plan_hash:plan.content_hash,template:'fullstack-fastapi-react',bundle_hash:'b'.repeat(64),created_at:'2026-10-27T10:00:00Z',files:['backend/app/main.py','plan.json']};
  let saved = false;
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (path === '/api/v1/me') body = {subject:'alice',display_name:'Alice',roles:['admin']};
    else if (path === '/api/v1/me/profile') body = {id:'alice',subject:'alice',display_name:'Alice'};
    else if (path === '/api/v1/app-requests') body = [request];
    else if (path === '/api/v1/app-requests/request-1') body = request;
    else if (path === '/api/v1/app-requests/request-1/plans') body = [plan];
    else if (path === '/api/v1/app-plans/plan-1/workspaces' && route.request().method() === 'POST') {
      expect(route.request().headers()['idempotency-key']).toBeTruthy();
      expect(route.request().postDataJSON()).toEqual({template:'fullstack-fastapi-react',content_hash:plan.content_hash});
      saved = true; body = workspace;
    } else if (path === '/api/v1/app-plans/plan-1/workspaces') body = saved ? [workspace] : [];
    else if (path === `/api/v1/forge/workspaces/${workspace.id}/archive`) {
      expect(route.request().headers().authorization).toBe('Bearer browser-test-token');
      await route.fulfill({contentType:'application/zip',body:'PK-test-archive'}); return;
    } else if (['/api/v1/apps','/api/v1/catalog','/api/v1/households','/api/v1/app-plans/plan-1/jobs'].includes(path)) body = [];
    else throw new Error(`Unexpected browser fixture route ${path}`);
    await route.fulfill({status:path.endsWith('/workspaces') && route.request().method() === 'POST' ? 201 : 200,json:body});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'App planen',exact:true}).click();
  await page.getByRole('button',{name:/Unser Garten.*Version 1/}).click();
  const panel = page.getByRole('region',{name:'App-Quellstände'});
  await panel.getByRole('button',{name:'Quellstände öffnen'}).click();
  await expect(panel.getByRole('button',{name:'Quellstand erstellen'})).toBeEnabled();
  await panel.getByRole('button',{name:'Quellstand erstellen'}).click();
  await expect(panel.getByText(/Quellstand gespeichert/)).toBeVisible();
  const download = page.waitForEvent('download');
  await panel.getByRole('button',{name:'ZIP herunterladen'}).click();
  expect((await download).suggestedFilename()).toBe(`dkman-workspace-${workspace.id}.zip`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath('forge-workspaces.png'),fullPage:true});
  await page.reload();
  await page.getByRole('button',{name:'App planen',exact:true}).click();
  await page.getByRole('button',{name:/Unser Garten.*Version 1/}).click();
  await page.getByRole('button',{name:'Quellstände öffnen'}).click();
  await expect(page.getByRole('button',{name:'ZIP herunterladen'})).toBeVisible();
});
