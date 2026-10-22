import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiClient } from './api';
import type { components } from './generated/api';

type Reply = components['schemas']['ChatView'];
type Provider = components['schemas']['ProviderView'];
export type Proposal = NonNullable<Reply['proposal']>;
type Turn = {id: number; message: string; reply?: Reply; error?: string};
const examples = ['Zeige meine Apps', 'Suche Dienste', 'Zeige Jobs', 'Plane eine Garten-App mit Pflanzen und Fotos'];
const states: Record<string,string> = {waiting_approval:'Wartet auf Freigabe',queued:'Freigegeben',claimed:'Wird vorbereitet',running:'Läuft',succeeded:'Erfolgreich',failed:'Fehlgeschlagen',cancelled:'Abgebrochen',expired:'Abgelaufen',reconciliation_required:'Abgleich erforderlich'};
const health: Record<string,string> = {healthy:'Bereit',starting:'Startet',degraded:'Eingeschränkt',unhealthy:'Gestört',stopped:'Gestoppt',unknown:'Unbekannt'};
const actions = {start:'Start',stop:'Stop',restart:'Neustart'};

export function Chat({api, onProposal}: {api: ApiClient; onProposal: (proposal: Proposal) => void}) {
  const [provider, setProvider] = useState<Provider | null>(null);
  const [message, setMessage] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const sequence = useRef(0);
  const pending = useRef(false);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    const abort = new AbortController();
    void api.get<Provider>('/api/v1/chat/config', abort.signal).then(setProvider).catch((cause: Error) => {if (!abort.signal.aborted) setError(cause.message);});
    return () => {abort.abort();controller.current?.abort();};
  }, [api]);

  async function send(text: string) {
    if (!text.trim() || pending.current || !provider) return;
    pending.current = true;setBusy(true);setError('');setMessage('');
    const id = ++sequence.current;
    setTurns(current => [...current.slice(-19),{id,message:text}]);
    const abort = new AbortController();controller.current = abort;
    try {
      const reply = await api.request<Reply>('/api/v1/chat', 'POST', {message:text}, abort.signal);
      if (!abort.signal.aborted) {setProvider(reply.provider);setTurns(current => current.map(turn => turn.id === id ? {...turn,reply} : turn));}
    } catch (cause) {
      if (!abort.signal.aborted) {setMessage(text);setTurns(current => current.map(turn => turn.id === id ? {...turn,error:cause instanceof Error ? cause.message : 'Anfrage fehlgeschlagen.'} : turn));}
    } finally {pending.current = false;if (!abort.signal.aborted) setBusy(false);}
  }

  function submit(event: FormEvent) {event.preventDefault();void send(message);}

  return <section className="chat" aria-label="DKMan Chat">
    <div className="section-head"><div><span className="section-number">DEIN ASSISTENT IM HUB</span><h2>Was möchtest du tun?</h2></div><span className="chat-mode">{provider?.label ?? 'Chat wird geladen …'}</span></div>
    <p className="muted">{provider?.notice}</p>
    <p>Finde berechtigte Apps und Dienste, frage Jobstände ab oder bereite eine App-Idee vor. Änderungen prüfst und bestätigst du im jeweiligen Plan.</p>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="chat-examples" aria-label="Beispielaufträge">{examples.map(text => <button key={text} disabled={busy || !provider} onClick={() => {void send(text);}}>{text}</button>)}</div>
    <div className="chat-transcript" role="log" aria-label="Chatverlauf" aria-live="polite" aria-relevant="additions text">
      {!turns.length && <div className="chat-empty"><span aria-hidden="true">✦</span><h3>Ein Auftrag, ein klarer nächster Schritt.</h3><p>Beginne mit einem Beispiel oder beschreibe deine Idee.</p></div>}
      {turns.map(turn => <article className="chat-turn" key={turn.id}>
        <p className="chat-question"><strong>Du</strong>{turn.message}</p>
        {turn.error && <p role="alert" className="error">{turn.error}</p>}
        {turn.reply && <div className="chat-answer"><span className="section-number">DKMAN · {turn.reply.provider.label}</span><p>{turn.reply.summary}</p>
          {turn.reply.apps?.map(app => <div className="chat-result" key={app.id}><h3>{app.name}</h3><p>{app.description}</p><p>Zum Messzeitpunkt: {health[app.status]} · {app.checked_at ? `Messung: ${new Date(app.checked_at).toLocaleString('de-DE')}` : 'Noch keine Messung'}</p><small>{app.id}</small></div>)}
          {turn.reply.registry?.map(item => <div className="chat-result" key={item.id}><h3>{item.name} <small>{item.version}</small></h3><p>{item.description}</p><p className="muted">Berechtigte Fähigkeiten: {item.capabilities.join(', ') || 'Keine'}</p><small>{item.id}</small></div>)}
          {turn.reply.jobs?.map(job => <div className="chat-result" key={job.id}><h3>{states[job.state]} · {job.action}</h3><small>{job.id}</small><ol aria-label="Jobereignisse">{job.events.map(event => <li key={event.sequence}>{event.kind} · {states[event.state]} · {new Date(event.created_at).toLocaleTimeString('de-DE')}</li>)}</ol></div>)}
          {turn.reply.proposal && <ProposalCard proposal={turn.reply.proposal} onOpen={onProposal} />}
          <p className="muted">Stand: <time dateTime={turn.reply.observed_at}>{new Date(turn.reply.observed_at).toLocaleString('de-DE')}</time></p>
        </div>}
      </article>)}
    </div>
    {busy && <p role="status">Auftrag wird eingeordnet …</p>}
    <form className="chat-composer" onSubmit={submit} aria-label="Chatnachricht senden"><label htmlFor="chat-message">Dein Auftrag</label><textarea id="chat-message" required maxLength={4000} rows={3} value={message} disabled={busy} onChange={event => setMessage(event.target.value)} placeholder="Zum Beispiel: Plane eine Garten-App mit Pflanzen und Fotos" /><div><span className="muted">Jede Nachricht steht für sich. Verlauf nur in diesem geöffneten Hub; Entwürfe separat speichern.</span><button className="primary" disabled={busy || !provider || !message.trim()}>Senden</button></div></form>
  </section>;
}

function ProposalCard({proposal, onOpen}: {proposal: Proposal; onOpen: (proposal: Proposal) => void}) {
  return <div className="chat-proposal" aria-label="Vorschlag prüfen">
    {proposal.kind === 'app.draft' ? <><h3>{proposal.requirements.title}</h3><ul>{proposal.requirements.features.map((item,index) => <li key={index}>{item}</li>)}</ul><button className="primary" onClick={() => onOpen(proposal)}>Entwurf in App-Planung prüfen</button></> : proposal.kind === 'runtime' ? <><h3>{actions[proposal.action]} für {proposal.name}</h3><p><code>{proposal.installation_id}</code></p><button onClick={() => onOpen(proposal)}>Im Containerbetrieb prüfen</button></> : <><h3>{proposal.name} · {proposal.version}</h3><button onClick={() => onOpen(proposal)}>Installation planen</button></>}
  </div>;
}
