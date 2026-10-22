import { expect, test } from '@playwright/test';

// Explicit browser fixtures. The independent chat journey uses actual OIDC and Core.
test('reviews a chat draft before saving and retains the transcript on desktop and mobile', async ({page}) => {
  const provider = {mode:'rules',label:'Regelbasierter Modus',notice:'Kein LLM verbunden. Jede Nachricht wird einzeln mit festen Regeln ausgewertet.'};
  const requirements = {title:'Garten-App',goal:'Pflanzen gemeinsam pflegen',features:['Pflanzen','Fotos'],entities:[],screens:[],acceptance_checks:[],deployment_requirements:[]};
  await page.route('**/src/auth.ts', route => route.fulfill({contentType:'text/javascript',body:'export async function initializeAuth(){return{authenticated:true,login:async()=>{},logout:async()=>{},token:async()=>"test-only"}}'}));
  await page.route('**/health/ready', route => route.fulfill({json:{status:'healthy',database:'ready',schema:'current',checked_at:new Date().toISOString()}}));
  let saved: Record<string,unknown> | null = null;
  let plan: Record<string,unknown> | null = null;
  const mutations: string[] = [];
  await page.route('**/api/v1/**', async route => {
    const request = route.request();const path = new URL(request.url()).pathname;
    let body: unknown;
    if (request.method() === 'POST') mutations.push(path);
    if (path === '/api/v1/me') body = {subject:'alice',display_name:'Alice',roles:['member']};
    else if (path === '/api/v1/me/profile') body = {id:'alice'};
    else if (path === '/api/v1/chat/config') body = provider;
    else if (path === '/api/v1/chat') body = {provider,intent:'app.draft',summary:'Bitte prüfe den Entwurf in der App-Planung.',observed_at:new Date().toISOString(),proposal:{kind:'app.draft',requirements}};
    else if (path === '/api/v1/app-requests' && request.method() === 'POST') {
      const input = request.postDataJSON();expect(request.headers()['idempotency-key']).toBeTruthy();
      saved = {id:'chat-request',title:input.requirements.title,current_revision:1,requested_by:'alice',household_id:null,created_at:new Date().toISOString(),updated_at:new Date().toISOString()};
      plan = {id:'chat-plan',request_id:'chat-request',revision:1,document:{schema_version:1,planning_mode:'manual',household_id:null,requirements:input.requirements},content_hash:'a'.repeat(64),created_by:'alice',created_at:new Date().toISOString(),approved_job_id:null};body = saved;
    } else if (path === '/api/v1/app-requests') body = saved ? [saved] : [];
    else if (path === '/api/v1/app-requests/chat-request') body = saved;
    else if (path === '/api/v1/app-requests/chat-request/plans') body = [plan];
    else if (['/api/v1/apps','/api/v1/households'].includes(path)) body = [];
    else throw new Error(`Unexpected fixture path ${path}`);
    await route.fulfill({status:path === '/api/v1/app-requests' && request.method() === 'POST' ? 201 : 200,json:body});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'DKMan Chat',exact:true}).click();
  await expect(page.getByText('Regelbasierter Modus',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Plane eine Garten-App mit Pflanzen und Fotos',exact:true}).click();
  await expect(page.getByRole('button',{name:'Entwurf in App-Planung prüfen'})).toBeVisible();
  expect(mutations).toEqual(['/api/v1/chat']);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath('chat.png'),fullPage:true});
  await page.getByRole('button',{name:'Entwurf in App-Planung prüfen'}).click();
  await expect(page.getByLabel('Name der App')).toHaveValue('Garten-App');
  await expect(page.getByLabel('Funktionen',{exact:true})).toHaveValue('Pflanzen\nFotos');
  await page.getByLabel('Name der App').fill('Unser Garten aus dem Chat');
  await page.getByRole('button',{name:'App-Idee speichern'}).click();
  await expect(page.getByRole('article',{name:'Gespeicherter App-Plan'})).toBeVisible();
  expect(mutations).toEqual(['/api/v1/chat','/api/v1/app-requests']);
  await page.getByRole('button',{name:'DKMan Chat',exact:true}).click();
  await expect(page.getByText('Bitte prüfe den Entwurf in der App-Planung.')).toBeVisible();
});
