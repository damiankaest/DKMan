import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiClient, type Household } from './api';
import type { components } from './generated/api';

type Job = components['schemas']['JobView'];
type Approval = components['schemas']['ApprovalView'];
type Preview = components['schemas']['PreviewView'];
type Installation = components['schemas']['RuntimeInstallationView'];

const states: Record<string,string> = {waiting_approval:'Wartet auf Freigabe',queued:'Freigegeben',claimed:'Wird vorbereitet',running:'Installation läuft',succeeded:'Installiert',failed:'Fehlgeschlagen',cancelled:'Abgebrochen',expired:'Freigabe abgelaufen',reconciliation_required:'Ausgang unklar – Abgleich erforderlich'};

function release(job: Job) {
  if ('replacement' in job.plan) return job.plan.replacement;
  return 'image' in job.plan ? job.plan : null;
}

export function ForgeInstall({api, preview, current, subject, requestId = ''}: {api: ApiClient; preview: Preview; current: boolean; subject: string; requestId?: string}) {
  const [open,setOpen] = useState(false);
  const [groups,setGroups] = useState<Household[]>([]);
  const [household,setHousehold] = useState('');
  const [installation,setInstallation] = useState<Installation | null>(null);
  const [job,setJob] = useState<Job | null>(null);
  const [approval,setApproval] = useState<Approval | null>(null);
  const [confirmed,setConfirmed] = useState(false);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const key = useRef<string | null>(null);

  const details = useCallback(async (next: Job) => {
    setJob(next);
    setApproval(await api.get<Approval>(`/api/v1/jobs/${next.id}/approval`));
  }, [api]);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setBusy(true); setError('');
    void Promise.all([api.get<Household[]>('/api/v1/households',controller.signal),api.get<Job[]>('/api/v1/jobs',controller.signal),api.get<Installation[]>('/api/v1/runtime/installations',controller.signal)])
      .then(async ([households,jobs,installations]) => {
        if (controller.signal.aborted) return;
        setGroups(households);
        setInstallation(installations.find(item => item.definition_id === `forge-${requestId.replaceAll('-','')}`) ?? null);
        const previous = jobs.find(item => ['deployment.install','deployment.upgrade'].includes(item.action) && item.requested_by === subject && release(item)?.forge?.preview.evidence.preview_id === preview.id);
        if (previous) await details(previous);
      })
      .catch((cause: Error) => {if (!controller.signal.aborted) setError(cause.message);})
      .finally(() => {if (!controller.signal.aborted) setBusy(false);});
    return () => controller.abort();
  }, [api,details,open,preview.id,requestId,subject]);

  async function act(work: () => Promise<void>) {
    setBusy(true); setError('');
    try {await work();} catch (cause) {setError(cause instanceof Error ? cause.message : 'Installation nicht erreichbar.');}
    finally {setBusy(false);}
  }
  const runtime = job ? release(job) : null;
  const updating = job ? job.action === 'deployment.upgrade' : Boolean(installation);
  const expired = Date.parse(preview.evidence.expires_at) <= Date.now();
  return <section aria-label={`Installation für Vorschau ${preview.id}`}>
    <button type="button" onClick={() => setOpen(value => !value)}>{open ? 'Installation schließen' : 'Installation vorbereiten'}</button>
    {open && <>
      <p>Der geprüfte Build muss zuvor im privaten Adapterbereich bereitgestellt sein. Die Vorschau ist eine frühere Messung; prüfe sie selbst, bevor du die Änderung freigibst.</p>
      {error && <p role="alert" className="error">{error}</p>}
      {busy && <p role="status">Installation wird verarbeitet …</p>}
      {(!job || ['failed','cancelled','expired'].includes(job.state)) && <>
        {installation ? <p>Update für „{installation.name}“ im bestehenden Haushalt.</p> : <><label htmlFor={`forge-household-${preview.id}`}>Haushalt</label>
        <select id={`forge-household-${preview.id}`} value={household} disabled={busy} onChange={event => {setHousehold(event.target.value); key.current = null;}}>
          <option value="">Haushalt auswählen</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}
        </select></>}
        <button type="button" disabled={busy || !current || expired || (!installation && !household)} onClick={() => {void act(async () => {
          key.current ??= crypto.randomUUID();
          const next = await api.request<Job>(`/api/v1/forge/previews/${preview.id}/${installation ? 'upgrades' : 'installations'}`,'POST',installation ? {installation_id:installation.id} : {household_id:household},undefined,key.current);
          await details(next); setConfirmed(false);
        });}}>{installation ? 'Update-Plan erstellen' : 'Installationsplan erstellen'}</button>
        {expired && <p>Der Preview-Nachweis ist abgelaufen. Starte eine neue Vorschau.</p>}
      </>}
      {job && runtime && <article aria-label="Forge-Installationsplan">
        <p role="status">{states[job.state] ?? job.state}</p>
        <dl>
          <dt>Haushalt</dt><dd>{groups.find(group => group.id === runtime.context?.household_id)?.name ?? runtime.context?.household_id}</dd>
          <dt>Image</dt><dd><code>{runtime.image}</code></dd>
          <dt>Version</dt><dd>{runtime.version}</dd>
          {job.action === 'deployment.upgrade' && 'previous' in job.plan && <><dt>Bisherige Version</dt><dd>{job.plan.previous.version}</dd></>}
          <dt>Preview</dt><dd><code>{preview.id}</code></dd>
          <dt>Ressourcen</dt><dd>{runtime.memory_mb} MiB / {runtime.cpus} CPU; kein persistentes Datenvolume und kein Hostport.</dd>
          <dt>Plan-Hash</dt><dd><code>{job.plan_hash}</code></dd>
          <dt>Freigabe gültig bis</dt><dd>{approval && new Date(approval.expires_at).toLocaleString('de-DE')}</dd>
        </dl>
        {job.state === 'waiting_approval' && approval && <>
          <label><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} />Ich habe diese Vorschau geprüft und gebe genau {updating ? 'dieses Update' : 'diese Installation'} frei.</label>
          <button type="button" disabled={busy || !confirmed} onClick={() => {void act(async () => {
            await api.request(`/api/v1/approvals/${approval.id}/decision`,'POST',{subject:approval.subject,action:approval.action,resource_type:approval.resource_type,resource_id:approval.resource_id,plan_hash:approval.plan_hash,expires_at:approval.expires_at,decision:'approve'});
            await details(await api.get<Job>(`/api/v1/jobs/${job.id}`));
          });}}>Diesen Plan freigeben</button>
        </>}
        {job.state === 'queued' && job.requested_by === subject && <button type="button" disabled={busy} onClick={() => {void act(async () => {await details(await api.request<Job>(`/api/v1/jobs/${job.id}/run`,'POST'));});}}>{updating ? 'Jetzt aktualisieren' : 'Jetzt installieren'}</button>}
        {['waiting_approval','queued'].includes(job.state) && <button type="button" disabled={busy} onClick={() => {void act(async () => {await details(await api.request<Job>(`/api/v1/jobs/${job.id}/cancel`,'POST')); key.current = null;});}}>Plan abbrechen</button>}
        {job.state === 'reconciliation_required' && <button type="button" disabled={busy} onClick={() => {void act(async () => {await details(await api.request<Job>(`/api/v1/jobs/${job.id}/reconcile`,'POST'));});}}>Ergebnis abgleichen</button>}
        {job.state === 'succeeded' && <p>{updating ? 'Die App wurde auf die neue Version aktualisiert.' : 'Die App ist installiert und erscheint unter „Meine Apps“.'}</p>}
        {job.failure_code && <p>Fehlercode: {job.failure_code}</p>}
      </article>}
    </>}
  </section>;
}
