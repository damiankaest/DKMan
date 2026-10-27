// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import App from '../src/App';

const mocked = vi.hoisted(() => ({
  client: {init:vi.fn(async () => true), updateToken:vi.fn(async () => true), token:'test-token'},
}));
vi.mock('../src/auth', () => ({appBase:() => '/run/12345678-1234-1234-1234-123456789abc/', identity:() => mocked.client}));
afterEach(() => {cleanup();vi.unstubAllGlobals();});

it('checks the actual installation grant using the access token', async () => {
  const fetcher = vi.fn(async () => new Response('{}',{status:200}));
  vi.stubGlobal('fetch',fetcher);
  render(<App />);
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('freigegeben'));
  expect(fetcher).toHaveBeenCalledWith('/api/v1/apps/12345678-1234-1234-1234-123456789abc/access',expect.objectContaining({headers:{Authorization:'Bearer test-token'}}));
  expect(mocked.client.init).toHaveBeenCalledWith(expect.objectContaining({pkceMethod:'S256',flow:'standard'}));
});

it('does not show an authorized state when the platform denies access', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}',{status:403})));
  render(<App />);
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('nicht bestätigt'));
});
