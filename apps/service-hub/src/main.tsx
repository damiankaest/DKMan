import { createRoot } from 'react-dom/client';
import { App } from './App';
import { initializeAuth } from './auth';

const root = createRoot(document.getElementById('root')!);
root.render(<p role="status">DKMan wird geladen …</p>);
initializeAuth().then(auth => root.render(<App auth={auth} />)).catch(() => {
  root.render(<main className="welcome"><h1>Anmeldung nicht erreichbar</h1><p>Prüfe mit dem Doctor-Skript, ob Keycloak und der Reverse Proxy laufen.</p><a href="/">Erneut versuchen</a></main>);
});
