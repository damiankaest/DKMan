import { expect, test, type Page } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';

test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.DKMAN_DISPOSABLE_DOCKER_TEST !== '1', 'Requires an explicitly disposable real stack');

test('real planning persists revisions, isolates people and records approval without deployment', async ({browser}) => {
  const accounts = JSON.parse(readFileSync('../../.local/ci-users.json','utf8')) as Record<string,string>;
  const adminContext = await browser.newContext();
  const memberContext = await browser.newContext();
  const outsiderContext = await browser.newContext();
  const admin = await adminContext.newPage();
  const member = await memberContext.newPage();
  const outsider = await outsiderContext.newPage();
  const authorizations = new Map<Page,string>();
  for (const page of [admin,member,outsider]) page.on('request', request => {
    const value = request.headers()['authorization'];
    if (value?.startsWith('Bearer ')) authorizations.set(page,value);
  });
  async function api(page: Page, path: string) {
    const authorization = authorizations.get(page);
    expect(authorization).toBeTruthy();
    return page.request.get(`http://localhost:8080/api/v1${path}`,{headers:{Authorization:authorization!}});
  }
  async function login(page: Page, name: string) {
    await page.goto('/');
    await page.getByRole('button',{name:/Mit DKMan anmelden/}).click();
    await page.locator('#username').fill(name);
    await page.locator('#password').fill(accounts[name]);
    await page.locator('#kc-login').click();
    await expect(page.getByRole('heading',{name:`Hallo, ${name}.`})).toBeVisible({timeout:30_000});
  }
  await login(member,'ci-member');await login(admin,'ci-admin');await login(outsider,'ci-outsider');
  const installationsBefore = await (await api(admin,'/apps')).json();
  await member.getByRole('button',{name:'App planen',exact:true}).click();
  await member.getByLabel('Name der App').fill('Unser Garten');
  await member.getByLabel('Was soll die App erreichen?').fill('Pflanzen im Haushalt gemeinsam pflegen');
  await member.getByLabel('Funktionen',{exact:true}).fill('Pflanzen verwalten\nGießen planen');
  await member.getByLabel('Daten und Entitäten',{exact:true}).fill('Pflanze\nAufgabe');
  await member.getByLabel('Abnahmekriterien',{exact:true}).fill('Neue Pflanzen bleiben nach einem Neustart erhalten');
  const saved = member.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/app-requests' && response.request().method() === 'POST');
  await member.getByRole('button',{name:'App-Idee speichern'}).click();
  const response = await saved;
  expect(response.status()).toBe(201);
  const request = await response.json();
  await expect(member.getByRole('article',{name:'Gespeicherter App-Plan'})).toBeVisible();
  await expect(member.getByRole('button',{name:'Freigabe vorbereiten'})).toHaveCount(0);
  const initial = (await (await api(member,`/app-requests/${request.id}/plans`)).json())[0];
  await member.reload();
  await member.getByRole('button',{name:'App planen',exact:true}).click();
  await member.getByRole('button',{name:/Unser Garten.*Version 1/}).click();
  await expect(member.getByLabel('Funktionen',{exact:true})).toHaveValue('Pflanzen verwalten\nGießen planen');
  await admin.getByRole('button',{name:'App planen',exact:true}).click();
  await admin.getByRole('button',{name:/Unser Garten.*Version 1/}).click();
  await admin.getByRole('button',{name:'Freigabe vorbereiten'}).click();
  await expect(admin.getByRole('button',{name:'Planversion freigeben'})).toBeDisabled();
  await admin.getByRole('checkbox').check();
  await admin.getByRole('button',{name:'Planversion freigeben'}).click();
  const executed = admin.waitForResponse(response => /\/api\/v1\/jobs\/[^/]+\/run$/.test(new URL(response.url()).pathname));
  await admin.getByRole('button',{name:'Freigabe abschließen'}).click();
  const job = await (await executed).json();
  expect(job.state).toBe('succeeded');expect(job.result.effect).toBe('plan_recorded');
  expect(job.result.content_hash).toBe(initial.content_hash);
  await expect(admin.getByText('Planversion freigegeben',{exact:true})).toBeVisible();
  const installationsAfter = await (await api(admin,'/apps')).json();
  expect(installationsAfter.map((item:{id:string}) => item.id).sort()).toEqual(installationsBefore.map((item:{id:string}) => item.id).sort());
  await member.getByLabel('Funktionen',{exact:true}).fill('Pflanzen verwalten\nGießen planen\nKalender');
  await member.getByRole('button',{name:'Neue Planversion speichern'}).click();
  await expect(member.getByRole('option',{name:'Version 2',exact:true})).toHaveCount(1);
  await member.getByLabel('Planversion',{exact:true}).selectOption(initial.id);
  await expect(member.getByText('Frühere Version',{exact:true})).toBeVisible();
  const versions = await (await api(member,`/app-requests/${request.id}/plans`)).json();
  expect(versions.map((plan:{revision:number}) => plan.revision)).toEqual([2,1]);
  expect(versions[0].approved_job_id).toBeNull();expect(versions[1].approved_job_id).toBe(job.id);
  expect(versions[1].document).toEqual(initial.document);
  expect((await api(outsider,`/app-requests/${request.id}`)).status()).toBe(404);
  expect((await api(outsider,`/app-plans/${initial.id}`)).status()).toBe(404);
  writeFileSync('../../.local/planning-journey.json',JSON.stringify({request_id:request.id,job_id:job.id,state:job.state,result:job.result,versions:versions.map((plan:{id:string;revision:number;content_hash:string;approved_job_id:string|null}) => ({id:plan.id,revision:plan.revision,content_hash:plan.content_hash,approved_job_id:plan.approved_job_id})),outsider_status:404,unchanged_installations:true},null,2));
  await adminContext.close();await memberContext.close();await outsiderContext.close();
});
