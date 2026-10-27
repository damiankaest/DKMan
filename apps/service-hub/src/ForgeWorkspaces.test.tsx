import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { ForgeWorkspaces } from './ForgeWorkspaces';
import type { components } from './generated/api';

afterEach(() => vi.unstubAllGlobals());
const plan = {id:'plan-1',content_hash:'a'.repeat(64),approved_job_id:'approval-job'} as components['schemas']['PlanView'];

it('prepares a source snapshot only after explicit creation and binds it to the plan', async () => {
  const fetcher = vi.fn(async (path: string, init: RequestInit) => {
    const data = init.method === 'POST' ? {id:'workspace-1',plan_id:'plan-1',plan_hash:'a'.repeat(64),template:'python-api',bundle_hash:'b'.repeat(64),created_at:'2026-10-27T10:00:00Z',files:['backend/app/main.py']} : [];
    if (!path.startsWith('/api/v1/app-plans/plan-1/workspaces')) throw new Error('Unexpected request');
    return new Response(JSON.stringify(data));
  });
  vi.stubGlobal('fetch', fetcher);
  const api = new ApiClient({authenticated:true,token:async () => 'test',login:async () => {},logout:async () => {}});
  render(<ForgeWorkspaces api={api} plan={plan} current />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Quellstände öffnen'}));
  const button = screen.getByRole('button',{name:'Quellstand erstellen'});
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.change(screen.getByLabelText('Vorlage'),{target:{value:'python-api'}});
  fireEvent.click(button);
  await screen.findByText('Quellstand gespeichert. Du kannst ihn jetzt herunterladen und prüfen.');
  expect(screen.getByText('python-api')).toBeVisible();
  const post = fetcher.mock.calls.find(([,init]) => init.method === 'POST')!;
  expect(JSON.parse(post[1].body as string)).toEqual({template:'python-api',content_hash:'a'.repeat(64)});
  expect((post[1].headers as Record<string,string>)['Idempotency-Key']).toBeTruthy();
  expect(fetcher.mock.calls.every(([path]) => !path.includes('/run') && !path.includes('/approve'))).toBe(true);
});

it('does not enable generation for an old or unapproved revision', async () => {
  const api = new ApiClient({authenticated:true,token:async () => 'test',login:async () => {},logout:async () => {}});
  vi.stubGlobal('fetch', vi.fn(async () => new Response('[]')));
  render(<ForgeWorkspaces api={api} plan={{...plan,approved_job_id:null}} current={false} />);
  fireEvent.click(screen.getByRole('button',{name:'Quellstände öffnen'}));
  await waitFor(() => expect(screen.getByRole('button',{name:'Quellstand erstellen'})).toBeDisabled());
  expect(screen.getByText(/Nur die aktuelle, freigegebene Planversion/)).toBeVisible();
});
