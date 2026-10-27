import { useEffect, useState } from 'react';
import { appBase, identity } from './auth';

export default function App() {
  const [message, setMessage] = useState('Anmeldung wird geprüft …');
  const [login, setLogin] = useState<(() => Promise<void>) | null>(null);
  useEffect(() => {
    let active = true;
    const client = identity();
    const redirectUri = window.location.origin + appBase(window.location.pathname);
    void client.init({onLoad:'check-sso', pkceMethod:'S256', flow:'standard', responseMode:'fragment', checkLoginIframe:false, redirectUri})
      .then(authenticated => {
        if (!active) return;
        if (authenticated) {
          void (async () => {
            try {
              const base = appBase(window.location.pathname);
              const match = base.match(/^\/run\/([0-9a-f-]{36})\/$/);
              if (!match) throw new Error('Installation fehlt');
              await client.updateToken(30);
              if (!client.token) throw new Error('Sitzung abgelaufen');
              const response = await fetch(`/api/v1/apps/${match[1]}/access`, {headers:{Authorization:`Bearer ${client.token}`}, cache:'no-store'});
              if (!response.ok) throw new Error('Zugriff verweigert');
              if (active) setMessage('Angemeldet und freigegeben. Die App kann weiterentwickelt werden.');
            } catch {if (active) setMessage('App-Zugriff konnte nicht bestätigt werden.');}
          })();
        }
        else {setMessage('Bitte melde dich an.');setLogin(() => async () => {await client.login({redirectUri});});}
      }).catch(() => {if (active) setMessage('Anmeldung nicht erreichbar. Bitte OIDC-Konfiguration prüfen.');});
    return () => {active = false;};
  }, []);
  return <main><h1>DKMan App</h1><p role="status">{message}</p>{login && <button onClick={() => {void login();}}>Anmelden</button>}</main>;
}
