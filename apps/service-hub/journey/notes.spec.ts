import { expect, test, type Page } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.DKMAN_DISPOSABLE_DOCKER_TEST !== '1', 'Requires an explicitly disposable real stack');

test('real OIDC, approved installation and operator lifecycle with unchanged Notes and revoked access', async ({browser}) => {
  const accounts = JSON.parse(readFileSync('../../.local/ci-users.json','utf8')) as Record<string,string>;
  async function login(page: Page, name: string) {
    await page.goto('/');
    await page.getByRole('button',{name:/Mit DKMan anmelden/}).click();
    await page.locator('#username').fill(name);
    await page.locator('#password').fill(accounts[name]);
    await page.locator('#kc-login').click();
    await expect(page.getByRole('heading',{name:`Hallo, ${name}.`})).toBeVisible({timeout:30_000});
  }
  const adminContext = await browser.newContext();
  const memberContext = await browser.newContext();
  const outsiderContext = await browser.newContext();
  const admin = await adminContext.newPage();
  const member = await memberContext.newPage();
  const outsider = await outsiderContext.newPage();
  for (const page of [admin, member, outsider]) page.on('response', response => {
    if (response.url().includes('/api/') && response.status() >= 400) console.log(`API status ${response.status()} ${new URL(response.url()).pathname}`);
  });
  await login(admin,'ci-admin'); await login(member,'ci-member'); await login(outsider,'ci-outsider');
  await admin.getByRole('button',{name:'Verwaltung',exact:true}).click();
  const access = admin.getByRole('region',{name:'Haushalte und Freigaben'});
  const deployment = admin.getByRole('region',{name:'App installieren'});
  await access.getByLabel('Neuer Haushalt').fill('Journey household');
  const creation = admin.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/households' && response.request().method() === 'POST');
  await access.getByRole('button',{name:'Haushalt erstellen'}).click();
  expect((await creation).status()).toBe(201);
  await expect(access.getByLabel('Haushalt',{exact:true}).locator('option').filter({hasText:'Journey household'})).toHaveCount(1);
  await deployment.getByRole('button',{name:'Stand neu laden'}).click();
  await deployment.getByLabel('Haushalt',{exact:true}).selectOption({label:'Journey household'});
  await deployment.getByRole('button',{name:'Plan erstellen'}).click();
  await expect(deployment.getByRole('heading',{name:/Wartet auf Freigabe/})).toBeVisible();
  await expect(deployment.getByRole('button',{name:'Diesen Plan freigeben'})).toBeDisabled();
  await deployment.getByRole('checkbox').check();
  await deployment.getByRole('button',{name:'Diesen Plan freigeben'}).click();
  const execution = admin.waitForResponse(response => /\/api\/v1\/jobs\/[^/]+\/run$/.test(new URL(response.url()).pathname), {timeout:120_000});
  await deployment.getByRole('button',{name:'Jetzt installieren'}).click();
  const executed = await execution;
  expect(executed.status()).toBe(200);
  expect((await executed.json()).state).toBe('succeeded');
  await expect(deployment.getByRole('heading',{name:/Installiert · Notes/})).toBeVisible({timeout:120_000});
  await access.getByLabel('Haushalt',{exact:true}).selectOption({label:'Journey household'});
  const memberRow = access.locator('li').filter({hasText:'ci-member'}).first();
  await memberRow.getByRole('button',{name:'Mitglied hinzufügen'}).click();
  await expect(memberRow.getByRole('button',{name:'Mitglied entfernen'})).toBeEnabled();
  await access.getByLabel('Installation',{exact:true}).selectOption({index:1});
  const grantRow = access.locator('li').filter({hasText:'ci-member'}).last();
  await grantRow.getByRole('button',{name:'App freigeben'}).click();
  await expect(grantRow.getByRole('button',{name:'Freigabe entziehen'})).toBeEnabled();
  await admin.getByRole('button',{name:'Meine Apps',exact:true}).click();
  const route = await admin.getByRole('link',{name:'App öffnen ↗'}).getAttribute('href');
  expect(route).toMatch(/^\/run\/[a-f0-9-]+\/$/);
  await admin.getByRole('link',{name:'App öffnen ↗'}).click();
  await expect(admin.getByRole('heading',{name:'Unsere Notizen.'})).toBeVisible();
  await expect(admin.getByLabel('Neue Notiz')).toBeVisible({timeout:30_000});
  const content = 'Gemeinsame echte Notes-Probe <script>kein HTML</script>';
  await admin.getByLabel('Neue Notiz').fill(content);
  await admin.getByRole('button',{name:'Notiz speichern'}).click();
  await expect(admin.locator('article')).toContainText(content);
  await member.goto(route!);
  await expect(member.getByLabel('Neue Notiz')).toBeVisible({timeout:30_000});
  await expect(member.locator('article')).toContainText(content);
  await member.getByLabel('Neue Notiz').fill('Notiz vom zweiten Nutzer');
  await member.getByRole('button',{name:'Notiz speichern'}).click();
  await expect(member.locator('article')).toHaveCount(2);
  await outsider.goto(route!);
  await expect(outsider.locator('#status')).toContainText('fehlgeschlagen',{timeout:30_000});
  await expect(outsider.locator('article')).toHaveCount(0);
  // Snapshot actual IDs, authors, texts and timestamps through the authenticated Notes API.
  async function notesSnapshot() {
    const reading = member.waitForResponse(response => response.url().endsWith('/api/notes') && response.request().method() === 'GET');
    await member.goto(route!);
    const response = await reading;
    expect(response.status()).toBe(200);
    return response.json();
  }
  const baseline = await notesSnapshot();
  expect(baseline).toHaveLength(2);
  const id = route!.split('/')[2];
  function engineEvidence(phase: string) {
    console.log(execFileSync('python3',['../../tests/verify_notes_lifecycle.py',id,phase],{encoding:'utf8'}).trim());
  }
  engineEvidence('before');
  // Member has operator role and app.use, but still no runtime scope.
  await member.goto('/');
  await expect(member.getByRole('heading',{name:'Hallo, ci-member.'})).toBeVisible({timeout:30_000});
  await member.getByRole('button',{name:'Verwaltung',exact:true}).click();
  await expect(member.getByRole('region',{name:'Runtime verwalten'})).toContainText('Keine für deinen Runtimebetrieb');
  await expect(member.getByRole('button',{name:'Container stoppen'})).toHaveCount(0);
  await admin.goto('/');
  await expect(admin.getByRole('heading',{name:'Hallo, ci-admin.'})).toBeVisible({timeout:30_000});
  await admin.getByRole('button',{name:'Verwaltung',exact:true}).click();
  await access.getByLabel('Haushalt',{exact:true}).selectOption({label:'Journey household'});
  await access.getByLabel('Installation',{exact:true}).selectOption({index:1});
  await grantRow.getByRole('button',{name:'Runtimebetrieb freigeben'}).click();
  await expect(grantRow.getByRole('button',{name:'Betriebsfreigabe entziehen'})).toBeEnabled();
  const lifecycleJobs: unknown[] = [];
  for (const action of ['stop','start','restart'] as const) {
    await member.goto('/');
    await expect(member.getByRole('heading',{name:'Hallo, ci-member.'})).toBeVisible({timeout:30_000});
    await member.getByRole('button',{name:'Verwaltung',exact:true}).click();
    const runtime = member.getByRole('region',{name:'Runtime verwalten'});
    const label = {stop:'Container stoppen',start:'Container starten',restart:'Container neu starten'}[action];
    await expect(runtime.getByRole('button',{name:label,exact:true})).toBeEnabled();
    await runtime.getByRole('button',{name:label,exact:true}).click();
    await expect(runtime.getByRole('button',{name:'Runtimeplan freigeben'})).toBeDisabled();
    if (action === 'stop') {
      // Full browser reload must recover the server-persisted pending plan.
      await member.reload();
      await expect(member.getByRole('heading',{name:'Hallo, ci-member.'})).toBeVisible({timeout:30_000});
      await expect(member.getByRole('link',{name:'App öffnen ↗'})).toHaveCount(0);
      await member.getByRole('button',{name:'Verwaltung',exact:true}).click();
      await expect(runtime.getByRole('button',{name:'Runtimeplan freigeben'})).toBeDisabled();
    }
    await runtime.getByRole('checkbox').check();
    await runtime.getByRole('button',{name:'Runtimeplan freigeben'}).click();
    const execution = member.waitForResponse(response => /\/api\/v1\/jobs\/[^/]+\/run$/.test(new URL(response.url()).pathname), {timeout:120_000});
    await runtime.getByRole('button',{name:'Runtimeaktion ausführen'}).click();
    const response = await execution;
    expect(response.status()).toBe(200);
    const completed = await response.json();
    expect(completed.state).toBe('succeeded');
    expect(completed.result.state).toBe(action === 'stop' ? 'stopped' : 'running');
    lifecycleJobs.push(completed);
    await expect(runtime.getByRole('heading',{name:/Erfolgreich abgeschlossen/})).toBeVisible();
    engineEvidence(action);
    await runtime.getByRole('button',{name:'Logs anzeigen'}).click();
    await expect(runtime.getByLabel('Runtime-Logs')).toBeVisible();
    if (action === 'stop') {
      await member.getByRole('button',{name:'Meine Apps',exact:true}).click();
      await expect(member.getByRole('link',{name:'App öffnen ↗'})).toHaveCount(0);
    } else {
      expect(await notesSnapshot()).toEqual(baseline);
    }
  }
  writeFileSync('../../.local/notes-lifecycle-jobs.json',JSON.stringify(lifecycleJobs,null,2));
  // Revoke only operator scope; app.use still works, runtime controls disappear.
  await grantRow.getByRole('button',{name:'Betriebsfreigabe entziehen'}).click();
  await expect(grantRow.getByRole('button',{name:'Runtimebetrieb freigeben'})).toBeEnabled();
  await member.goto('/');
  await expect(member.getByRole('heading',{name:'Hallo, ci-member.'})).toBeVisible({timeout:30_000});
  await member.getByRole('button',{name:'Verwaltung',exact:true}).click();
  await expect(member.getByRole('region',{name:'Runtime verwalten'})).toContainText('Keine für deinen Runtimebetrieb');
  expect(await notesSnapshot()).toEqual(baseline);
  admin.once('dialog', dialog => dialog.accept());
  await memberRow.getByRole('button',{name:'Mitglied entfernen'}).click();
  await expect(memberRow.getByRole('button',{name:'Mitglied hinzufügen'})).toBeEnabled();
  await member.reload();
  await expect(member.locator('#status')).toContainText('fehlgeschlagen',{timeout:30_000});
  await expect(member.locator('article')).toHaveCount(0);
  // Return installation ID without credentials for the container persistence probe.
  writeFileSync('../../.local/notes-installation.txt',id);
  console.log(`Verified real Notes installation ${id}`);
  await adminContext.close(); await memberContext.close(); await outsiderContext.close();
});
