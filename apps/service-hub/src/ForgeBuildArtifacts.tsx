import { useEffect, useState } from 'react';
import { ApiClient } from './api';
import type { components } from './generated/api';
import { ForgePreviews } from './ForgePreviews';

type Artifact = components['schemas']['BuildArtifactView'];
type SignedEvidence = components['schemas']['SignedBuildEvidence'];

export function ForgeBuildArtifacts({api, workspaceId, current, admin = false, subject = '', requestId = ''}: {api: ApiClient; workspaceId: string; current: boolean; admin?: boolean; subject?: string; requestId?: string}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Artifact[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const path = `/api/v1/forge/workspaces/${workspaceId}/build-artifacts`;

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setBusy(true); setError('');
    void api.get<Artifact[]>(path, controller.signal)
      .then(value => {if (!controller.signal.aborted) setItems(value);})
      .catch((cause: Error) => {if (!controller.signal.aborted) setError(cause.message);})
      .finally(() => {if (!controller.signal.aborted) setBusy(false);});
    return () => controller.abort();
  }, [api,open,path]);

  async function register() {
    if (!file || !current) return;
    setBusy(true); setError(''); setNotice('');
    try {
      if (file.size > 16_384) throw new Error('Die Nachweisdatei ist zu groß.');
      const signed = JSON.parse(await file.text()) as SignedEvidence;
      const result = await api.request<Artifact>(path, 'POST', signed);
      setItems(previous => [result,...previous.filter(item => item.id !== result.id)]);
      setNotice('Build-Nachweis geprüft und gespeichert. Das Image bleibt auf dem Builder.');
      setFile(null);
    } catch (cause) {setError(cause instanceof Error ? cause.message : 'Build-Nachweis konnte nicht geprüft werden.');}
    finally {setBusy(false);}
  }

  return <section className="forge-artifacts" aria-label={`Build-Nachweise ${workspaceId}`}>
    <button type="button" onClick={() => setOpen(value => !value)}>{open ? 'Build-Nachweise schließen' : 'Build-Nachweise öffnen'}</button>
    {open && <>
      <p>Importiere die signierte Datei <code>build-attestation.json</code> vom isolierten Builder. Der Vertrauensschlüssel muss im Core eingerichtet sein.</p>
      {error && <p role="alert" className="error">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {busy && <p role="status">Build-Nachweis wird geprüft …</p>}
      <label htmlFor={`forge-proof-${workspaceId}`}>Signierter Build-Nachweis</label>
      <input id={`forge-proof-${workspaceId}`} type="file" accept="application/json,.json" disabled={busy || !current} onChange={event => setFile(event.target.files?.[0] ?? null)} />
      <button type="button" disabled={busy || !current || !file} onClick={() => {void register();}}>Build-Nachweis prüfen</button>
      {!current && <p>Für neue Build-Nachweise ist eine aktuelle, freigegebene Planversion erforderlich.</p>}
      {items.length === 0 && !busy ? <p>Für diesen Quellstand liegt noch kein geprüfter Build-Nachweis vor.</p> : <ul>{items.map(item => <li key={item.id}>
        <strong>{item.evidence.template}</strong> · {new Date(item.evidence.finished_at).toLocaleString('de-DE')}
        <p>Image-Digest: <code>{item.evidence.manifest_digest}</code></p>
        <p>Checks: {item.evidence.checks.join(', ')}</p>
        <ForgePreviews api={api} artifactId={item.id} requestId={requestId} current={current} admin={admin} subject={subject} installable={item.evidence.template === 'react-spa'} />
      </li>)}</ul>}
      <p>Ein geprüfter Build-Nachweis ist noch keine Vorschau oder Installationsfreigabe.</p>
    </>}
  </section>;
}
