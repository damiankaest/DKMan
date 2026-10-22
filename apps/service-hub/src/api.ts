import type { components } from './generated/api';
import type { AuthSession } from './auth';

export type AppItem = components['schemas']['AppView'];
export type User = components['schemas']['MeView'];
export type Definition = components['schemas']['DefinitionView'];
export type Readiness = components['schemas']['HealthView'];

export class ApiClient {
  constructor(private readonly auth: AuthSession) {}

  async request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal, idempotencyKey?: string): Promise<T> {
    const token = await this.auth.token();
    const response = await fetch(path, {
      method,
      body: body === undefined ? undefined : JSON.stringify(body),
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...(idempotencyKey ? {'Idempotency-Key': idempotencyKey} : {}) },
      signal,
      credentials: 'omit',
      cache: 'no-store',
    });
    if (!response.ok) {
      if (path.startsWith('/api/v1/chat') && [502,503].includes(response.status)) {
        const body = await response.json().catch(() => ({})) as {detail?: string};
        const messages: Record<string,string> = {chat_provider_not_configured:'Der Modellanbieter ist noch nicht vollständig konfiguriert. Bitte prüfe die Serverkonfiguration.',chat_provider_busy:'Der Modellanbieter ist ausgelastet. Bitte versuche es gleich noch einmal.',chat_provider_unavailable:'Der Modellanbieter ist momentan nicht erreichbar. Deine Nachricht wurde nicht ausgeführt.',chat_provider_invalid_response:'Der Modellanbieter hat keine gültige Antwort geliefert. Bitte versuche es erneut.',chat_provider_invalid_intent:'Die Modellantwort entspricht keinem erlaubten Auftrag. Bitte formuliere den Auftrag erneut.'};
        throw new Error(messages[body.detail ?? ''] ?? 'Der Chat ist momentan nicht erreichbar.');
      }
      if (response.status === 404) throw new Error('Der angefragte Eintrag ist nicht vorhanden oder nicht für dich freigegeben.');
      if (response.status === 401) throw new Error('Sitzung abgelaufen. Bitte erneut anmelden.');
      if (response.status === 403) throw new Error('Für diese Aktion fehlen dir die Rechte.');
      if (response.status === 429) throw new Error('Zu viele Anfragen. Warte einen Moment und lade den Stand erneut.');
      if (response.status === 409) throw new Error('Änderung steht im Konflikt mit dem aktuellen Stand. Lade Haushalt, Plan und Job erneut.');
      throw new Error(`DKMan ist momentan nicht erreichbar (HTTP ${response.status}).`);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  get<T>(path: string, signal?: AbortSignal) { return this.request<T>(path, 'GET', undefined, signal); }
  syncProfile = (signal?: AbortSignal) => this.request('/api/v1/me/profile', 'PUT', undefined, signal);
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


export type Profile = components['schemas']['ProfileView'];
export type Household = components['schemas']['HouseholdView'];
export type Grant = components['schemas']['GrantView'];
