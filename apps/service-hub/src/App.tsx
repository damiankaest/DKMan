import { useEffect, useMemo, useState } from 'react';
import { ApiClient, checkReadiness } from './api';
import type { AppItem, Definition, Readiness, User } from './api';
import type { AuthSession } from './auth';
import './styles.css';
import { AccessAdmin } from './AccessAdmin';
import { DeploymentAdmin } from './DeploymentAdmin';
import { RuntimeManager } from './RuntimeManager';
import { AppPlanning } from './AppPlanning';

const labels: Record<AppItem['status'], string> = {
  healthy: 'Bereit', starting: 'Startet', degraded: 'Eingeschränkt',
  unhealthy: 'Gestört', stopped: 'Gestoppt', unknown: 'Unbekannt',
};

export function App({ auth }: { auth: AuthSession }) {
  const api = useMemo(() => new ApiClient(auth), [auth]);
  const [user, setUser] = useState<User | null>(null);
  const [apps, setApps] = useState<AppItem[]>([]);
  const [catalog, setCatalog] = useState<Definition[]>([]);
  const [health, setHealth] = useState<Readiness | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(auth.authenticated);
  const [query, setQuery] = useState('');
  const [tab, setTab] = useState<'apps' | 'admin' | 'planning'>('apps');

  useEffect(() => {
    const controller = new AbortController();
    const signal = controller.signal;
    async function poll() {
      try {
        const result = await checkReadiness(signal);
        if (!signal.aborted) setHealth(result);
      } catch {
        if (!signal.aborted) setHealth(null);
      }
    }
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 15_000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!auth.authenticated) return;
    const controller = new AbortController();
    const signal = controller.signal;
    async function load() {
      try {
        await api.syncProfile(signal);
        const [profile, installations] = await Promise.all([api.me(signal), api.apps(signal)]);
        if (signal.aborted) return;
        setUser(profile);
        setApps(installations);
        if (profile.roles.includes('admin')) {
          const definitions = await api.catalog(signal);
          if (!signal.aborted) setCatalog(definitions);
        }
      } catch (cause) {
        if (!signal.aborted) setError(cause instanceof Error ? cause.message : 'Laden fehlgeschlagen.');
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [api, auth.authenticated]);

  useEffect(() => {
    if (!auth.authenticated) return;
    const timer = window.setInterval(() => {void api.apps().then(setApps).catch(() => setApps(current => current.map(app => ({...app, status:'unknown', route:null}))));}, 15_000);
    return () => window.clearInterval(timer);
  }, [api, auth.authenticated]);

  function login() {
    void auth.login().catch(() => setError('Anmeldung konnte nicht gestartet werden.'));
  }
  function logout() {
    void auth.logout().catch(() => setError('Abmeldung fehlgeschlagen. Bitte erneut versuchen.'));
  }

  const filtered = apps.filter(app => app.name.toLocaleLowerCase('de').includes(query.toLocaleLowerCase('de')));
  return (
    <div className="layout">
      <a className="skip" href="#main">Zum Inhalt</a>
      <header>
        <a className="brand" href="/" aria-label="DKMan Startseite"><span className="logo">DK</span> DKMan<span className="brand-label">SERVICEHUB</span></a>
        <nav aria-label="Hauptnavigation">
          <button className={tab === 'apps' ? 'active' : ''} onClick={() => setTab('apps')}>Meine Apps</button>
          {user?.roles.some(role => ['admin','developer','member'].includes(role)) && <button className={tab === 'planning' ? 'active' : ''} onClick={() => setTab('planning')}>App planen</button>}
          {user?.roles.some(role => ['admin','operator'].includes(role)) && <button className={tab === 'admin' ? 'active' : ''} onClick={() => setTab('admin')}>Verwaltung</button>}
        </nav>
        {auth.authenticated ? <button className="quiet" onClick={logout}>Abmelden</button> : <button className="primary" onClick={login}>Anmelden</button>}
      </header>

      <main id="main">
        <section className="hero">
          <div>
            <p className="eyebrow">DEIN ZUHAUSE. DEINE ANWENDUNGEN.</p>
            <h1>Ein Ort für<br /><span>deine Möglichkeiten.</span></h1>
            <p className="intro">Dein privater ServiceHub bringt Anwendungen, Menschen und Ideen zusammen.</p>
          </div>
          <aside className="system" aria-label="Plattformstatus">
            <span className="eyebrow">DKMAN CORE</span>
            <p className={`system-state ${health?.status === 'healthy' ? 'healthy' : 'unknown'}`}>
              <i />{health?.status === 'healthy' ? 'Core bereit' : health ? 'Core nicht bereit' : 'Status unbekannt'}
            </p>
            <p className="muted">{health ? `Datenbank: ${health.database === 'ready' ? 'erreichbar' : 'nicht erreichbar'}` : 'Health-Prüfung nicht erreichbar'}</p>
            {health && <time dateTime={health.checked_at}>Geprüft: {new Date(health.checked_at).toLocaleTimeString('de-DE')}</time>}
            <span className="milestone">0.1 · Apps und Planung</span>
          </aside>
        </section>

        {error && <p role="alert" className="error">{error}</p>}

        {!auth.authenticated ? (
          <section className="welcome">
            <span className="section-number">01 / WILLKOMMEN</span>
            <h2>Dein Hub beginnt mit dir.</h2>
            <p>Melde dich an, um deine freigegebenen Anwendungen zu sehen.</p>
            <button className="primary" onClick={login}>Mit DKMan anmelden <span aria-hidden="true">↗</span></button>
          </section>
        ) : loading ? <p role="status">Dein ServiceHub wird geladen …</p> : tab === 'apps' ? (
          <section>
            <div className="section-head">
              <div><span className="section-number">01 / DEIN SERVICEHUB</span><h2>{user ? `Hallo, ${user.display_name}.` : 'Meine Apps'}</h2></div>
              <label className="search"><span>Apps durchsuchen</span><input type="search" placeholder="Nach einer App suchen …" value={query} onChange={event => setQuery(event.target.value)} /></label>
            </div>
            {filtered.length === 0 ? <div className="empty"><span aria-hidden="true">▦</span><h3>{query ? 'Keine passenden Apps' : 'Platz für deine ersten Apps'}</h3><p>{query ? 'Versuche einen anderen Suchbegriff.' : 'Sobald Anwendungen installiert und für dich freigegeben sind, erscheinen sie hier.'}</p></div> :
              <div className="grid">{filtered.map(app => <article className="app-card" key={app.id}>
                <div className="app-art" aria-hidden="true">{app.name.slice(0, 2)}</div>
                <div className="card-body"><span className={`badge ${app.status}`}>{labels[app.status]}</span><h3>{app.name}</h3><p>{app.description}</p><span className="muted">Version {app.version}</span>
                  {app.route && app.route.startsWith('/run/') && !app.route.includes('//') ? <a className="open" href={app.route}>App öffnen ↗</a> : <p className="muted">Noch keine freigegebene Laufzeit-URL</p>}
                </div>
              </article>)}</div>}
          </section>
        ) : tab === 'planning' && user ? <AppPlanning api={api} subject={user.subject} admin={user.roles.includes('admin')} /> : (
          <section>
            {user && <RuntimeManager api={api} subject={user.subject} onChanged={() => {void api.apps().then(setApps).catch(() => setApps(current => current.map(app => ({...app,status:'unknown',route:null}))));}} />}
            {user?.roles.includes('admin') && <>
            {user && <DeploymentAdmin api={api} subject={user.subject} onInstalled={() => {void api.apps().then(setApps).catch(() => setError('Apps konnten nicht aktualisiert werden.'));}} />}
            <AccessAdmin api={api} installations={apps} />
            <span className="section-number">02 / VERWALTUNG</span><h2>Registrierte App-Definitionen</h2>
            <p className="muted">Die Registry beschreibt Apps. Nur separat kuratierte Quellbuilds können installiert werden.</p>
            {catalog.length === 0 ? <div className="empty"><h3>Registry ist bereit</h3><p>Manifeste können über die geschützte Registry-API registriert werden. Eine Beispielregistrierung steht in der Startanleitung.</p></div> :
              <div className="grid">{catalog.map(item => <article className="catalog-card" key={item.id}><span className="muted">{item.version} · {item.source}</span><h3>{item.name}</h3><p>{item.description}</p></article>)}</div>}
            </>}
          </section>
        )}

        <section className="roadmap"><div><span className="section-number">DEINE NÄCHSTEN MÖGLICHKEITEN</span><h2>Von der Idee zur eigenen App.</h2><p>Unter „App planen“ kannst du Ideen und Planversionen speichern. Als Nächstes folgen Chat, Planungswizard und anschließend Forge für Build und Vorschau.</p></div><span className="planned">Schritt für Schritt</span></section>
      </main>
      <footer><span>DKMan <span className="muted">/ Private by design</span></span><span className="muted">Core · Registry · Identity</span></footer>
    </div>
  );
}

