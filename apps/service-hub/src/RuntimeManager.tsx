import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiClient } from './api';
import type { components } from './generated/api';

type Installation = components['schemas']['RuntimeInstallationView'];
type Status = components['schemas']['RuntimeStatusView'];
type Logs = components['schemas']['RuntimeLogsView'];
type Job = components['schemas']['JobView'];
type Approval = components['schemas']['ApprovalView'];
type Event = components['schemas']['JobEventView'];
type Action = 'start' | 'stop' | 'restart';
const actions: Record<Action, string> = {start:'Container starten',stop:'Container stoppen',restart:'Container neu starten'};
const states: Record<string,string> = {waiting_approval:'Wartet auf Freigabe',queued:'Freigegeben',claimed:'Wird vorbereitet',running:'Auftrag läuft',succeeded:'Erfolgreich abgeschlossen',failed:'Fehlgeschlagen',cancelled:'Abgebrochen',expired:'Freigabe abgelaufen',reconciliation_required:'Ausgang unklar – Abgleich erforderlich'};
const runtimeStates: Record<string,string> = {running:'Bereit',stopped:'Gestoppt',starting:'Startet',unhealthy:'Gestört',unknown:'Unbekannt',absent:'Container fehlen'};

export function RuntimeManager({api, subject, onChanged}: {api: ApiClient; subject: string; onChanged: () => void}) {
  const [installations, setInstallations] = useState<Installation[]>([]);
  const [selected, setSelected] = useState('');
  const [status, setStatus] = useState<Status | null>(null);
  const [logs, setLogs] = useState<Logs | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const key = useRef<{action: Action; installation: string; value: string} | null>(null);
  const generation = useRef(0);
  const busyRef = useRef(false);
  const displayedJob = useRef('');
  const detailSequence = useRef(0);
  const details = useCallback(async (next: Job) => {
    const current = generation.current;
    const sequence = ++detailSequence.current;
    const [binding, history] = await Promise.all([api.get<Approval>(`/api/v1/jobs/${next.id}/approval`),api.get<Event[]>(`/api/v1/jobs/${next.id}/events`)]);
    if (current !== generation.current || sequence !== detailSequence.current) return;
    if (displayedJob.current !== next.id) {setConfirmed(false); displayedJob.current = next.id;}
    setJob(next); setApproval(binding); setEvents(history);
  }, [api]);
  const refresh = useCallback(async () => {
    const items = await api.get<Installation[]>('/api/v1/runtime/installations');
    setInstallations(items);
    setSelected(current => items.some(item => item.id === current) ? current : items[0]?.id || '');
  }, [api]);
  useEffect(() => {void refresh().catch((cause: Error) => setError(cause.message));}, [refresh]);
  useEffect(() => {
    const current = ++generation.current;
    setStatus(null); setLogs(null); setJobs([]); setJob(null); setApproval(null); setEvents([]); setConfirmed(false); key.current = null;
    if (!selected) return;
    async function poll() {
      if (busyRef.current) return;
      try {
        const [observed, history] = await Promise.all([api.get<Status>(`/api/v1/installations/${selected}/status`),api.get<Job[]>(`/api/v1/installations/${selected}/jobs`)]);
        if (generation.current !== current || busyRef.current) return;
        setStatus(observed); setJobs(history);
        const recent = history.find(item => ['deployment.start','deployment.stop','deployment.restart'].includes(item.action));
        if (recent) await details(recent);
      } catch (cause) {
        if (generation.current === current) {setStatus(null); setLogs(null); setError(cause instanceof Error ? cause.message : 'Status nicht erreichbar.');}
      }
    }
    void poll();
    const timer = window.setInterval(() => {void poll();},15_000);
    return () => {++generation.current; window.clearInterval(timer);};
  }, [api, details, selected]);
  async function work(task: () => Promise<void>) {
    busyRef.current = true; setBusy(true); setError('');
    try {await task();} catch (cause) {setError(cause instanceof Error ? cause.message : 'Auftrag nicht erreichbar. Gespeicherten Stand erneut laden.');}
    finally {busyRef.current = false; setBusy(false);}
  }
  async function reload() {
    if (!selected) return;
    const observed = await api.get<Status>(`/api/v1/installations/${selected}/status`);
    const history = await api.get<Job[]>(`/api/v1/installations/${selected}/jobs`);
    setStatus(observed); setJobs(history);
    const recent = history.find(item => ['deployment.start','deployment.stop','deployment.restart'].includes(item.action));
    if (recent) await details(recent);
    onChanged();
  }
  async function acceptJob(next: Job) {
    // Mutation responses already contain the durable job. Do not reload it and its
    // approval twice in the same interaction.
    await details(next);
    setJobs(current => [next,...current.filter(item => item.id !== next.id)]);
    setStatus(await api.get<Status>(`/api/v1/installations/${selected}/status`));
    onChanged();
  }
  function plan(action: Action) {
    if (key.current?.action !== action || key.current.installation !== selected) key.current = {action,installation:selected,value:crypto.randomUUID()};
    const requestKey = key.current.value;
    void work(async () => {
      const next = await api.request<Job>(`/api/v1/installations/${selected}/${action}`,'POST',{},undefined,requestKey);
      await acceptJob(next); setConfirmed(false);
    });
  }
  function decide() {
    if (!job || !approval || !confirmed) return;
    void work(async () => {
      await api.request(`/api/v1/approvals/${approval.id}/decision`,'POST',{subject:approval.subject,action:approval.action,resource_type:approval.resource_type,resource_id:approval.resource_id,plan_hash:approval.plan_hash,expires_at:approval.expires_at,decision:'approve'});
      await reload();
    });
  }
  function execute(suffix: 'run' | 'cancel' | 'reconcile') {
    if (!job) return;
    void work(async () => {
      await acceptJob(await api.request<Job>(`/api/v1/jobs/${job.id}/${suffix}`,'POST'));
      key.current = null; setConfirmed(false);
    });
  }
  const planView = job && 'runtime' in job.plan ? job.plan : null;
  const own = job?.requested_by === subject;
  const locked = busy || !!status?.blocked_job_id || !status;
  return <section className="runtime-manager" aria-label="Runtime verwalten">
    <span className="section-number">CONTAINERBETRIEB</span><h2>Installierte Apps verwalten.</h2>
    <p>„App öffnen“ lädt die Anwendung. Diese Aktionen steuern ihre vorhandenen Container und erhalten alle Daten.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {installations.length ? <><label htmlFor="runtime-installation">Runtime-Installation</label><select id="runtime-installation" value={selected} disabled={busy} onChange={event => setSelected(event.target.value)}>{installations.map(item => <option key={item.id} value={item.id}>{item.name} ({item.id})</option>)}</select>
      <p role="status">{status ? runtimeStates[status.state] : 'Status wird ermittelt …'}{status && <> · Gemessen: <time dateTime={status.observed_at}>{new Date(status.observed_at).toLocaleString('de-DE')}</time></>}</p>
      {status?.reason && <p className="muted">Statuscode: {status.reason}</p>}
      {status?.blocked_job_id && <p>Offener Auftrag: <code>{status.blocked_job_id}</code>. Weitere Änderungen bleiben gesperrt.</p>}
      <div className="runtime-actions">{(['start','stop','restart'] as const).map(action => <button key={action} disabled={locked} onClick={() => plan(action)}>{actions[action]}</button>)}</div>
      <button disabled={busy} onClick={() => {void work(reload);}}>Runtime neu laden</button>
      <button disabled={busy} onClick={() => {void work(async () => {setLogs(null); setLogs(await api.get<Logs>(`/api/v1/installations/${selected}/logs`));});}}>Logs anzeigen</button>
      {logs && <div><p>Letzte maximal {logs.max_lines} Zeilen / {logs.max_bytes} Bytes. Musterbasierte Maskierung erkennt keine beliebigen frei formulierten Secrets.</p><pre className="runtime-logs" aria-label="Runtime-Logs">{logs.text || 'Keine Logzeilen vorhanden.'}</pre></div>}
      {busy && <p role="status">Auftrag wird verarbeitet. Sein Zustand bleibt serverseitig gespeichert.</p>}
      {job && planView && <article className="installation-plan" aria-label="Runtimeplan">
        <h3>{states[job.state]} · {actions[planView.action]}</h3>
        <dl><dt>Installation</dt><dd>{planView.resource_id}</dd><dt>Aktion</dt><dd>{job.action}</dd><dt>Identität</dt><dd>{planView.subject}</dd><dt>App-Image</dt><dd><code>{planView.runtime.image}</code></dd><dt>Datenbank-Image</dt><dd><code>{planView.runtime.database_image}</code></dd><dt>Plan-Hash</dt><dd><code>{job.plan_hash}</code></dd><dt>Freigabe gültig bis</dt><dd>{approval && new Date(approval.expires_at).toLocaleString('de-DE')}</dd></dl>
        <details><summary>Vollständiger Plan</summary><pre className="runtime-logs">{JSON.stringify(planView,null,2)}</pre></details>
        {own && job.state === 'waiting_approval' && <><label className="approval-check"><input type="checkbox" disabled={busy} checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />Ich gebe diese Runtimeaktion für diese Installation frei.</label><button disabled={busy || !confirmed || !approval} onClick={decide}>Runtimeplan freigeben</button></>}
        {own && job.state === 'queued' && <button className="primary" disabled={busy} onClick={() => execute('run')}>Runtimeaktion ausführen</button>}
        {own && ['waiting_approval','queued'].includes(job.state) && <button disabled={busy} onClick={() => execute('cancel')}>Runtimeplan abbrechen</button>}
        {own && job.state === 'reconciliation_required' && <><p>Der Ausgang bleibt unklar. Der Abgleich prüft einen gespeicherten Enginebeleg und den Zustand aller Container. Ohne ausreichenden Nachweis bleibt die Installation gesperrt. Es wird keine Mutation wiederholt.</p><button disabled={busy} onClick={() => execute('reconcile')}>Runtimeergebnis abgleichen</button></>}
        {typeof job.result?.evidence_hash === 'string' && <p>Abschlussnachweis: <code>{job.result.evidence_hash}</code></p>}
        {job.failure_code && <p>Fehlercode: {job.failure_code}</p>}
        <p>Job: <code>{job.id}</code></p><ol aria-label="Runtime-Jobverlauf">{events.map(item => <li key={item.sequence}>{item.kind} · {new Date(item.created_at).toLocaleTimeString('de-DE')}</li>)}</ol>
      </article>}
      <details><summary>Gespeicherte Runtimeaufträge ({jobs.length})</summary><ul>{jobs.filter(item => item.action !== 'deployment.install').map(item => <li key={item.id}><button disabled={busy} onClick={() => {setConfirmed(false); void work(() => details(item));}}>{item.action} · {states[item.state]} · {item.id}</button></li>)}</ul></details>
    </> : <p>Keine für deinen Runtimebetrieb freigegebene Installation vorhanden. Operatoren benötigen eine eigene Betriebsfreigabe pro Installation.</p>}
    <button disabled={busy} onClick={() => {void work(async () => {await refresh(); await reload();});}}>Runtimefreigaben neu laden</button>
  </section>;
}
