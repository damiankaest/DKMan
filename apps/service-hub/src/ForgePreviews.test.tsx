import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { ForgePreviews } from './ForgePreviews';

afterEach(() => vi.unstubAllGlobals());

it('imports a preview observation without claiming a live connection', async () => {
  const proof = {algorithm:'ed25519',key_id:'a'.repeat(64),evidence:{preview_id:'one'},signature:'signature'};
  const observation = {id:'one',artifact_id:'artifact',created_at:'2026-10-27T00:00:00Z',submitted_by:'alice',evidence_hash:'b'.repeat(64),key_id:'a'.repeat(64),evidence:{observed_at:'2026-10-27T00:00:00Z',expires_at:'2026-10-27T00:05:00Z',state:'healthy'}};
  const fetcher = vi.fn(async (_path: string, init: RequestInit) => new Response(JSON.stringify(init.method === 'POST' ? observation : [])));
  vi.stubGlobal('fetch', fetcher);
  const api = new ApiClient({authenticated:true,token:async () => 'test',login:async () => {},logout:async () => {}});
  render(<ForgePreviews api={api} artifactId="artifact" current />);
  fireEvent.click(screen.getByRole('button',{name:'Vorschau-Nachweise öffnen'}));
  await screen.findByText('Für diesen Build liegt noch kein Vorschau-Nachweis vor.');
  const file = new File([JSON.stringify(proof)], 'preview-attestation.json', {type:'application/json'});
  Object.defineProperty(file, 'text', {value:async () => JSON.stringify(proof)});
  fireEvent.change(screen.getByLabelText('Signierter Vorschau-Nachweis'),{target:{files:[file]}});
  fireEvent.click(screen.getByRole('button',{name:'Vorschau-Nachweis prüfen'}));
  await screen.findByText('Vorschau-Nachweis geprüft und gespeichert.');
  expect(screen.getByText(/Dies belegt eine frühere Messung/)).toBeVisible();
  expect(fetcher.mock.calls.filter(([,init]) => init.method === 'POST')).toHaveLength(1);
});
