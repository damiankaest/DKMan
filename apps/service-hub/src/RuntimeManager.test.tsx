import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { RuntimeManager } from './RuntimeManager';

afterEach(() => vi.unstubAllGlobals());
function setup(resume = false, authorized = true, holdStatus = false) {
  let releaseStatus!: () => void;
  const statusGate = new Promise<void>(resolve => {releaseStatus = resolve;});
  let state = resume ? 'reconciliation_required' : '';
  const binding = {id:'approval',subject:'operator',action:'deployment.stop',resource_type:'app_installation',resource_id:'app',plan_hash:'c'.repeat(64),expires_at:'2026-10-20T20:00:00Z'};
  const job = () => ({id:'job',requested_by:'operator',action:'deployment.stop',resource_id:'app',state,plan_hash:binding.plan_hash,plan:{action:'stop',subject:'operator',resource_id:'app',runtime:{image:'sha256:aaa',database_image:'sha256:bbb'}},failure_code:null});
  const fetcher = vi.fn(async (path: string, init: RequestInit) => {
    if (path.endsWith('/stop')) state = 'waiting_approval';
    if (path.endsWith('/decision')) state = 'queued';
    if (path.endsWith('/run')) state = 'succeeded';
    if (path.endsWith('/status') && holdStatus && state === 'waiting_approval') await statusGate;
    const body = path.endsWith('/runtime/installations') ? (authorized ? [{id:'app',name:'Notes'}] : [])
      : path.endsWith('/status') ? {installation_id:'app',state:state === 'succeeded' ? 'stopped' : 'running',observed_at:new Date().toISOString(),blocked_job_id: state && state !== 'succeeded' ? 'job' : null}
      : path.endsWith('/jobs') ? (state ? [job()] : []) : path.endsWith('/approval') ? binding
      : path.endsWith('/events') ? [{sequence:1,kind:'submitted',created_at:new Date().toISOString()}]
      : path.endsWith('/logs') ? {text:'<script>window.pwned=1</script> password=[REDACTED]',max_lines:100,max_bytes:8192}
      : job();
    return new Response(JSON.stringify(body),{status:init.method === 'POST' && path.endsWith('/stop') ? 202 : 200});
  });
  vi.stubGlobal('fetch',fetcher);
  const api = new ApiClient({authenticated:true,token:async () => 'test',login:async () => {},logout:async () => {}});
  const changed = vi.fn();
  render(<RuntimeManager api={api} subject="operator" onChanged={changed} />);
  return {fetcher,binding,releaseStatus};
}
it('reviews the full lifecycle binding, then executes and displays actual stopped status',async () => {
  const {fetcher,binding,releaseStatus} = setup(false,true,true);
  const stop = await screen.findByRole('button',{name:'Container stoppen'});
  await waitFor(() => expect(stop).toBeEnabled());
  fireEvent.click(stop);
  const approve = await screen.findByRole('button',{name:'Runtimeplan freigeben'});
  expect(approve).toBeDisabled();
  expect(screen.getByRole('checkbox')).toBeDisabled();
  releaseStatus();
  expect(fetcher.mock.calls.filter(([path]) => path.endsWith('/approval'))).toHaveLength(1);
  expect(screen.queryByRole('button',{name:'Runtimeaktion ausführen'})).toBeNull();
  await waitFor(() => expect(screen.getByRole('checkbox')).toBeEnabled());
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(approve);
  const run = await screen.findByRole('button',{name:'Runtimeaktion ausführen'});
  await waitFor(() => expect(run).toBeEnabled());
  const call = fetcher.mock.calls.find(([path]) => path.endsWith('/decision'))!;
  expect(JSON.parse(call[1].body as string)).toEqual({...binding,id:undefined,decision:'approve'});
  fireEvent.click(run);
  await screen.findByRole('heading',{name:/Erfolgreich abgeschlossen/});
  expect(screen.getByText(/Gestoppt · Gemessen/)).toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([path]) => path.endsWith('/stop'))).toHaveLength(1);
});
it('restores an uncertain persisted job and blocks new mutations after reload',async () => {
  const {fetcher} = setup(true);
  await screen.findByRole('button',{name:'Runtimeergebnis abgleichen'});
  expect(screen.getByRole('button',{name:'Container starten'})).toBeDisabled();
  expect(screen.queryByRole('button',{name:'Runtimeaktion ausführen'})).toBeNull();
  expect(fetcher.mock.calls.every(([,init]) => init.method === 'GET')).toBe(true);
});
it('renders provider log text without creating executable HTML',async () => {
  setup();
  const logs = await screen.findByRole('button',{name:'Logs anzeigen'});
  fireEvent.click(logs);
  const output = await screen.findByLabelText('Runtime-Logs');
  expect(output.textContent).toContain('<script>window.pwned=1</script>');
  expect(output.querySelector('script')).toBeNull();
});
it('does not offer container controls when no runtime scope is granted',async () => {
  setup(false,false);
  await screen.findByText(/Keine für deinen Runtimebetrieb/);
  expect(screen.queryByRole('button',{name:'Container starten'})).toBeNull();
});
