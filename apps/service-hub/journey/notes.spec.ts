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
  const rateLimitErrors: string[] = [];
  const authorizations = new Map<Page,string>();
  for (const page of [admin, member, outsider]) page.on('request', request => {
    const token = request.headers()['authorization'];
    if (token?.startsWith('Bearer ')) authorizations.set(page,token);
  });
  async function api(page: Page, path: string, method = 'GET', data?: unknown) {
    const authorization = authorizations.get(page);
    expect(authorization).toBeTruthy();
    return page.request.fetch(`http://localhost:8080${path}`,{method,
      headers:{Authorization:authorization!,'Idempotency-Key':crypto.randomUUID()}, data});
  }
  for (const page of [admin, member, outsider]) page.on('response', response => {
    if (response.status() === 429) rateLimitErrors.push(new URL(response.url()).pathname);
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
  const faultResults: Record<string,unknown> = {};
  function fault(action: string, operation?: string) {
    console.log(execFileSync('python3',['../../tests/notes_faults.py',action,id,...(operation ? [operation] : [])],{encoding:'utf8',timeout:65_000}).trim());
  }
  // Actual bearer tokens came from the browser's real PKCE login, never from password grant.
  faultResults.operator_without_scope = (await api(member,`/api/v1/installations/${id}/stop`,'POST',{})).status();
  expect(faultResults.operator_without_scope).toBe(404);
  faultResults.member_without_role = (await api(outsider,`/api/v1/installations/${id}/logs`)).status();
  expect(faultResults.member_without_role).toBe(403);
  faultResults.free_image_payload = (await api(admin,'/api/v1/deployments/installations','POST',
    {definition_id:'demo-notes',household_id:crypto.randomUUID(),image:'untrusted:latest'})).status();
  expect(faultResults.free_image_payload).toBe(422);
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
  // Real database outages: metadata remains queued, app data is unavailable safely.
  fault('notes-db-stop');
  const unavailableNotes = await api(member,`${route}api/notes`);
  expect(unavailableNotes.status()).toBe(503);
  expect(await unavailableNotes.json()).toEqual({detail:'Notes database unavailable'});
  const downStatus = await api(admin,`/api/v1/installations/${id}/status`);
  expect((await downStatus.json()).state).toBe('unhealthy');
  const hidden = await api(admin,'/api/v1/apps');
  expect((await hidden.json()).find((app: {id:string}) => app.id === id).route).toBeNull();
  faultResults.notes_database_down = {status:unavailableNotes.status(),runtime:'unhealthy'};
  fault('notes-db-start');
  expect(await notesSnapshot()).toEqual(baseline);

  await member.goto('/');
  await expect(member.getByRole('heading',{name:'Hallo, ci-member.'})).toBeVisible({timeout:30_000});
  await member.getByRole('button',{name:'Verwaltung',exact:true}).click();
  const recoveryRuntime = member.getByRole('region',{name:'Runtime verwalten'});
  async function approvedRestart() {
    await expect(recoveryRuntime.getByRole('button',{name:'Container neu starten',exact:true})).toBeEnabled();
    const planned = member.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith(`/${id}/restart`));
    await recoveryRuntime.getByRole('button',{name:'Container neu starten',exact:true}).click();
    const plannedJob = await (await planned).json();
    await recoveryRuntime.getByRole('checkbox').check();
    await recoveryRuntime.getByRole('button',{name:'Runtimeplan freigeben'}).click();
    await expect(recoveryRuntime.getByRole('button',{name:'Runtimeaktion ausführen'})).toBeEnabled();
    return plannedJob;
  }
  const databaseJob = await approvedRestart();
  fault('core-db-stop');
  const duringOutage = await api(member,`/api/v1/jobs/${databaseJob.id}/run`,'POST');
  expect(duringOutage.status()).toBe(503);
  expect((await member.request.get('http://localhost:8080/health/live')).status()).toBe(200);
  expect((await member.request.get('http://localhost:8080/health/ready')).status()).toBe(503);
  fault('core-db-start');
  await expect.poll(async () => (await member.request.get('http://localhost:8080/health/ready')).status()).toBe(200);
  expect((await (await api(member,`/api/v1/jobs/${databaseJob.id}`)).json()).state).toBe('queued');
  faultResults.core_database_down = {status:duringOutage.status(),job_after_recovery:'queued'};
  // The approved command was never dispatched during the outage; execute it once now.
  const afterDatabase = member.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/jobs/${databaseJob.id}/run`);
  await recoveryRuntime.getByRole('button',{name:'Runtimeaktion ausführen'}).click();
  expect((await (await afterDatabase).json()).state).toBe('succeeded');

  // Kill the real adapter after the Engine receipt commit, before its final result commit.
  const recoverable = await approvedRestart();
  fault('after_receipt',recoverable.id);
  const lost = member.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/jobs/${recoverable.id}/run`);
  await recoveryRuntime.getByRole('button',{name:'Runtimeaktion ausführen'}).click();
  expect((await (await lost).json()).state).toBe('reconciliation_required');
  fault('adapter-ready');
  await member.reload();
  await expect(member.getByRole('heading',{name:'Hallo, ci-member.'})).toBeVisible({timeout:30_000});
  await expect(member.getByRole('link',{name:'App öffnen ↗'})).toHaveCount(0);
  await member.getByRole('button',{name:'Verwaltung',exact:true}).click();
  const reconciled = member.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/jobs/${recoverable.id}/reconcile`);
  await recoveryRuntime.getByRole('button',{name:'Runtimeergebnis abgleichen'}).click();
  const completedRecovery = await (await reconciled).json();
  expect(completedRecovery.state).toBe('succeeded');
  expect(completedRecovery.result.evidence_kind).toBe('engine_acknowledgement');
  expect(completedRecovery.result.evidence_hash).toMatch(/^[a-f0-9]{64}$/);
  await expect(recoveryRuntime.getByText(completedRecovery.result.evidence_hash,{exact:true})).toBeVisible();
  faultResults.acknowledged_crash = completedRecovery;
  engineEvidence('reconciled_restart');
  expect(await notesSnapshot()).toEqual(baseline);

  // The same actual restart without a durable acknowledgement stays quarantined.
  await member.goto('/');
  await expect(member.getByRole('heading',{name:'Hallo, ci-member.'})).toBeVisible({timeout:30_000});
  await member.getByRole('button',{name:'Verwaltung',exact:true}).click();
  const ambiguous = await approvedRestart();
  fault('before_receipt',ambiguous.id);
  const interrupted = member.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/jobs/${ambiguous.id}/run`);
  await recoveryRuntime.getByRole('button',{name:'Runtimeaktion ausführen'}).click();
  expect((await (await interrupted).json()).state).toBe('reconciliation_required');
  fault('adapter-ready');
  engineEvidence('unproven_restart');
  const unresolved = member.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/jobs/${ambiguous.id}/reconcile`);
  await recoveryRuntime.getByRole('button',{name:'Runtimeergebnis abgleichen'}).click();
  const unresolvedJob = await (await unresolved).json();
  expect(unresolvedJob.state).toBe('reconciliation_required');
  expect(unresolvedJob.failure_code).toBe('execution_receipt_missing');
  expect((await api(member,`/api/v1/installations/${id}/stop`,'POST',{})).status()).toBe(409);
  const observedAmbiguity = await api(member,`/api/v1/installations/${id}/status`);
  expect((await observedAmbiguity.json()).blocked_job_id).toBe(ambiguous.id);
  engineEvidence('after_reconcile');
  faultResults.unacknowledged_crash = unresolvedJob;
  writeFileSync('../../.local/notes-fault-results.json',JSON.stringify(faultResults,null,2));
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
  expect(rateLimitErrors).toEqual([]);
  console.log(`Verified real Notes installation ${id}`);
  await adminContext.close(); await memberContext.close(); await outsiderContext.close();
});
