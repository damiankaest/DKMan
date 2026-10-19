import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import type { AuthSession } from './auth';

function session(authenticated = false): AuthSession {
  return {
    authenticated,
    login: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
    token: vi.fn(async () => 'test-access-token'),
  };
}

function responses(roles: string[] = ['member']) {
  vi.stubGlobal('fetch', vi.fn(async (path: string) => {
    const body = path === '/health/ready' ? {
      status: 'healthy', database: 'ready', schema: 'current', checked_at: '2026-10-19T10:00:00Z',
    } : path === '/api/v1/me' ? {
      subject: 'alice', display_name: 'Alice', roles,
    } : ['/api/v1/catalog', '/api/v1/users', '/api/v1/households'].includes(path) ? [] : [{
      id: 'notes-one', definition_id: 'notes', name: 'Notes', version: '0.1.0',
      description: 'Gemeinsame Notizen', status: 'unknown', checked_at: null, route: null,
    }];
    return new Response(JSON.stringify(body), { status: 200 });
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe('ServiceHub', () => {
  it('shows login without fabricating apps', async () => {
    responses();
    const auth = session();
    render(<App auth={auth} />);
    expect(screen.getByRole('heading', { name: 'Dein Hub beginnt mit dir.' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: /Mit DKMan anmelden/ }));
    expect(auth.login).toHaveBeenCalledOnce();
    expect(await screen.findByText('Core bereit')).toBeVisible();
    expect(screen.queryByText('Notes')).toBeNull();
  });

  it('shows assigned apps and retains unknown state without an opening link', async () => {
    responses();
    render(<App auth={session(true)} />);
    expect(await screen.findByRole('heading', { name: 'Notes' })).toBeVisible();
    expect(screen.getByText('Unbekannt')).toBeVisible();
    expect(screen.queryByRole('link', { name: /App öffnen/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Verwaltung' })).toBeNull();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Garten' } });
    expect(screen.getByText('Keine passenden Apps')).toBeVisible();
  });

  it('exposes registry administration only for the server-reported admin role', async () => {
    responses(['admin']);
    render(<App auth={session(true)} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Verwaltung' }));
    expect(screen.getByRole('heading', { name: 'Registry ist bereit' })).toBeVisible();
  });

  it('shows an API failure and no invented healthy state', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 503 })));
    render(<App auth={session(true)} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 503');
    expect(screen.queryByText('Core bereit')).toBeNull();
  });
});

