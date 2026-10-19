import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AccessAdmin } from './AccessAdmin';
import { ApiClient } from './api';

afterEach(() => vi.unstubAllGlobals());

it('creates households, adds members and confirms removal', async () => {
  let member = false;
  let created = false;
  const fetcher = vi.fn(async (path: string, init: RequestInit) => {
    const method = init.method ?? 'GET';
    if (method === 'POST') created = true;
    if (method === 'PUT') member = true;
    if (method === 'DELETE') member = false;
    const person = { id: 'alice', subject: 'sub-alice', display_name: 'Alice' };
    const body = path.endsWith('/users') ? [person] : path.endsWith('/members') ? (member ? [person] : []) : created ? [{ id: 'home', name: 'Zuhause' }] : [];
    return method === 'PUT' || method === 'DELETE' ? new Response(null, { status: 204 }) : new Response(JSON.stringify(body));
  });
  vi.stubGlobal('fetch', fetcher);
  const confirm = vi.fn(() => false);
  vi.stubGlobal('confirm', confirm);
  const api = new ApiClient({ authenticated: true, token: async () => 'token', login: async () => {}, logout: async () => {} });
  render(<AccessAdmin api={api} installations={[]} />);
  fireEvent.change(screen.getByLabelText('Neuer Haushalt'), { target: { value: 'Zuhause' } });
  fireEvent.click(screen.getByRole('button', { name: 'Haushalt erstellen' }));
  await screen.findByRole('option', { name: 'Zuhause' });
  fireEvent.change(screen.getByLabelText('Haushalt'), { target: { value: 'home' } });
  const add = await screen.findByRole('button', { name: 'Mitglied hinzufügen' });
  await waitFor(() => expect(add).toBeEnabled());
  fireEvent.click(add);
  const remove = await screen.findByRole('button', { name: 'Mitglied entfernen' });
  await waitFor(() => expect(remove).toBeEnabled());
  fireEvent.click(remove);
  expect(confirm).toHaveBeenCalledOnce();
  expect(member).toBe(true);
  confirm.mockReturnValue(true);
  fireEvent.click(remove);
  await screen.findByRole('button', { name: 'Mitglied hinzufügen' });
  expect(member).toBe(false);
  expect(fetcher.mock.calls.every(([, init]) => (init.headers as Record<string, string>).Authorization === 'Bearer token')).toBe(true);
});
