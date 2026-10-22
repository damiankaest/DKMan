import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AppPlanning } from './AppPlanning';
import { ApiClient } from './api';

afterEach(() => vi.unstubAllGlobals());

function fixture(initial = false, failFirst = false) {
  const requirements = {title:'Unser Garten',goal:'Pflanzen gemeinsam pflegen',features:['Pflanzen verwalten'],entities:[],screens:[],acceptance_checks:[],deployment_requirements:[]};
  let request = initial ? {id:'request-1',title:requirements.title,requested_by:'alice',household_id:null,current_revision:1,created_at:'2026-10-22T10:00:00Z',updated_at:'2026-10-22T10:00:00Z'} : null;
  let history = [{id:'plan-1',request_id:'request-1',revision:1,document:{schema_version:1,planning_mode:'manual',household_id:null,requirements},content_hash:'b'.repeat(64),created_by:'alice',created_at:'2026-10-22T10:00:00Z',approved_job_id:null as string | null}];
  let job: {id:string;action:string;requested_by:string;state:string;failure_code:null} | null = null;
  const binding = {id:'approval-1',subject:'alice',action:'app_plan.approve',resource_type:'app_plan',resource_id:'plan-1',plan_hash:'a'.repeat(64),expires_at:'2026-10-22T12:00:00Z'};
  const fetcher = vi.fn(async (path: string, init: RequestInit) => {
    let body: unknown;
    if (path === '/api/v1/households') body = [];
    else if (path === '/api/v1/app-requests' && init.method === 'POST') {
      if (failFirst) {failFirst = false;return new Response('{}',{status:503});}
      const input = JSON.parse(init.body as string);
      request = {id:'request-1',title:input.requirements.title,requested_by:'alice',household_id:null,current_revision:1,created_at:'2026-10-22T10:00:00Z',updated_at:'2026-10-22T10:00:00Z'};
      history[0].document.requirements = input.requirements;
      body = request;
    } else if (path === '/api/v1/app-requests') body = request ? [request] : [];
    else if (path === '/api/v1/app-requests/request-1') body = request;
    else if (path === '/api/v1/app-requests/request-1/plans' && init.method === 'POST') {
      const input = JSON.parse(init.body as string);
      history = [{...history[0],id:'plan-2',revision:2,document:{...history[0].document,requirements:input.requirements}},...history];
      request = {...request!,current_revision:2}; body = history[0];
    } else if (path.endsWith('/plans')) body = history;
    else if (path.startsWith('/api/v1/app-plans/') && path.endsWith('/jobs')) body = job ? [job] : [];
    else if (path.startsWith('/api/v1/app-plans/') && path.endsWith('/approve')) {
      job = {id:'job-1',action:'app_plan.approve',requested_by:'alice',state:'waiting_approval',failure_code:null};body = job;
    } else if (path.endsWith('/approval')) body = binding;
    else if (path.endsWith('/events')) body = [];
    else if (path.endsWith('/decision')) {job!.state = 'queued';body = binding;}
    else if (path.endsWith('/run')) {job!.state = 'succeeded';history[0].approved_job_id = 'job-1';body = job;}
    else if (path.startsWith('/api/v1/jobs/')) body = job;
    else throw new Error(`Unhandled test request: ${path}`);
    return new Response(JSON.stringify(body));
  });
  vi.stubGlobal('fetch',fetcher);
  const api = new ApiClient({authenticated:true,token:async () => 'test-token',login:async () => {},logout:async () => {}});
  return {api,fetcher,binding};
}

function fill() {
  fireEvent.change(screen.getByLabelText('Name der App'),{target:{value:'Unser Garten'}});
  fireEvent.change(screen.getByLabelText('Was soll die App erreichen?'),{target:{value:'Pflanzen gemeinsam pflegen'}});
  fireEvent.change(screen.getByLabelText('Funktionen'),{target:{value:'Pflanzen verwalten\nGießen planen'}});
}

