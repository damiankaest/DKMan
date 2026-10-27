import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiClient, type Household } from './api';
import type { components } from './generated/api';
import { PlanningWizard } from './PlanningWizard';
import { ForgeWorkspaces } from './ForgeWorkspaces';

type AppRequest = components['schemas']['RequestView'];
type Plan = components['schemas']['PlanView'];
type Requirements = components['schemas']['Requirements'];
type Job = components['schemas']['JobView'];
type Approval = components['schemas']['ApprovalView'];
type JobEvent = components['schemas']['JobEventView'];
type Fields = {title: string; goal: string; features: string; entities: string; screens: string; acceptance_checks: string; deployment_requirements: string};
const empty: Fields = {title:'', goal:'', features:'', entities:'', screens:'', acceptance_checks:'', deployment_requirements:''};
const sections = {features:'Funktionen',entities:'Daten und Entitäten',screens:'Ansichten',acceptance_checks:'Abnahmekriterien',deployment_requirements:'Anforderungen an den Betrieb'} as const;
const lines = (text: string) => text.split('\n').map(line => line.trim()).filter(Boolean);
const terminal = new Set(['succeeded','failed','cancelled','expired']);
const stateLabels: Record<string, string> = {waiting_approval:'Wartet auf Freigabe',queued:'Freigabe kann abgeschlossen werden',claimed:'Wird vorbereitet',running:'Freigabe wird gespeichert',succeeded:'Planversion freigegeben',failed:'Freigabe fehlgeschlagen',cancelled:'Freigabe abgebrochen',expired:'Freigabe abgelaufen',reconciliation_required:'Freigabe konnte nicht bestätigt werden'};

function fieldsOf(value: Requirements): Fields {
  return {title:value.title,goal:value.goal,features:value.features.join('\n'),entities:(value.entities ?? []).join('\n'),screens:(value.screens ?? []).join('\n'),acceptance_checks:(value.acceptance_checks ?? []).join('\n'),deployment_requirements:(value.deployment_requirements ?? []).join('\n')};
}

function useRequestKey() {
  const pending = useRef<{signature: string; key: string} | null>(null);
  const key = (signature: string) => {
    if (pending.current?.signature !== signature) pending.current = {signature,key:crypto.randomUUID()};
    return pending.current.key;
  };
  return [key, () => {pending.current = null;}] as const;
}

