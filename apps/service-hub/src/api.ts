import type { components } from './generated/api';
import type { AuthSession } from './auth';

export type AppItem = components['schemas']['AppView'];
export type User = components['schemas']['MeView'];
export type Definition = components['schemas']['DefinitionView'];
export type Readiness = components['schemas']['HealthView'];

export class ApiClient {
  constructor(private readonly auth: AuthSession) {}

  async get<T>(path: string, signal?: AbortSignal): Promise<T> {
    const token = await this.auth.token();
    const response = await fetch(path, {
      headers: { Authorization: `Bearer ${token}` },
      signal,
      credentials: 'omit',
      cache: 'no-store',
    });
    if (!response.ok) {
      if (response.status === 401) throw new Error('Sitzung abgelaufen. Bitte erneut anmelden.');
      if (response.status === 403) throw new Error('Für diese Aktion fehlen dir die Rechte.');
      throw new Error(`DKMan ist momentan nicht erreichbar (HTTP ${response.status}).`);
    }
    return response.json() as Promise<T>;
  }

  me = (signal?: AbortSignal) => this.get<User>('/api/v1/me', signal);
  apps = (signal?: AbortSignal) => this.get<AppItem[]>('/api/v1/apps', signal);
  catalog = (signal?: AbortSignal) => this.get<Definition[]>('/api/v1/catalog', signal);
}

export async function checkReadiness(signal?: AbortSignal): Promise<Readiness> {
  const response = await fetch('/health/ready', { signal, cache: 'no-store' });
  if (response.status !== 200 && response.status !== 503) {
    throw new Error('Health-Prüfung nicht erreichbar.');
  }
  return response.json() as Promise<Readiness>;
}
