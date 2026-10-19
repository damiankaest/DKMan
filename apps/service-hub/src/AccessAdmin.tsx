import { useEffect, useState } from 'react';
import type { ApiClient, AppItem, Grant, Household, Profile } from './api';

export function AccessAdmin({ api, installations }: { api: ApiClient; installations: AppItem[] }) {
  const [users, setUsers] = useState<Profile[]>([]);
  const [homes, setHomes] = useState<Household[]>([]);
  const [home, setHome] = useState('');
  const [members, setMembers] = useState<Profile[]>([]);
  const [app, setApp] = useState('');
  const [grants, setGrants] = useState<Grant[]>([]);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [loadedKey, setLoadedKey] = useState('');
  const selectionKey = `${home}/${app}/${revision}`;
  const disabled = busy || loadedKey !== selectionKey;

  useEffect(() => {
    const controller = new AbortController();
    const signal = controller.signal;
    async function load() {
      try {
        const [people, households, membership, permissions] = await Promise.all([
          api.get<Profile[]>('/api/v1/users', signal),
          api.get<Household[]>('/api/v1/households', signal),
          home ? api.get<Profile[]>(`/api/v1/households/${encodeURIComponent(home)}/members`, signal) : [],
          app ? api.get<Grant[]>(`/api/v1/installations/${encodeURIComponent(app)}/grants`, signal) : [],
        ]);
        if (!signal.aborted) { setUsers(people); setHomes(households); setMembers(membership); setGrants(permissions); setLoadedKey(`${home}/${app}/${revision}`); }
      } catch (cause) { if (!signal.aborted) setError(String(cause)); }
    }
    void load();
    return () => controller.abort();
  }, [api, home, app, revision]);

  async function change(path: string, method: string, body?: unknown) {
    setBusy(true); setError('');
    try { await api.request(path, method, body); setRevision(value => value + 1); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Änderung fehlgeschlagen.'); }
    finally { setBusy(false); }
  }

  return <section className="access-admin" aria-label="Haushalte und Freigaben">
    <h2>Haushalte und Freigaben</h2>
    <p>Benutzer erscheinen nach ihrer ersten Anmeldung. Konten und globale Rollen werden in Keycloak verwaltet.</p>
    {error && <p role="alert" className="error">{error}</p>}
    <form onSubmit={event => { event.preventDefault(); void change('/api/v1/households', 'POST', { name: name.trim() }); }}>
      <label>Neuer Haushalt <input required maxLength={120} value={name} onChange={event => setName(event.target.value)} /></label>
      <button disabled={busy || !name.trim()}>Haushalt erstellen</button>
    </form>
    <label>Haushalt <select value={home} onChange={event => { setHome(event.target.value); setMembers([]); }}>
      <option value="">Bitte wählen</option>{homes.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select></label>
    {home && <ul>{users.map(person => {
      const member = members.some(item => item.id === person.id);
      return <li key={person.id}>{person.display_name} <small>{person.subject}</small> <button disabled={disabled} onClick={() => {
        if (member && !window.confirm('Mitglied und alle App-Freigaben dieses Haushalts entfernen?')) return;
        void change(`/api/v1/households/${encodeURIComponent(home)}/members/${encodeURIComponent(person.id)}`, member ? 'DELETE' : 'PUT');
      }}>{member ? 'Mitglied entfernen' : 'Mitglied hinzufügen'}</button></li>;
    })}</ul>}
    <h3>App-Zugriff</h3>
    <p>Eine Mitgliedschaft allein gibt keine App frei. Freigaben gelten nur für Mitglieder des Installationshaushalts.</p>
    {!installations.length ? <p>Noch keine installierten Apps vorhanden.</p> : <label>Installation <select value={app} onChange={event => { setApp(event.target.value); setGrants([]); }}>
      <option value="">Bitte wählen</option>{installations.map(item => <option key={item.id} value={item.id}>{item.name} ({item.id})</option>)}
    </select></label>}
    {app && <ul>{users.map(person => {
      const allowed = grants.some(item => item.subject === person.subject && item.permission === 'app.use');
      return <li key={person.id}>{person.display_name} <button disabled={disabled} onClick={() => {
        void change(`/api/v1/installations/${encodeURIComponent(app)}/grants/${encodeURIComponent(person.id)}`, allowed ? 'DELETE' : 'PUT');
      }}>{allowed ? 'Freigabe entziehen' : 'App freigeben'}</button></li>;
    })}</ul>}
  </section>;
}
