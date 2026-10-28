import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.DKMAN_DISPOSABLE_DOCKER_TEST !== '1', 'Requires a disposable CI stack');

test('real OIDC user builds, previews, approves and updates a Forge app', async ({browser}) => {
  test.setTimeout(1_200_000);
  const accounts = JSON.parse(readFileSync('../../.local/ci-users.json','utf8')) as Record<string,string>;
  const adminContext = await browser.newContext();
  const outsiderContext = await browser.newContext();
  const admin = await adminContext.newPage();
  const outsider = await outsiderContext.newPage();
  let authorization = '';
  admin.on('request', request => {const token = request.headers().authorization; if (token?.startsWith('Bearer ')) authorization = token;});
  async function login(page: Page, name: string) {
    await page.goto('/');
    await page.getByRole('button',{name:/Mit DKMan anmelden/}).click();
    await page.locator('#username').fill(name);
    await page.locator('#password').fill(accounts[name]);
    await page.locator('#kc-login').click();
    await expect(page.getByRole('heading',{name:`Hallo, ${name}.`})).toBeVisible({timeout:30_000});
  }
  await login(admin,'ci-admin');
  await login(outsider,'ci-outsider');
  // Earlier browser journeys share the same rate limiter. Drain its burst before mutations.
  await new Promise(resolve => setTimeout(resolve, 7000));
  const notesId = readFileSync('../../.local/notes-installation.txt','utf8').trim();
  function notesContainers() {
    const ids = execFileSync('docker',['ps','--all','--filter',`label=io.dkman.installation=${notesId}`,'--format','{{.ID}}'],{encoding:'utf8'}).trim().split(/\s+/).filter(Boolean);
    expect(ids).toHaveLength(2);
    return ids.map(id => {
      const item = JSON.parse(execFileSync('docker',['container','inspect',id],{encoding:'utf8'}))[0];
      return {id:item.Id,image:item.Image,started:item.State.StartedAt,volumes:item.Mounts.filter((mount:{Type:string}) => mount.Type === 'volume').map((mount:{Name:string}) => mount.Name).sort()};
    }).sort((left,right) => left.id.localeCompare(right.id));
  }
  const notesBefore = notesContainers();
  async function api(path: string, method = 'GET', data?: unknown) {
    expect(authorization).toMatch(/^Bearer /);
    // Pace requests proactively; never retry an execution or approval mutation.
    await new Promise(resolve => setTimeout(resolve, 200));
    const response = await admin.request.fetch(`http://localhost:8080/api/v1${path}`,{
      method, data, headers:{Authorization:authorization,'Idempotency-Key':crypto.randomUUID()}, timeout:420_000,
    });
    expect(response.status(), `${method} ${path}`).toBeLessThan(400);
    return response.json();
  }
  async function approve(job: {id:string}) {
    const binding = await api(`/jobs/${job.id}/approval`);
    const {subject,action,resource_type,resource_id,plan_hash,expires_at} = binding;
    await api(`/approvals/${binding.id}/decision`,'POST',{subject,action,resource_type,resource_id,plan_hash,expires_at,decision:'approve'});
    return api(`/jobs/${job.id}/run`,'POST');
  }
  async function build(plan: {id:string;content_hash:string}) {
    const workspace = await api(`/app-plans/${plan.id}/workspaces`,'POST',{template:'react-spa',content_hash:plan.content_hash});
    // The bearer token is sent on stdin only and never written to the evidence file.
    const output = execFileSync('uv',['run','python','tests/forge_journey_worker.py',workspace.id],{
      cwd:'../..',input:authorization.slice('Bearer '.length),encoding:'utf8',timeout:600_000,
    });
    return JSON.parse(output) as {preview_id:string;build_id:string};
  }
  const home = await api('/households','POST',{name:'Forge CI household'});
  const requirements = {title:'Forge CI App',goal:'Prüfbare Starter-App',features:['Startseite'],entities:[],screens:['Übersicht'],acceptance_checks:['Anmeldung funktioniert'],deployment_requirements:[]};
  const request = await api('/app-requests','POST',{household_id:home.id,requirements});
  const initial = (await api(`/app-requests/${request.id}/plans`))[0];
  const review = await api(`/app-plans/${initial.id}/approve`,'POST',{content_hash:initial.content_hash});
  expect((await approve(review)).state).toBe('succeeded');
  const first = await build(initial);
  const install = await api(`/forge/previews/${first.preview_id}/installations`,'POST',{household_id:home.id});
  expect(install.state).toBe('waiting_approval');
  expect((await approve(install)).state).toBe('succeeded');
  const path = `/run/${install.resource_id}/`;
  await admin.goto('/');
  const card = admin.getByRole('article').filter({has:admin.getByRole('heading',{name:'Forge CI App'})});
  await expect(card.getByRole('link',{name:'App öffnen ↗'})).toHaveAttribute('href',path,{timeout:45_000});
  await card.getByRole('link',{name:'App öffnen ↗'}).click();
  await expect(admin.getByRole('status')).toContainText('Angemeldet und freigegeben',{timeout:45_000});
  expect(notesContainers()).toEqual(notesBefore);
  await outsider.goto(path);
  await expect(outsider.getByRole('status')).toContainText('App-Zugriff konnte nicht bestätigt werden',{timeout:45_000});
  // Reload the hub to refresh the captured admin token before the second real build.
  await admin.goto('/');
  await expect(admin.getByRole('heading',{name:'Hallo, ci-admin.'})).toBeVisible();
  const revised = await api(`/app-requests/${request.id}/plans`,'POST',{
    expected_revision:1,requirements:{...requirements,features:['Startseite','Kalender']},
  });
  const revisionReview = await api(`/app-plans/${revised.id}/approve`,'POST',{content_hash:revised.content_hash});
  expect((await approve(revisionReview)).state).toBe('succeeded');
  const second = await build(revised);
  const update = await api(`/forge/previews/${second.preview_id}/upgrades`,'POST',{installation_id:install.resource_id});
  expect(update.state).toBe('waiting_approval');
  const outcome = await approve(update);
  expect(outcome.state).toBe('succeeded');
  expect(outcome.result.evidence_kind).toBe('engine_acknowledgement');
  await admin.goto('/');
  const updated = admin.getByRole('article').filter({has:admin.getByRole('heading',{name:'Forge CI App'})});
  await expect(updated).toContainText(`Version ${update.plan.replacement.version}`,{timeout:45_000});
  await updated.getByRole('link',{name:'App öffnen ↗'}).click();
  await expect(admin.getByRole('status')).toContainText('Angemeldet und freigegeben',{timeout:45_000});
  expect(notesContainers()).toEqual(notesBefore);
  writeFileSync('../../.local/forge-journey.json',JSON.stringify({request_id:request.id,installation_id:install.resource_id,install_job:install.id,update_job:update.id,builds:[first.build_id,second.build_id],update_state:outcome.state,outsider_denied:true,other_app_unchanged:true},null,2));
  await adminContext.close();await outsiderContext.close();
});
