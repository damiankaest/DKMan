import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiClient, type Household } from './api';
import type { components } from './generated/api';

type Curated = components['schemas']['CuratedImage'];
type Job = components['schemas']['JobView'];
type Approval = components['schemas']['ApprovalView'];
type Event = components['schemas']['JobEventView'];

const states: Record<string, string> = {waiting_approval:'Wartet auf Freigabe',queued:'Freigegeben',claimed:'Wird vorbereitet',running:'Installation läuft',succeeded:'Installiert',failed:'Fehlgeschlagen',cancelled:'Abgebrochen',expired:'Freigabe abgelaufen',reconciliation_required:'Ausgang unklar – Abgleich erforderlich'};

export function DeploymentAdmin({api, subject, onInstalled, initialDefinition}: {api: ApiClient; subject: string; onInstalled: () => void; initialDefinition?: string}) {
  const [images, setImages] = useState<Curated[]>([]);
  const [households, setHouseholds] = useState<Household[]>([]);
  const [household, setHousehold] = useState('');
  const [definition, setDefinition] = useState(initialDefinition ?? '');
  const [job, setJob] = useState<Job | null>(null);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const key = useRef<string | null>(null);

  const details = useCallback(async (next: Job) => {
    setJob(next);
    const [binding, history] = await Promise.all([
      api.get<Approval>(`/api/v1/jobs/${next.id}/approval`),
      api.get<Event[]>(`/api/v1/jobs/${next.id}/events`),
    ]);
    setApproval(binding); setEvents(history);
  }, [api]);

  const load = useCallback(async () => {
    const [curated, groups, jobs] = await Promise.all([
      api.get<Curated[]>('/api/v1/deployments/catalog'), api.get<Household[]>('/api/v1/households'), api.get<Job[]>('/api/v1/jobs'),
    ]);
    setImages(curated); setHouseholds(groups);
    setDefinition(current => curated.some(item => item.definition_id === current) ? current : initialDefinition ? '' : curated[0]?.definition_id || '');
    if (initialDefinition && !curated.some(item => item.definition_id === initialDefinition)) setError('Der vorgeschlagene Build ist nicht mehr kuratiert. Bitte lade den Stand erneut.');
    const recent = jobs.find(item => item.action === 'deployment.install' && item.requested_by === subject);
    if (recent) await details(recent);
  }, [api, details, subject, initialDefinition]);

  useEffect(() => {void load().catch((cause: Error) => setError(cause.message));}, [load]);

  async function action(work: () => Promise<void>) {
    setError(''); setBusy(true);
    try {await work();} catch (cause) {setError(cause instanceof Error ? cause.message : 'Installation momentan nicht erreichbar. Job erneut laden.');}
    finally {setBusy(false);}
  }

  function plan() {
    if (job && ['cancelled','expired','failed','succeeded'].includes(job.state)) key.current = null;
    key.current ??= crypto.randomUUID();
    void action(async () => {
      const next = await api.request<Job>('/api/v1/deployments/installations', 'POST', {definition_id:definition, household_id:household}, undefined, key.current!);
      await details(next); setConfirmed(false);
    });
  }

  function approve() {
    if (!approval || !job || !confirmed) return;
    void action(async () => {
      await api.request(`/api/v1/approvals/${approval.id}/decision`, 'POST', {
        subject:approval.subject,action:approval.action,resource_type:approval.resource_type,
        resource_id:approval.resource_id,plan_hash:approval.plan_hash,expires_at:approval.expires_at,decision:'approve',
      });
      await details(await api.get<Job>(`/api/v1/jobs/${job.id}`));
    });
  }

  function run() {
    if (!job) return;
    void action(async () => {
      const result = await api.request<Job>(`/api/v1/jobs/${job.id}/run`, 'POST');
      await details(result); if (result.state === 'succeeded') onInstalled();
    });
  }

  const runtime = job && 'image' in job.plan ? job.plan : null;
  return <section className="deployment-admin" aria-label="App installieren">
    <span className="section-number">KURATIERTER KATALOG</span><h2>Eine App für deinen Haushalt.</h2>
    <p className="muted">Prüfe den Plan, erteile die zeitlich begrenzte Freigabe und starte anschließend die Installation.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {images.length === 0 ? <p>Aktuell ist kein gebautes App-Image kuratiert.</p> : <div className="install-controls">
      <div><label htmlFor="deploy-app">App</label><select id="deploy-app" value={definition} onChange={event => {setDefinition(event.target.value); key.current = null;}}><option value="">App auswählen</option>{images.map(image => <option key={image.definition_id} value={image.definition_id}>{image.definition_id === 'demo-notes' ? 'Notes' : image.definition_id} · {image.version}</option>)}</select></div>
      <div><label htmlFor="deploy-household">Haushalt</label><select id="deploy-household" value={household} onChange={event => {setHousehold(event.target.value); key.current = null;}}><option value="">Haushalt auswählen</option>{households.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select></div>
      <button className="primary" disabled={busy || !household || !definition} onClick={plan}>Plan erstellen</button>
    </div>}
    <button className="quiet" disabled={busy} onClick={() => {void action(load);}}>Stand neu laden</button>
    {job && runtime && <article className="installation-plan" aria-label="Installationsplan">
      <h3>{states[job.state]} · Notes {runtime.version}</h3>
      <dl>
        <dt>Haushalt</dt><dd>{households.find(group => group.id === runtime.context?.household_id)?.name ?? runtime.context?.household_id}</dd>
        <dt>Herkunft</dt><dd>Geprüfter DKMan-Quellbuild, SHA-256 <code>{runtime.source_hash}</code></dd>
        <dt>App-Image</dt><dd><code>{runtime.image}</code></dd>
        <dt>Datenbank-Image</dt><dd><code>{runtime.database_image}</code></dd>
        <dt>Ressourcen</dt><dd>App: {runtime.memory_mb} MiB / {runtime.cpus} CPU; eigene PostgreSQL: 256 MiB / 0,5 CPU</dd>
        <dt>Daten & Netzwerk</dt><dd>Eigenes persistentes Datenvolume. Keine Hostports. Zugang über den Hub-Proxy mit OIDC und expliziter App-Freigabe.</dd>
        <dt>Identität</dt><dd>{job.requested_by}</dd>
        <dt>Plan-Hash</dt><dd><code>{job.plan_hash}</code></dd>
        <dt>Freigabe gültig bis</dt><dd>{approval ? new Date(approval.expires_at).toLocaleString('de-DE') : 'Wird geladen …'}</dd>
      </dl>
      {job.state === 'waiting_approval' && <><label className="approval-check"><input type="checkbox" disabled={busy} checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />Ich gebe diese Installation und ihre Ressourcen frei.</label><button className="primary" disabled={busy || !confirmed || !approval} onClick={approve}>Diesen Plan freigeben</button></>}
      {job.state === 'queued' && <button className="primary" disabled={busy} onClick={run}>Jetzt installieren</button>}
      {busy && <p role="status">Aktion wird verarbeitet. Der Job bleibt bei einem Verbindungsabbruch gespeichert.</p>}
      {['waiting_approval','queued'].includes(job.state) && <button className="quiet" disabled={busy} onClick={() => {void action(async () => {await details(await api.request<Job>(`/api/v1/jobs/${job.id}/cancel`,'POST')); key.current = null;});}}>Plan abbrechen</button>}
      {job.state === 'reconciliation_required' && <><p>Die Installation wird nicht erneut gesendet. Prüfe das gespeicherte Ergebnis beim Deployment-Adapter.</p><button disabled={busy} onClick={() => {void action(async () => {const next = await api.request<Job>(`/api/v1/jobs/${job.id}/reconcile`,'POST'); await details(next); if(next.state === 'succeeded') onInstalled();});}}>Ergebnis abgleichen</button></>}
      {job.state === 'succeeded' && <p>Notes ist installiert. Unter „Meine Apps“ öffnen; weitere Personen über die App-Freigaben berechtigen.</p>}
      {typeof job.result?.evidence_hash === 'string' && <p>Abschlussnachweis: <code>{job.result.evidence_hash}</code></p>}
      {job.failure_code && <p className="muted">Fehlercode: {job.failure_code}</p>}
      <details><summary>Jobverlauf</summary><p><code>{job.id}</code></p><ol>{events.map(event => <li key={event.sequence}>{event.kind} · {new Date(event.created_at).toLocaleTimeString('de-DE')}</li>)}</ol></details>
    </article>}
  </section>;
}