function PlanReview({api, plan, subject, onApproved}: {api: ApiClient; plan: Plan; subject: string; onApproved: () => Promise<void>}) {
  const [job, setJob] = useState<Job | null>(null);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [key] = useRequestKey();

  const details = useCallback(async (next: Job) => {
    const [binding, history] = await Promise.all([
      api.get<Approval>(`/api/v1/jobs/${next.id}/approval`), api.get<JobEvent[]>(`/api/v1/jobs/${next.id}/events`),
    ]);
    setJob(next); setApproval(binding); setEvents(history);
  }, [api]);

  const load = useCallback(async () => {
    const history = await api.get<Job[]>(`/api/v1/app-plans/${plan.id}/jobs`);
    if (history[0]) await details(history[0]);
    else {setJob(null); setApproval(null); setEvents([]);}
  }, [api, plan.id, details]);

  useEffect(() => {void load().catch((cause: Error) => setError(cause.message)).finally(() => setBusy(false));}, [load]);

  async function act(work: () => Promise<void>) {
    setBusy(true); setError('');
    try {await work();} catch (cause) {setError(cause instanceof Error ? cause.message : 'Freigabe konnte nicht geladen werden.');}
    finally {setBusy(false);}
  }

  async function run() {
    if (!job) return;
    const next = await api.request<Job>(`/api/v1/jobs/${job.id}/run`, 'POST');
    await details(next);
    if (next.state === 'succeeded') await onApproved();
  }

  return <div className="plan-review" aria-label="Planfreigabe">
    <h4>Planversion zur Umsetzung freigeben</h4>
    <p>Die Freigabe hält diesen Entwurf fest. Build, Vorschau und Installation folgen später mit eigenen Freigaben.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {job && <p role="status">{stateLabels[job.state] ?? job.state}</p>}
    {!plan.approved_job_id && (!job || terminal.has(job.state)) && <button className="primary" disabled={busy} onClick={() => {void act(async () => {
      const next = await api.request<Job>(`/api/v1/app-plans/${plan.id}/approve`, 'POST', {content_hash:plan.content_hash}, undefined, key(`${plan.id}:${job?.id ?? ''}`));
      setConfirmed(false); await details(next);
    });}}>Freigabe vorbereiten</button>}
    {job?.state === 'waiting_approval' && approval && <>
      <label className="approval-check"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} />Ich gebe genau diese Planversion zur späteren Umsetzung frei.</label>
      <button className="primary" disabled={busy || !confirmed} onClick={() => {void act(async () => {
        await api.request(`/api/v1/approvals/${approval.id}/decision`, 'POST', {subject:approval.subject,action:approval.action,resource_type:approval.resource_type,resource_id:approval.resource_id,plan_hash:approval.plan_hash,expires_at:approval.expires_at,decision:'approve'});
        await details(await api.get<Job>(`/api/v1/jobs/${job.id}`));
      });}}>Planversion freigeben</button>
    </>}
    {job?.state === 'queued' && job.requested_by === subject && <button className="primary" disabled={busy} onClick={() => {void act(run);}}>Freigabe abschließen</button>}
    {job?.state === 'queued' && job.requested_by !== subject && <p>Die anfordernde Person schließt diese Freigabe in ihrer Sitzung ab.</p>}
    {job && ['waiting_approval','queued'].includes(job.state) && <button disabled={busy} onClick={() => {void act(async () => {await details(await api.request<Job>(`/api/v1/jobs/${job.id}/cancel`, 'POST'));});}}>Freigabe abbrechen</button>}
    <button className="quiet" disabled={busy} onClick={() => {void act(load);}}>Freigabestatus laden</button>
    {busy && <p role="status">Freigabe wird verarbeitet …</p>}
    {job?.failure_code && <p className="muted">Fehlercode: {job.failure_code}</p>}
    {approval && <p className="muted">Freigabe gültig bis {new Date(approval.expires_at).toLocaleString('de-DE')}</p>}
    {events.length > 0 && <details><summary>Jobverlauf</summary><ol>{events.map(item => <li key={item.sequence}>{item.kind} · {new Date(item.created_at).toLocaleString('de-DE')}</li>)}</ol></details>}
  </div>;
}

