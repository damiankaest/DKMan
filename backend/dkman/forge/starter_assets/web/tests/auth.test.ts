import { describe, expect, it } from 'vitest';
import { appBase } from '../src/auth';
describe('app routing', () => {
  it('keeps the UUID installation route for the login redirect', () => {
    expect(appBase('/run/12345678-1234-1234-1234-123456789abc/')).toBe('/run/12345678-1234-1234-1234-123456789abc/');
    expect(appBase('/untrusted/path')).toBe('/');
    expect(appBase('/run/------------------------------------/')).toBe('/');
  });
});
