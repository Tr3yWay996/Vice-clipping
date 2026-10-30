import type {Status} from './types';

/** The backend's reachable flag covers tunnels and configured public origins.
 * A LAN bind URL is still returned as public_url when neither is available.
 */
export function publicInternetUrl(status: Status): string | null {
  if (!status.public_is_tunnel || !status.public_url) return null;
  try {
    const url = new URL(status.public_url);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    const host = url.hostname.toLowerCase().replace(/\.$/, '');
    if (host.startsWith('[')) {
      // IPv4-mapped addresses are rejected as well as loopback/link-local/ULA.
      if (/^\[(?:::|fc|fd|fe[89ab])/i.test(host)) return null;
    } else if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
      const [a, b] = host.split('.').map(Number);
      if (
        a === 0 ||
        a === 10 ||
        a === 127 ||
        a >= 224 ||
        (a === 169 && b === 254) ||
        (a === 172 && b >= 16 && b <= 31) ||
        (a === 192 && b === 168) ||
        (a === 100 && b >= 64 && b <= 127)
      )
        return null;
    } else if (!host.includes('.') || /\.(localhost|localdomain|local|lan|internal)$/.test(host))
      return null;
    return status.public_url;
  } catch {
    return null;
  }
}

export function publicLinkState(
  status: Status,
  synced: boolean,
  enabled: boolean,
  failed: boolean,
) {
  const url = synced ? publicInternetUrl(status) : null;
  return {
    url,
    phase: url ? 'active' : !synced || (enabled && !failed) ? 'connecting' : 'local',
  } as const;
}
