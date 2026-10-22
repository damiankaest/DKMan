import { expect, test, type Page } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';

test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.DKMAN_DISPOSABLE_DOCKER_TEST !== '1', 'Requires an explicitly disposable real stack');

test('real OIDC chat searches, reviews and persists a draft, isolates jobs and only proposes installation', async ({browser}) => {
  const accounts = JSON.parse(readFileSync('../../.local/ci-users.json','utf8')) as Record<string,string>;
  const adminContext = await browser.newContext();const memberContext = await browser.newContext();const outsiderContext = await browser.newContext();
  const admin = await adminContext.newPage();const member = await memberContext.newPage();const outsider = await outsiderContext.newPage();
  const authorizations = new Map<Page,string>();
  for (const page of [admin,member,outsider]) page.on('request', request => {
    const value = request.headers()['authorization'];if (value?.startsWith('Bearer ')) authorizations.set(page,value);
  });
  async function api(page: Page, path: string, method = 'GET') {
    const authorization = authorizations.get(page);expect(authorization).toBeTruthy();
    return page.request.fetch(`http://localhost:8080/api/v1${path}`,{method,headers:{Authorization:authorization!}});
  }
  async function login(page: Page, name: string) {
    await page.goto('/');await page.getByRole('button',{name:/Mit DKMan anmelden/}).click();
    await page.locator('#username').fill(name);await page.locator('#password').fill(accounts[name]);await page.locator('#kc-login').click();
    await expect(page.getByRole('heading',{name:`Hallo, ${name}.`})).toBeVisible({timeout:30_000});
  }
  async function send(page: Page, message: string) {
    const response = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/chat' && response.request().method() === 'POST');
    await page.getByLabel('Dein Auftrag').fill(message);await page.getByRole('button',{name:'Senden',exact:true}).click();return response;
  }
  await login(member,'ci-member');await login(admin,'ci-admin');await login(outsider,'ci-outsider');
  const requestsBefore = await (await api(member,'/app-requests')).json();
  await member.getByRole('button',{name:'DKMan Chat',exact:true}).click();
  await expect(member.getByText('Regelbasierter Modus',{exact:true})).toBeVisible();
  const draft = await send(member,'Plane eine Garten-App mit Pflanzen und Fotos');
  expect(draft.status()).toBe(200);expect((await draft.json()).provider.mode).toBe('rules');
  expect((await (await api(member,'/app-requests')).json()).length).toBe(requestsBefore.length);
  await member.getByRole('button',{name:'Entwurf in App-Planung prüfen'}).click();
  await expect(member.getByLabel('Funktionen',{exact:true})).toHaveValue('Pflanzen\nFotos');
  await member.getByLabel('Name der App').fill('Chat-Garten');
  const saved = member.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/app-requests' && response.request().method() === 'POST');
  await member.getByRole('button',{name:'App-Idee speichern'}).click();const request = await (await saved).json();
  await expect(member.getByRole('article',{name:'Gespeicherter App-Plan'})).toBeVisible();
  await member.reload();await member.getByRole('button',{name:'App planen',exact:true}).click();
  await member.getByRole('button',{name:/Chat-Garten.*Version 1/}).click();
  await expect(member.getByLabel('Funktionen',{exact:true})).toHaveValue('Pflanzen\nFotos');
  await admin.getByRole('button',{name:'App planen',exact:true}).click();await admin.getByRole('button',{name:/Chat-Garten.*Version 1/}).click();
  const prepared = admin.waitForResponse(response => /\/api\/v1\/app-plans\/[^/]+\/approve$/.test(new URL(response.url()).pathname));
  await admin.getByRole('button',{name:'Freigabe vorbereiten'}).click();const job = await (await prepared).json();
  expect(job.state).toBe('waiting_approval');
  const jobsBefore = await (await api(admin,'/jobs?limit=100')).json();
  const appsBefore = await (await api(admin,'/apps')).json();
  await admin.getByRole('button',{name:'DKMan Chat',exact:true}).click();
  const status = await send(admin,`Job ${job.id}`);const statusBody = await status.json();
  expect(statusBody.jobs[0].state).toBe('waiting_approval');expect(statusBody.jobs[0].events.length).toBeGreaterThan(0);
  expect(statusBody.jobs[0].plan).toBeUndefined();
  await expect(admin.getByRole('heading',{name:'Wartet auf Freigabe · app_plan.approve'})).toBeVisible();
  const registry = await send(admin,'Suche Dienste Notes');expect((await registry.json()).registry.some((item:{id:string}) => item.id === 'demo-notes')).toBe(true);
  const install = await send(admin,'Installiere Notes');expect((await install.json()).proposal.definition_id).toBe('demo-notes');
  await admin.getByRole('button',{name:'Installation planen',exact:true}).click();
  await expect(admin.getByLabel('App',{exact:true})).toHaveValue('demo-notes');
  expect((await (await api(admin,'/jobs?limit=100')).json()).map((item:{id:string}) => item.id)).toEqual(jobsBefore.map((item:{id:string}) => item.id));
  expect((await (await api(admin,'/apps')).json()).map((item:{id:string}) => item.id)).toEqual(appsBefore.map((item:{id:string}) => item.id));
  await outsider.getByRole('button',{name:'DKMan Chat',exact:true}).click();
  expect((await send(outsider,`Job ${job.id}`)).status()).toBe(404);
  expect((await api(outsider,`/app-requests/${request.id}`)).status()).toBe(404);
  const hidden = await send(outsider,'Suche Dienste');expect((await hidden.json()).registry).toEqual([]);
  expect((await api(admin,`/jobs/${job.id}/cancel`,'POST')).status()).toBe(200);
  await admin.getByRole('button',{name:'DKMan Chat',exact:true}).click();
  const cancelled = await send(admin,`Job ${job.id}`);expect((await cancelled.json()).jobs[0].state).toBe('cancelled');
  writeFileSync('../../.local/chat-journey.json',JSON.stringify({mode:'rules',request_id:request.id,job_id:job.id,initial_state:'waiting_approval',final_state:'cancelled',outsider_status:404,reviewed_draft_persisted:true,chat_did_not_create_jobs_or_installations:true,curated_installation_proposal:'demo-notes'},null,2));
  await adminContext.close();await memberContext.close();await outsiderContext.close();
});
