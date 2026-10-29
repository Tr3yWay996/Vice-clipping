import {describe, expect, it} from 'vitest';
import {publicInternetUrl, publicLinkState} from './publicLink';
import type {Status} from './types';
const status = (url: string, reachable = true) =>
  ({public_url: url, public_is_tunnel: reachable}) as Status;

describe('public internet link classification', () => {
  it.each([
    'http://192.168.1.2:8766',
    'http://10.0.0.2',
    'http://172.16.0.1',
    'http://172.31.255.254',
    'http://127.0.0.1',
    'http://localhost',
    'http://localhost.localdomain',
    'http://vice.local',
    'http://169.254.1.1',
    'http://100.64.0.1',
    'http://[::1]',
    'http://[::ffff:192.168.1.1]',
    'http://[fd00::1]',
    'http://[fe80::1]',
    'javascript:alert(1)',
    'broken',
    'https://user:pass@example.com',
  ])('rejects %s', url => {
    expect(publicInternetUrl(status(url))).toBeNull();
  });
  it('requires the authoritative flag and preserves configured public origins', () => {
    expect(publicInternetUrl(status('https://valid.trycloudflare.com', false))).toBeNull();
    expect(publicInternetUrl(status('https://valid.trycloudflare.com'))).toBe(
      'https://valid.trycloudflare.com',
    );
    expect(publicInternetUrl(status('https://clips.example.com'))).toBe(
      'https://clips.example.com',
    );
    expect(publicInternetUrl(status('http://8.8.8.8:8766'))).toBe('http://8.8.8.8:8766');
  });
  it('does not advertise unsynchronized public state', () => {
    expect(
      publicLinkState(status('https://valid.trycloudflare.com'), false, true, false).phase,
    ).toBe('connecting');
    expect(publicLinkState(status('http://192.168.1.2', false), true, false, false).phase).toBe(
      'local',
    );
  });
});
