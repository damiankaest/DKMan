import Keycloak from 'keycloak-js';

// The client is public; register its exact redirects before use. No tokens are persisted.
export function appBase(pathname: string): string {
  const match = pathname.match(/^\/run\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\//);
  return match ? `/run/${match[1]}/` : '/';
}
export function identity() {
  return new Keycloak({url: `${window.location.origin}/auth`, realm:'dkman', clientId:'generated-app'});
}
