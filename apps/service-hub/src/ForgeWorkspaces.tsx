import { useEffect, useRef, useState } from 'react';
import { ApiClient } from './api';
import type { components } from './generated/api';
import { ForgeBuildArtifacts } from './ForgeBuildArtifacts';

type Plan = components['schemas']['PlanView'];
type Workspace = components['schemas']['WorkspaceView'];
type Template = components['schemas']['WorkspaceInput']['template'];

export function ForgeWorkspaces({api, plan, current, admin = false, subject = ''}: {api: ApiClient; plan: Plan; current: boolean; admin?: boolean; subject?: string}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Workspace[]>([]);
  const [template, setTemplate] = useState<Template>('fullstack-fastapi-react');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const key = useRef<{signature: string; value: string} | null>(null);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setBusy(true); setError('');
    void api.get<Workspace[]>(`/api/v1/app-plans/${plan.id}/workspaces`, controller.signal)
      .then(value => {if (!controller.signal.aborted) setItems(value);})
      .catch((cause: Error) => {if (!controller.signal.aborted) setError(cause.message);})
      .finally(() => {if (!controller.signal.aborted) setBusy(false);});
    return () => controller.abort();
  }, [api,open,plan.id]);
  async function create() {
    const body = {template, content_hash:plan.content_hash};
    const signature = JSON.stringify({plan:plan.id,body});
    if (key.current?.signature !== signature) key.current = {signature,value:crypto.randomUUID()};
    setBusy(true); setError(''); setNotice('');
    try {
      const created = await api.request<Workspace>(`/api/v1/app-plans/${plan.id}/workspaces`, 'POST', body, undefined, key.current.value);
      setItems(currentItems => [created,...currentItems.filter(item => item.id !== created.id)]);
      key.current = null;
      setNotice('Quellstand gespeichert. Du kannst ihn jetzt herunterladen und prüfen.');
    } catch (cause) {setError(cause instanceof Error ? cause.message : 'Quellstand konnte nicht erstellt werden.');}
    finally {setBusy(false);}
  }
  async function download(item: Workspace) {
    setBusy(true); setError('');
    try {
      const blob = await api.download(`/api/v1/forge/workspaces/${item.id}/archive`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = `dkman-workspace-${item.id}.zip`;
      document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {setError(cause instanceof Error ? cause.message : 'Download fehlgeschlagen.');}
    finally {setBusy(false);}
  }
  return <section className="forge-workspaces" aria-label="App-Quellstände">
    <h4>App-Quellcode vorbereiten</h4>
    <p>Erstelle aus einem freigegebenen Plan einen gespeicherten Quellstand. Ein isolierter Worker kann die Vorlage prüfen und ein Image bauen. Die React-Vorlage kann nach einer Vorschau separat zur Installation freigegeben werden.</p>
    <button type="button" onClick={() => setOpen(!open)}>{open ? 'Quellstände schließen' : 'Quellstände öffnen'}</button>
    {open && <>
      {error && <p role="alert" className="error">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {busy && <p role="status">Quellstand wird verarbeitet …</p>}
      <label htmlFor="forge-template">Vorlage</label>
      <select id="forge-template" value={template} disabled={busy} onChange={event => setTemplate(event.target.value as Template)}>
        <option value="fullstack-fastapi-react">Fullstack: FastAPI und React</option>
        <option value="python-api">Python-API</option>
        <option value="react-spa">React-Oberfläche</option>
      </select>
      <button type="button" className="primary" disabled={busy || !current || !plan.approved_job_id} onClick={() => {void create();}}>Quellstand erstellen</button>
      {(!current || !plan.approved_job_id) && <p>Nur die aktuelle, freigegebene Planversion kann als Grundlage verwendet werden.</p>}
      {items.length === 0 && !busy ? <p>Noch keine Quellstände für diese Planversion.</p> : <ul>{items.map(item => <li key={item.id}>
        <strong>{item.template}</strong> · {new Date(item.created_at).toLocaleString('de-DE')}
        <button type="button" disabled={busy} onClick={() => {void download(item);}}>ZIP herunterladen</button>
        <details><summary>Dateien und Prüfsumme</summary><p>Quellstand-ID: <code>{item.id}</code></p><p>Prüfsumme: <code>{item.bundle_hash}</code></p><ul>{item.files.map(file => <li key={file}>{file}</li>)}</ul></details>
        <ForgeBuildArtifacts api={api} workspaceId={item.id} requestId={plan.request_id} current={current && !!plan.approved_job_id} admin={admin} subject={subject} />
      </li>)}</ul>}
    </>}
  </section>;
}
