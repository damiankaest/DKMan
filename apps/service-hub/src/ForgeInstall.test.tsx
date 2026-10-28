import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { ForgeInstall } from './ForgeInstall';
import type { components } from './generated/api';

afterEach(() => vi.unstubAllGlobals());

it('requires an explicit preview review before approving the bound installation', async () => {
  const preview = {id:'preview-1',artifact_id:'build-1',evidence:{expires_at:new Date(Date.now()+300_000).toISOString()}} as components['schemas']['PreviewView'];
  const plan = {image:`sha256:${'a'.repeat(64)}`,profile:'forge-spa-v1',memory_mb:256,cpus:0.5,context:{household_id:'home'},forge:{preview:{evidence:{preview_id:preview.id}}}};
  let state = 'waiting_approval';
  const job = () => ({id:'job-1',action:'deployment.install',requested_by:'admin',state,plan,plan_hash:'c'.repeat(64)});
  const approval = {id:'approval-1',subject:'admin',action:'deployment.install',resource_type:'app_installation',resource_id:'installation-1',plan_hash:'c'.repeat(64),expires_at:new Date(Date.now()+300_000).toISOString()};
  const fetcher = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const path = String(input); const method = init?.method ?? 'GET';
    if (path.endsWith('/households')) return new Response(JSON.stringify([{id:'home',name:'Zuhause'}]));
    if (path.endsWith('/jobs')) return new Response('[]');
    if (path.endsWith('/runtime/installations')) return new Response('[]');
    if (path.endsWith('/installations') && method === 'POST') return new Response(JSON.stringify(job()));
    if (path.endsWith('/approval')) return new Response(JSON.stringify(approval));
    if (path.endsWith('/decision')) {state='queued'; return new Response(JSON.stringify(approval));}
    if (path.endsWith('/run')) {state='succeeded'; return new Response(JSON.stringify(job()));}
    if (path.endsWith('/jobs/job-1')) return new Response(JSON.stringify(job()));
    return new Response('',{status:404});
  });
  vi.stubGlobal('fetch', fetcher);
  const api = new ApiClient({authenticated:true,token:async () => 'test',login:async () => {},logout:async () => {}});
  render(<ForgeInstall api={api} preview={preview} current subject="admin" />);
  fireEvent.click(screen.getByRole('button',{name:'Installation vorbereiten'}));
  const household = await screen.findByLabelText('Haushalt');
  await screen.findByRole('option',{name:'Zuhause'});
  fireEvent.change(household,{target:{value:'home'}});
  fireEvent.click(screen.getByRole('button',{name:'Installationsplan erstellen'}));
  const approve = await screen.findByRole('button',{name:'Diesen Plan freigeben'});
  expect(approve).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox',{name:/Ich habe diese Vorschau geprüft/}));
  fireEvent.click(approve);
  fireEvent.click(await screen.findByRole('button',{name:'Jetzt installieren'}));
  expect(await screen.findByText(/Die App ist installiert/)).toBeVisible();
  expect(fetcher.mock.calls.some(([path]) => String(path).includes('/forge/previews/preview-1/installations'))).toBe(true);
});

it('offers an approved revision update for the existing installation', async () => {
  const preview = {id:'preview-2',artifact_id:'build-2',evidence:{expires_at:new Date(Date.now()+300_000).toISOString()}} as components['schemas']['PreviewView'];
  const replacement = {image:`sha256:${'b'.repeat(64)}`,version:'0.2.1',profile:'forge-spa-v1',memory_mb:256,cpus:0.5,context:{household_id:'home'},forge:{preview:{evidence:{preview_id:preview.id}}}};
  const plan = {previous:{version:'0.1.1'},replacement};
  let state = 'waiting_approval';
  const job = () => ({id:'job-2',action:'deployment.upgrade',requested_by:'admin',state,plan,plan_hash:'d'.repeat(64)});
  const approval = {id:'approval-2',subject:'admin',action:'deployment.upgrade',resource_type:'app_installation',resource_id:'installation-1',plan_hash:'d'.repeat(64),expires_at:new Date(Date.now()+300_000).toISOString()};
  const fetcher = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const path = String(input); const method = init?.method ?? 'GET';
    if (path.endsWith('/households')) return new Response(JSON.stringify([{id:'home',name:'Zuhause'}]));
    if (path.endsWith('/jobs')) return new Response('[]');
    if (path.endsWith('/runtime/installations')) return new Response(JSON.stringify([{id:'installation-1',definition_id:'forge-1234',household_id:'home',name:'Garten'}]));
    if (path.endsWith('/upgrades') && method === 'POST') return new Response(JSON.stringify(job()));
    if (path.endsWith('/approval')) return new Response(JSON.stringify(approval));
    if (path.endsWith('/decision')) {state='queued'; return new Response(JSON.stringify(approval));}
    if (path.endsWith('/run')) {state='succeeded'; return new Response(JSON.stringify(job()));}
    if (path.endsWith('/jobs/job-2')) return new Response(JSON.stringify(job()));
    return new Response('',{status:404});
  });
  vi.stubGlobal('fetch', fetcher);
  const api = new ApiClient({authenticated:true,token:async () => 'test',login:async () => {},logout:async () => {}});
  render(<ForgeInstall api={api} preview={preview} requestId="12-34" current subject="admin" />);
  fireEvent.click(screen.getByRole('button',{name:'Installation vorbereiten'}));
  fireEvent.click(await screen.findByRole('button',{name:'Update-Plan erstellen'}));
  expect(await screen.findByText('0.1.1')).toBeVisible();
  const approve = screen.getByRole('button',{name:'Diesen Plan freigeben'});
  expect(approve).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox',{name:/dieses Update frei/}));
  fireEvent.click(approve);
  fireEvent.click(await screen.findByRole('button',{name:'Jetzt aktualisieren'}));
  expect(await screen.findByText(/App wurde auf die neue Version aktualisiert/)).toBeVisible();
  expect(fetcher.mock.calls.some(([path]) => String(path).includes('/forge/previews/preview-2/upgrades'))).toBe(true);
});
