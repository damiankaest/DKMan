import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { DeploymentAdmin } from './DeploymentAdmin';
import { ApiClient } from './api';

afterEach(() => vi.unstubAllGlobals());

function setup(resume = false, uncertain = false) {
  let state = resume ? 'reconciliation_required' : 'waiting_approval';
  const image = {definition_id:'demo-notes',version:'0.1.0',image:'sha256:'+'a'.repeat(64),database_image:'sha256:'+'b'.repeat(64),source_hash:'c'.repeat(64),memory_mb:128,cpus:0.5};
  const job = () => ({id:'job-1',requested_by:'alice',action:'deployment.install',state,resource_id:'app-1',plan_hash:'f'.repeat(64),plan:{...image,context:{household_id:'home'}},failure_code:null});
  const binding = {id:'approval-1',job_id:'job-1',subject:'alice',action:'deployment.install',resource_type:'app_installation',resource_id:'app-1',plan_hash:'f'.repeat(64),expires_at:'2026-10-20T16:00:00Z',state:'pending'};
  const fetcher = vi.fn(async (path: string, init: RequestInit) => {
    if (path.endsWith('/decision')) {state = 'queued'; return new Response(JSON.stringify(binding));}
    if (path.endsWith('/run')) state = uncertain ? 'reconciliation_required' : 'succeeded';
    if (path.endsWith('/reconcile')) state = 'succeeded';
    const body = path.endsWith('/catalog') ? [image] : path.endsWith('/households') ? [{id:'home',name:'Zuhause'}] : path.endsWith('/jobs') ? (resume ? [job()] : []) : path.endsWith('/approval') ? binding : path.endsWith('/events') ? [] : job();
    return new Response(JSON.stringify(body),{status: init.method === 'POST' && path.endsWith('/installations') ? 202 : 200});
  });
  vi.stubGlobal('fetch',fetcher);
  const api = new ApiClient({authenticated:true,token:async () => 'test-token',login:async () => {},logout:async () => {}});
  const onInstalled = vi.fn();
  render(<DeploymentAdmin api={api} subject="alice" onInstalled={onInstalled} />);
  return {fetcher,onInstalled,binding};
}

it('requires a reviewed plan and sends the exact approval binding before installation',async () => {
  const {fetcher,onInstalled,binding} = setup();
  await screen.findByRole('option',{name:'Zuhause'});
  fireEvent.change(screen.getByLabelText('Haushalt'),{target:{value:'home'}});
  fireEvent.click(screen.getByRole('button',{name:'Plan erstellen'}));
  const approve = await screen.findByRole('button',{name:'Diesen Plan freigeben'});
  expect(approve).toBeDisabled();
  expect(screen.queryByRole('button',{name:'Jetzt installieren'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox'));
  await waitFor(() => expect(approve).toBeEnabled());
  fireEvent.click(approve);
  const install = await screen.findByRole('button',{name:'Jetzt installieren'});
  await waitFor(() => expect(install).toBeEnabled());
  const decision = fetcher.mock.calls.find(([path]) => path.endsWith('/decision'))!;
  expect(JSON.parse(decision[1].body as string)).toEqual({subject:binding.subject,action:binding.action,resource_type:binding.resource_type,resource_id:binding.resource_id,plan_hash:binding.plan_hash,expires_at:binding.expires_at,decision:'approve'});
  const submission = fetcher.mock.calls.find(([path]) => path.endsWith('/installations'))!;
  expect((submission[1].headers as Record<string,string>)['Idempotency-Key']).toBeTruthy();
  fireEvent.click(install);
  await waitFor(() => expect(onInstalled).toHaveBeenCalledOnce());
});

it('resumes an uncertain persisted job and reconciles without another install request',async () => {
  const {fetcher,onInstalled} = setup(true);
  const reconcile = await screen.findByRole('button',{name:'Ergebnis abgleichen'});
  await waitFor(() => expect(reconcile).toBeEnabled());
  fireEvent.click(reconcile);
  await waitFor(() => expect(onInstalled).toHaveBeenCalledOnce());
  expect(fetcher.mock.calls.some(([path]) => path.endsWith('/run') || path.endsWith('/installations'))).toBe(false);
});
