import { useEffect, useState } from 'react';
import { ApiClient } from './api';
import type { components } from './generated/api';
import { ForgeInstall } from './ForgeInstall';

type Preview = components['schemas']['PreviewView'];
type SignedPreview = components['schemas']['SignedPreviewEvidence'];

export function ForgePreviews({api, artifactId, current, admin = false, subject = '', installable = false}: {api: ApiClient; artifactId: string; current: boolean; admin?: boolean; subject?: string; installable?: boolean}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Preview[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const path = `/api/v1/forge/build-artifacts/${artifactId}/previews`;

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setBusy(true); setError('');
    void api.get<Preview[]>(path, controller.signal)
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
      const proof = JSON.parse(await file.text()) as SignedPreview;
      const result = await api.request<Preview>(path,'POST',proof);
      setItems(previous => [result,...previous.filter(item => item.id !== result.id)]);
      setFile(null); setNotice('Vorschau-Nachweis geprüft und gespeichert.');
    } catch (cause) {setError(cause instanceof Error ? cause.message : 'Vorschau-Nachweis konnte nicht geprüft werden.');}
    finally {setBusy(false);}
  }

  return <section aria-label={`Vorschau-Nachweise ${artifactId}`}>
    <button type="button" onClick={() => setOpen(value => !value)}>{open ? 'Vorschau-Nachweise schließen' : 'Vorschau-Nachweise öffnen'}</button>
    {open && <>
      <p>Starte die Vorschau auf der isolierten Vorschau-VM und importiere deren Datei <code>preview-attestation.json</code>. Der separate Vertrauensschlüssel muss eingerichtet sein.</p>
      {error && <p role="alert" className="error">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {busy && <p role="status">Vorschau-Nachweis wird geprüft …</p>}
      <label htmlFor={`preview-proof-${artifactId}`}>Signierter Vorschau-Nachweis</label>
      <input id={`preview-proof-${artifactId}`} type="file" accept="application/json,.json" disabled={busy || !current} onChange={event => setFile(event.target.files?.[0] ?? null)} />
      <button type="button" disabled={busy || !current || !file} onClick={() => {void register();}}>Vorschau-Nachweis prüfen</button>
      {items.length === 0 && !busy ? <p>Für diesen Build liegt noch kein Vorschau-Nachweis vor.</p> : <ul>{items.map(item => <li key={item.id}>
        Vorschau bei der Prüfung erreichbar: {new Date(item.evidence.observed_at).toLocaleString('de-DE')}.
        <p>Nachweis gültig bis {new Date(item.evidence.expires_at).toLocaleString('de-DE')}.</p>
        {admin && installable && <ForgeInstall api={api} preview={item} current={current} subject={subject} />}
      </li>)}</ul>}
      <p>Dies belegt eine frühere Messung; es ist keine Anzeige des aktuellen Zustands und keine Installationsfreigabe.</p>
    </>}
  </section>;
}
