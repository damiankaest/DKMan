import Keycloak from 'keycloak-js';

// The public issuer matches the reverse proxy. No tokens or secrets in Web Storage.
export const identity = new Keycloak({
  url: `${window.location.origin}/auth`,
  realm: 'dkman',
  clientId: 'service-hub',
});

export interface AuthSession {
  authenticated: boolean;
  login(): Promise<void>;
  logout(): Promise<void>;
  token(): Promise<string>;
}

export async function initializeAuth(): Promise<AuthSession> {
  if (new URLSearchParams(window.location.search).has('error')) {
    throw new Error('Anmeldung wurde vom Identity-Provider abgelehnt.');
  }
  await identity.init({
    pkceMethod: 'S256',
    flow: 'standard',
    checkLoginIframe: false,
    responseMode: 'fragment',
  });
  return {
    authenticated: identity.authenticated === true,
    login: () => identity.login({ redirectUri: window.location.origin + '/' }),
    logout: () => identity.logout({ redirectUri: window.location.origin + '/' }),
    async token() {
      await identity.updateToken(30);
      if (!identity.token) throw new Error('Sitzung abgelaufen. Bitte erneut anmelden.');
      return identity.token;
    },
  };
}