it('retains a request key on connection failure and stores a new immutable revision', async () => {
  const {api,fetcher} = fixture(false,true);
  render(<AppPlanning api={api} subject="alice" admin={false} />);
  fill();
  fireEvent.click(screen.getByRole('button',{name:'App-Idee speichern'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 503');
  fireEvent.click(screen.getByRole('button',{name:'App-Idee speichern'}));
  await screen.findByRole('article',{name:'Gespeicherter App-Plan'});
  const submissions = fetcher.mock.calls.filter(([path,init]) => path === '/api/v1/app-requests' && init.method === 'POST');
  expect(submissions).toHaveLength(2);
  expect((submissions[0][1].headers as Record<string,string>)['Idempotency-Key']).toEqual((submissions[1][1].headers as Record<string,string>)['Idempotency-Key']);
  fireEvent.change(screen.getByLabelText('Funktionen'),{target:{value:'Fotos verwalten'}});
  await waitFor(() => expect(screen.getByRole('button',{name:'Neue Planversion speichern'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Neue Planversion speichern'}));
  await screen.findByRole('option',{name:'Version 2'});
  const revision = fetcher.mock.calls.find(([path,init]) => path.endsWith('/request-1/plans') && init.method === 'POST')!;
  expect(JSON.parse(revision[1].body as string)).toMatchObject({expected_revision:1,requirements:{features:['Fotos verwalten']}});
  fireEvent.change(screen.getByLabelText('Planversion'),{target:{value:'plan-1'}});
  expect(screen.getByText('Frühere Version')).toBeVisible();
  expect(screen.getByText('Gießen planen')).toBeVisible();
  expect(screen.queryByRole('button',{name:'Freigabe vorbereiten'})).toBeNull();
});

it('restores saved ideas and binds approval to the server plan before recording it', async () => {
  const {api,fetcher,binding} = fixture(true);
  render(<AppPlanning api={api} subject="alice" admin />);
  fireEvent.click(await screen.findByRole('button',{name:/Unser Garten.*Version 1/}));
  const prepare = await screen.findByRole('button',{name:'Freigabe vorbereiten'});
  await waitFor(() => expect(prepare).toBeEnabled());
  fireEvent.click(prepare);
  const approve = await screen.findByRole('button',{name:'Planversion freigeben'});
  expect(approve).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox'));
  await waitFor(() => expect(approve).toBeEnabled());
  fireEvent.click(approve);
  const finish = await screen.findByRole('button',{name:'Freigabe abschließen'});
  await waitFor(() => expect(finish).toBeEnabled());
  fireEvent.click(finish);
  await screen.findByText('Planversion freigegeben');
  const decision = fetcher.mock.calls.find(([path]) => path.endsWith('/decision'))!;
  const {id: approvalId,...expected} = binding;
  expect(approvalId).toBe('approval-1');
  expect(JSON.parse(decision[1].body as string)).toEqual({...expected,decision:'approve'});
  expect(fetcher.mock.calls.some(([path]) => path.includes('/deployments/') || path.endsWith('/installations'))).toBe(false);
});

it('starts a distinct idea with a new request key after the previous save', async () => {
  const {api,fetcher} = fixture();
  render(<AppPlanning api={api} subject="alice" admin={false} />);
  fill();fireEvent.click(screen.getByRole('button',{name:'App-Idee speichern'}));
  await screen.findByRole('article',{name:'Gespeicherter App-Plan'});
  await waitFor(() => expect(screen.getByRole('button',{name:'Neue App-Idee'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Neue App-Idee'}));
  fill();fireEvent.click(screen.getByRole('button',{name:'App-Idee speichern'}));
  await screen.findByRole('article',{name:'Gespeicherter App-Plan'});
  const posts = fetcher.mock.calls.filter(([path,init]) => path === '/api/v1/app-requests' && init.method === 'POST');
  expect(posts).toHaveLength(2);
  expect((posts[0][1].headers as Record<string,string>)['Idempotency-Key']).not.toEqual((posts[1][1].headers as Record<string,string>)['Idempotency-Key']);
});