export function AppPlanning({api, subject, admin, developer = false, initialDraft}: {api: ApiClient; subject: string; admin: boolean; developer?: boolean; initialDraft?: Requirements}) {
  const [requests, setRequests] = useState<AppRequest[]>([]);
  const [households, setHouseholds] = useState<Household[]>([]);
  const [selected, setSelected] = useState<AppRequest | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [viewId, setViewId] = useState('');
  const [fields, setFields] = useState<Fields>(() => initialDraft ? fieldsOf(initialDraft) : empty);
  const [household, setHousehold] = useState('');
  const [busy, setBusy] = useState(false);
  const [wizard, setWizard] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [key, resetKey] = useRequestKey();

  const load = useCallback(async (signal?: AbortSignal) => {
    const [items, groups] = await Promise.all([api.get<AppRequest[]>('/api/v1/app-requests', signal), api.get<Household[]>('/api/v1/households', signal)]);
    if (!signal?.aborted) {setRequests(items); setHouseholds(groups);}
  }, [api]);
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).catch((cause: Error) => {if (!controller.signal.aborted) setError(cause.message);});
    return () => controller.abort();
  }, [load]);

  async function open(item: AppRequest) {
    const [current, history] = await Promise.all([api.get<AppRequest>(`/api/v1/app-requests/${item.id}`), api.get<Plan[]>(`/api/v1/app-requests/${item.id}/plans`)]);
    setWizard(false); setSelected(current); setPlans(history); setViewId(history[0]?.id ?? '');
    setFields(history[0] ? fieldsOf(history[0].document.requirements) : empty);
    setHousehold(current.household_id ?? '');
  }

  async function act(work: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try {await work();} catch (cause) {setError(cause instanceof Error ? cause.message : 'Planung konnte nicht gespeichert werden.');}
    finally {setBusy(false);}
  }

  function save(event: FormEvent) {
    event.preventDefault();
    const requirements: Requirements = {title:fields.title.trim(),goal:fields.goal.trim(),features:lines(fields.features),entities:lines(fields.entities),screens:lines(fields.screens),acceptance_checks:lines(fields.acceptance_checks),deployment_requirements:lines(fields.deployment_requirements)};
    if (Object.keys(sections).some(name => {
      const values = requirements[name as keyof typeof sections] ?? [];
      return values.length > 30 || values.some(value => value.length > 500);
    })) {setError('Bitte verwende höchstens 30 Einträge pro Feld und 500 Zeichen pro Eintrag.');return;}
    const path = selected ? `/api/v1/app-requests/${selected.id}/plans` : '/api/v1/app-requests';
    const body = selected ? {expected_revision:selected.current_revision,requirements} : {household_id:household || null,requirements};
    void act(async () => {
      if (selected) {
        await api.request<Plan>(path, 'POST', body, undefined, key(JSON.stringify({path,body})));
        await open(selected);
      } else {
        const created = await api.request<AppRequest>(path, 'POST', body, undefined, key(JSON.stringify({path,body})));
        await open(created);
      }
      await load(); setNotice('Gespeichert. Dein Entwurf bleibt auch nach einem Neustart erhalten.');
    });
  }

  const viewed = plans.find(plan => plan.id === viewId);
  const latest = viewed && viewed.revision === selected?.current_revision;
  return <section className="app-planning" aria-label="App planen">
    <span className="section-number">VON DER IDEE ZUM PLAN</span><h2>Was möchtest du bauen?</h2>
    <p className="muted">Halte deine App-Idee fest und entwickle sie Schritt für Schritt weiter. Jede Änderung bleibt als eigene Planversion erhalten.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status" className="planning-notice">{notice}</p>}
    <div className="planning-layout">
      <aside className="planning-history" aria-label="Gespeicherte App-Ideen">
        <h3>{admin ? 'App-Ideen' : 'Meine App-Ideen'}</h3>
        <button className="primary" disabled={busy} onClick={() => {resetKey();setWizard(false);setSelected(null);setPlans([]);setViewId('');setFields(empty);setHousehold('');setNotice('');setError('');}}>Neue App-Idee</button>
        {requests.length === 0 ? <p className="muted">Deine erste Idee wartet auf dich.</p> : <ul>{requests.map(item => <li key={item.id}><button className={selected?.id === item.id ? 'selected' : ''} aria-label={`${item.title}, Version ${item.current_revision}`} aria-pressed={selected?.id === item.id} disabled={busy} onClick={() => {void act(() => open(item));}}><strong>{item.title}</strong><small>Version {item.current_revision} · {new Date(item.updated_at).toLocaleDateString('de-DE')}</small></button></li>)}</ul>}
        <button className="quiet" disabled={busy} onClick={() => {void act(async () => {await load();if (selected) await open(selected);});}}>Stand neu laden</button>
      </aside>
      <div className="planning-content">
        {!wizard && <button type="button" disabled={busy} onClick={() => setWizard(true)}>Geführte Planung starten</button>}
        {wizard && <PlanningWizard api={api} initial={{title:fields.title,goal:fields.goal,features:lines(fields.features),entities:lines(fields.entities),screens:lines(fields.screens),acceptance_checks:lines(fields.acceptance_checks),deployment_requirements:lines(fields.deployment_requirements)}} onCancel={() => setWizard(false)} onApply={value => {setFields(fieldsOf(value));setWizard(false);setNotice('Entwurf übernommen. Bitte prüfen und speichern.');}} />}
        <form hidden={wizard} onSubmit={save} aria-label={selected ? 'App-Idee weiterentwickeln' : 'Neue App-Idee anlegen'}>
          <h3>{selected ? 'Deine nächste Planversion' : 'Eine neue App-Idee'}</h3>
          <p className="muted">{initialDraft && !selected ? 'Aus dem Chat übernommen. Bitte prüfe und ergänze den Entwurf vor dem Speichern.' : 'Prüfe deine Angaben vor dem Speichern.'}</p>
          <div className="planning-field"><label htmlFor="planning-title">Name der App</label><input id="planning-title" required maxLength={120} value={fields.title} disabled={busy} onChange={event => setFields({...fields,title:event.target.value})} placeholder="Zum Beispiel: Unser Garten" /></div>
          <div className="planning-field"><label htmlFor="planning-goal">Was soll die App erreichen?</label><textarea id="planning-goal" required maxLength={4000} value={fields.goal} disabled={busy} onChange={event => setFields({...fields,goal:event.target.value})} placeholder="Was möchtest du damit im Alltag einfacher machen?" /></div>
          <div className="planning-field"><label htmlFor="planning-household">Haushalt</label><select id="planning-household" value={household} disabled={busy || selected !== null} onChange={event => setHousehold(event.target.value)}><option value="">Noch keinem Haushalt zugeordnet</option>{households.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select></div>
          <p className="muted">Die Zuordnung erteilt anderen Personen noch keinen Zugriff auf deine Idee oder eine spätere App.</p>
          <div className="requirements-grid">{Object.entries(sections).map(([name,label]) => <div className="planning-field" key={name}><label htmlFor={`planning-${name}`}>{label}</label><textarea id={`planning-${name}`} required={name === 'features'} maxLength={15000} rows={3} value={fields[name as keyof Fields]} disabled={busy} onChange={event => setFields({...fields,[name]:event.target.value})} placeholder="Ein Eintrag pro Zeile, bis zu 30 Einträge" /></div>)}</div>
          <button className="primary" disabled={busy || !fields.title.trim() || !fields.goal.trim() || !fields.features.trim()} type="submit">{selected ? 'Neue Planversion speichern' : 'App-Idee speichern'}</button>
          {busy && <p role="status">Planung wird geladen oder gespeichert …</p>}
        </form>
        {viewed && <article className="planning-document" aria-label="Gespeicherter App-Plan">
          <div className="section-head"><div><span className="section-number">GESPEICHERTER ENTWURF</span><h3>{viewed.document.requirements.title}</h3></div><div className="planning-version"><label htmlFor="planning-version">Planversion</label><select id="planning-version" value={viewId} disabled={busy} onChange={event => setViewId(event.target.value)}>{plans.map(plan => <option key={plan.id} value={plan.id}>Version {plan.revision}{plan.approved_job_id ? ' · Freigegeben' : ''}</option>)}</select></div></div>
          <span className="badge">{!latest ? 'Frühere Version' : viewed.approved_job_id ? 'Freigegeben' : 'Entwurf'}</span>
          <p>{viewed.document.requirements.goal}</p>
          {Object.entries(sections).map(([name,label]) => {
            const items = viewed.document.requirements[name as keyof typeof sections] ?? [];
            return items.length > 0 && <div key={name}><h4>{label}</h4><ul>{items.map((value,index) => <li key={index}>{value}</li>)}</ul></div>;
          })}
          <details><summary>Planreferenz</summary><p>Version {viewed.revision} · Manuell · {new Date(viewed.created_at).toLocaleString('de-DE')}</p><p>Inhalts-Hash: <code>{viewed.content_hash}</code></p></details>
          {(admin || developer) && <ForgeWorkspaces key={`forge-${viewed.id}`} api={api} plan={viewed} current={Boolean(latest)} />}
          {latest && admin && <PlanReview key={`review-${viewed.id}`} api={api} plan={viewed} subject={subject} onApproved={async () => {if (selected) await open(selected);}} />}
          {latest && !admin && <p className="muted">Eine Person mit Adminrechten kann diese Planversion zur späteren Umsetzung freigeben.</p>}
        </article>}
      </div>
    </div>
  </section>;
}
