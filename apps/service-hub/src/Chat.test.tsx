import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { Chat } from './Chat';
import type { AuthSession } from './auth';

const provider = {mode:'rules',label:'Regelbasierter Modus',notice:'Kein LLM verbunden.'};
const api = new ApiClient({authenticated:true,token:async () => 'test-only',login:async () => {},logout:async () => {}} as AuthSession);
const reply = {provider,intent:'help',summary:'Bitte formuliere einen einzelnen Auftrag.',observed_at:'2026-10-22T12:00:00Z',apps:[],registry:[],jobs:[],proposal:null};
afterEach(() => vi.unstubAllGlobals());

it('labels rules mode and forwards only the message to the authenticated dispatcher', async () => {
  const fetcher = vi.fn(async (_path: string, options?: RequestInit) => new Response(JSON.stringify(options?.method === 'POST' ? reply : provider)));
  vi.stubGlobal('fetch', fetcher);
  render(<Chat api={api} onProposal={vi.fn()} />);
  expect(await screen.findByText('Kein LLM verbunden.')).toBeVisible();
  fireEvent.change(screen.getByLabelText('Dein Auftrag'), {target:{value:'Zeige Jobs'}});
  fireEvent.click(screen.getByRole('button',{name:'Senden'}));
  expect(await screen.findByText(reply.summary)).toBeVisible();
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(JSON.parse(fetcher.mock.calls[1][1]!.body as string)).toEqual({message:'Zeige Jobs'});
  expect((fetcher.mock.calls[1][1]!.headers as Record<string,string>).Authorization).toBe('Bearer test-only');
});

it('renders untrusted draft text safely and hands over a proposal only after an explicit click', async () => {
  const proposal = {kind:'app.draft',requirements:{title:'Unser Garten',goal:'<img src=x onerror=alert(1)>',features:['<script>doBadThings()</script>']}};
  const onProposal = vi.fn();
  vi.stubGlobal('fetch', vi.fn(async (_path: string, options?: RequestInit) => new Response(JSON.stringify(options?.method === 'POST' ? {...reply,proposal} : provider))));
  render(<Chat api={api} onProposal={onProposal} />);
  await screen.findByText(provider.notice);
  fireEvent.click(screen.getByRole('button',{name:/Plane eine Garten-App/}));
  expect(await screen.findByText('<script>doBadThings()</script>')).toBeVisible();
  expect(document.querySelector('.chat script, .chat img')).toBeNull();
  expect(onProposal).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Entwurf in App-Planung prüfen'}));
  expect(onProposal).toHaveBeenCalledExactlyOnceWith(proposal);
});

it('displays actual failed job state and ordered events without an execute or approval control', async () => {
  const jobs = [{id:'job-id',action:'deployment.stop',state:'failed',updated_at:reply.observed_at,events:[{sequence:1,kind:'requested',state:'waiting_approval',created_at:reply.observed_at},{sequence:2,kind:'failed',state:'failed',created_at:reply.observed_at}]}];
  vi.stubGlobal('fetch', vi.fn(async (_path: string, options?: RequestInit) => new Response(JSON.stringify(options?.method === 'POST' ? {...reply,jobs} : provider))));
  render(<Chat api={api} onProposal={vi.fn()} />);
  await screen.findByText(provider.notice);
  fireEvent.click(screen.getByRole('button',{name:'Zeige Jobs'}));
  expect(await screen.findByRole('heading',{name:'Fehlgeschlagen · deployment.stop'})).toBeVisible();
  expect(screen.getAllByRole('listitem').map(item => item.textContent)).toEqual([expect.stringContaining('requested'),expect.stringContaining('failed')]);
  expect(screen.queryByRole('button',{name:/freigeben|ausführen/i})).toBeNull();
});

it('keeps a failed message for retry and shows only allowlisted provider errors', async () => {
  vi.stubGlobal('fetch', vi.fn(async (_path: string, options?: RequestInit) => options?.method === 'POST' ? new Response(JSON.stringify({detail:'chat_provider_not_configured',secret:'never-render'}),{status:503}) : new Response(JSON.stringify({...provider,mode:'external'}))));
  render(<Chat api={api} onProposal={vi.fn()} />);
  await screen.findByText(provider.notice);
  fireEvent.click(screen.getByRole('button',{name:'Zeige Jobs'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Modellanbieter ist noch nicht vollständig konfiguriert');
  await waitFor(() => expect(screen.getByLabelText('Dein Auftrag')).toHaveValue('Zeige Jobs'));
  expect(screen.queryByText('never-render')).toBeNull();
});
