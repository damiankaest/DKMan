import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { ForgeBuildArtifacts } from './ForgeBuildArtifacts';

afterEach(() => vi.unstubAllGlobals());

it('submits the signed evidence and shows the verified image digest', async () => {
  const proof = {algorithm:'ed25519', key_id:'a'.repeat(64), evidence:{build_id:'one'}, signature:'signature'};
  const artifact = {id:'one', workspace_id:'workspace', created_at:'2026-10-27T00:00:00Z', submitted_by:'alice', key_id:'a'.repeat(64), evidence_hash:'b'.repeat(64), evidence:{template:'react-spa', finished_at:'2026-10-27T00:00:00Z', manifest_digest:`sha256:${'c'.repeat(64)}`, checks:['web-passed']}};
  const fetcher = vi.fn(async (_path: string, init: RequestInit) => new Response(JSON.stringify(init.method === 'POST' ? artifact : [])));
  vi.stubGlobal('fetch', fetcher);
  const api = new ApiClient({authenticated:true,token:async () => 'test',login:async () => {},logout:async () => {}});
  render(<ForgeBuildArtifacts api={api} workspaceId="workspace" current />);
  fireEvent.click(screen.getByRole('button',{name:'Build-Nachweise öffnen'}));
  await screen.findByText('Für diesen Quellstand liegt noch kein geprüfter Build-Nachweis vor.');
  const file = new File([JSON.stringify(proof)], 'build-attestation.json', {type:'application/json'});
  Object.defineProperty(file, 'text', {value:async () => JSON.stringify(proof)});
  fireEvent.change(screen.getByLabelText('Signierter Build-Nachweis'), {target:{files:[file]}});
  fireEvent.click(screen.getByRole('button',{name:'Build-Nachweis prüfen'}));
  await screen.findByText('Build-Nachweis geprüft und gespeichert. Das Image bleibt auf dem Builder.');
  expect(screen.getByText(`sha256:${'c'.repeat(64)}`)).toBeVisible();
  const sent = fetcher.mock.calls.find(([,init]) => init.method === 'POST')!;
  expect(JSON.parse(sent[1].body as string)).toEqual(proof);
});

it('prevents importing evidence for an old plan', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('[]')));
  const api = new ApiClient({authenticated:true,token:async () => 'test',login:async () => {},logout:async () => {}});
  render(<ForgeBuildArtifacts api={api} workspaceId="workspace" current={false} />);
  fireEvent.click(screen.getByRole('button',{name:'Build-Nachweise öffnen'}));
  await waitFor(() => expect(screen.getByLabelText('Signierter Build-Nachweis')).toBeDisabled());
  expect(screen.getByRole('button',{name:'Build-Nachweis prüfen'})).toBeDisabled();
});

it.each(['python-api', 'fullstack-fastapi-react'])('offers preview evidence for %s', async template => {
  const artifact = {id:'one', workspace_id:'workspace', created_at:'2026-10-27T00:00:00Z', submitted_by:'alice', key_id:'a'.repeat(64), evidence_hash:'b'.repeat(64), evidence:{template, finished_at:'2026-10-27T00:00:00Z', manifest_digest:`sha256:${'c'.repeat(64)}`, checks:['api-passed']}};
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([artifact]))));
  const api = new ApiClient({authenticated:true,token:async () => 'test',login:async () => {},logout:async () => {}});
  render(<ForgeBuildArtifacts api={api} workspaceId="workspace" current />);
  fireEvent.click(screen.getByRole('button',{name:'Build-Nachweise öffnen'}));
  expect(await screen.findByRole('button',{name:'Vorschau-Nachweise öffnen'})).toBeVisible();
});
