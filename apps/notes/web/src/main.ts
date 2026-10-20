import Keycloak from 'keycloak-js';
import './style.css';

const status = document.querySelector<HTMLParagraphElement>('#status')!;
const form = document.querySelector<HTMLFormElement>('form')!;
const input = document.querySelector<HTMLTextAreaElement>('#note')!;
const list = document.querySelector<HTMLElement>('#notes')!;
const identity = new Keycloak({url: `${location.origin}/auth`, realm: 'dkman', clientId: 'demo-notes'});

async function request(path: string, body?: unknown): Promise<unknown> {
  await identity.updateToken(30);
  if (!identity.token) throw new Error('Sitzung abgelaufen. Öffne Notes erneut über den Hub.');
  const response = await fetch(new URL(path, location.href), {
    method: body ? 'POST' : 'GET',
    headers: {Authorization: `Bearer ${identity.token}`, 'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined, credentials: 'omit', cache: 'no-store',
  });
  if (!response.ok) throw new Error(response.status === 401 || response.status === 403 || response.status === 404 ? 'Für diese App fehlt dir die Freigabe.' : 'Notes ist momentan nicht erreichbar. Bitte erneut versuchen.');
  return response.json();
}

async function load() {
  const notes = await request('api/notes') as {text: string; created_at: string}[];
  list.replaceChildren();
  for (const note of notes) {
    const article = document.createElement('article');
    const content = document.createElement('p'); content.textContent = note.text;
    const time = document.createElement('time'); time.dateTime = note.created_at; time.textContent = new Date(note.created_at).toLocaleString('de-DE');
    article.append(content, time); list.append(article);
  }
  status.textContent = notes.length ? `${notes.length} gemeinsame Notizen` : 'Noch keine Notizen. Schreib die erste.';
}

form.addEventListener('submit', event => {
  event.preventDefault();
  const button = form.querySelector('button')!;
  button.disabled = true;
  void request('api/notes', {text: input.value.trim()}).then(async () => {input.value = ''; await load();})
    .catch((error: Error) => {status.textContent = error.message;})
    .finally(() => {button.disabled = false;});
});

void identity.init({onLoad: 'login-required', flow: 'standard', pkceMethod: 'S256', checkLoginIframe: false, responseMode: 'fragment', redirectUri: location.origin + location.pathname})
  .then(async () => {await load(); form.hidden = false;})
  .catch(() => {status.textContent = 'Anmeldung oder App-Zugriff fehlgeschlagen. Kehre zum ServiceHub zurück und öffne die App erneut.';});
