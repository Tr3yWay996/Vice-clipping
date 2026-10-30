import {act, StrictMode} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {beforeEach, afterEach, describe, expect, it, vi} from 'vitest';
import {api} from '../lib/api';
import {connectWs} from '../lib/ws';
import type {Clip, Config, Status, WsMessage} from '../lib/types';
import {Home} from '../screens/Home';
import {StoreProvider, useStore} from './store';

vi.mock('../lib/api', () => ({
  api: {
    jobs: vi.fn(), jobControl: vi.fn(), status: vi.fn(),
    getConfig: vi.fn(),
    clips: vi.fn(),
    images: vi.fn(),
    playlists: vi.fn(),
    saveConfig: vi.fn(),
  },
}));
vi.mock('../lib/ws', () => ({connectWs: vi.fn()}));
vi.mock('../lib/env', () => ({H264_SUPPORTED: true}));
vi.mock('./clipActions', () => ({useClipActions: () => ({actions: {}, overlays: null})}));
vi.mock('../components/AppFrame', () => ({useHomeLayout: () => 'columns'}));
vi.mock('../components/HomeImages', () => ({HomeImages: () => null}));
vi.mock('../lib/clipboard', () => ({copyToClipboard: vi.fn().mockResolvedValue(true)}));

const lan: Status = {
  running: true,
  version: 'test',
  clips: 0,
  local_url: 'http://127.0.0.1:8765',
  public_url: 'http://192.168.1.23:8766',
  base_url: 'http://192.168.1.23:8766',
  public_is_tunnel: false,
  recording: true,
  backend: 'gpu-screen-recorder',
  session_active: false,
  hotkeys_available: true,
  ready: true,
  recorder_error: null,
  cpu_fallback: false,
  codec_fallback: false,
};
const active: Status = {
  ...lan,
  public_url: 'https://first-tunnel.trycloudflare.com',
  public_is_tunnel: true,
};
const config = {sharing: {cloudflare_tunnel: true}, recording: {}, hotkeys: {}} as Config;
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return {promise, resolve, reject};
}
let container: HTMLDivElement, root: Root;
let store: ReturnType<typeof useStore>;
let message: (msg: WsMessage) => void;
let lifecycle: {onOpen?: () => void; onClose?: () => void};
const disconnect = vi.fn();
function Observe() {
  store = useStore();
  return null;
}
async function mount(strict = false) {
  const app = (
    <StoreProvider>
      <Observe />
      <Home />
    </StoreProvider>
  );
  await act(async () => root.render(strict ? <StrictMode>{app}</StrictMode> : app));
}
const flush = async (fn: () => void) => {
  await act(async () => {
    fn();
  });
};
const emit = (msg: WsMessage) => flush(() => message(msg));
const readout = () => container.querySelector<HTMLButtonElement>('.tile-readout')!;
const text = () => container.textContent!;

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  localStorage.clear();
  vi.mocked(api.jobs).mockResolvedValue([]);
  vi.mocked(api.getConfig).mockResolvedValue(config);
  vi.mocked(api.clips).mockResolvedValue([]);
  vi.mocked(api.images).mockResolvedValue([]);
  vi.mocked(api.playlists).mockResolvedValue([]);
  vi.mocked(api.status).mockResolvedValue(lan);
  vi.mocked(api.saveConfig).mockResolvedValue({ok: true});
  vi.mocked(connectWs).mockImplementation((onMessage, callbacks = {}) => {
    message = onMessage;
    lifecycle = callbacks;
    return disconnect;
  });
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
});

describe('authoritative homepage public-link status', () => {
  it('does not let slow startup clip loading overwrite a newer tunnel snapshot', async () => {
    const clips = deferred<Clip[]>();
    vi.mocked(api.clips).mockReturnValue(clips.promise);
    await mount();
    expect(readout().disabled).toBe(true);
    expect(text()).toContain('Connecting');
    expect(text()).not.toContain('192.168');
    vi.mocked(api.status).mockResolvedValue(active);
    await emit({type: 'tunnel_url', url: active.public_url!});
    expect(text()).toContain('first-tunnel');
    await flush(() => clips.resolve([]));
    expect(store.state.ready).toBe(true);
    expect(text()).toContain('Public link active');
    expect(text()).toContain('first-tunnel');
    expect(readout().disabled).toBe(false);
  });

  it('closes the HTTP-to-WebSocket gap even if the tunnel event was missed', async () => {
    await mount();
    expect(text()).toContain('Connecting');
    vi.mocked(api.status).mockResolvedValue(active);
    await flush(() => lifecycle.onOpen?.());
    expect(text()).toContain('first-tunnel');
    expect(text()).not.toContain('192.168');
    expect(api.status).toHaveBeenCalledTimes(2);
  });

  it('disables stale public links while disconnected and reconciles on reconnect', async () => {
    vi.mocked(api.status).mockResolvedValue(active);
    await mount();
    await flush(() => lifecycle.onClose?.());
    expect(readout().disabled).toBe(true);
    expect(text()).toContain('Connecting');
    vi.mocked(api.status).mockResolvedValue({
      ...active,
      public_url: 'https://second-tunnel.trycloudflare.com',
    });
    await flush(() => lifecycle.onOpen?.());
    expect(text()).toContain('second-tunnel');
    expect(text()).not.toContain('first-tunnel');
    expect(readout().disabled).toBe(false);
  });

  it('ignores an older in-flight snapshot when a newer request finishes first', async () => {
    const stale = deferred<Status>();
    vi.mocked(api.status).mockReturnValueOnce(stale.promise).mockResolvedValue(active);
    await mount();
    await flush(() => lifecycle.onOpen?.());
    expect(text()).toContain('first-tunnel');
    await flush(() => stale.resolve(lan));
    expect(text()).toContain('first-tunnel');
  });

  it('resnapshots when a live status event races a pending HTTP response', async () => {
    const stale = deferred<Status>();
    vi.mocked(api.status).mockReturnValueOnce(stale.promise).mockResolvedValue(active);
    await mount();
    await emit({type: 'status', ...active});
    expect(text()).toContain('first-tunnel');
    await flush(() => stale.resolve(lan));
    expect(text()).toContain('first-tunnel');
    expect(api.status).toHaveBeenCalledTimes(2);
  });

  it('uses subsequent status frames and keeps partial recording updates from clearing the URL', async () => {
    await mount();
    await emit({type: 'status', ...active});
    await emit({type: 'status', recording: false});
    expect(text()).toContain('first-tunnel');
    expect(store.state.status.recording).toBe(false);
    await emit({type: 'status', ...lan});
    expect(readout().disabled).toBe(true);
    expect(text()).not.toContain('192.168');
  });

  it('refreshes URL changes and share-link notifications without restarting the interface', async () => {
    vi.mocked(api.status).mockResolvedValue(active);
    await mount();
    vi.mocked(api.status).mockResolvedValue({
      ...active,
      public_url: 'https://replacement.trycloudflare.com',
    });
    await emit({type: 'tunnel_url', url: 'https://replacement.trycloudflare.com'});
    expect(text()).toContain('replacement');
    vi.mocked(api.status).mockResolvedValue({...active, public_url: 'https://custom.example.com'});
    await emit({type: 'share_links_changed', links: {}, share_is_public: true});
    expect(text()).toContain('custom.example.com');
  });

  it('distinguishes connecting, failed/local-only, active and disabled states', async () => {
    await mount();
    expect(text()).toContain('Connecting');
    await emit({type: 'tunnel_error', error: 'unavailable'});
    expect(text()).toContain('Local only');
    expect(readout().disabled).toBe(true);
    vi.mocked(api.status).mockResolvedValue(active);
    await emit({type: 'tunnel_url', url: active.public_url!});
    expect(text()).toContain('Public link active');
    vi.mocked(api.status).mockResolvedValue(lan);
    await act(async () => {
      await store.saveConfig({sharing: {cloudflare_tunnel: false}});
    });
    expect(text()).toContain('Local only');
    expect(text()).not.toContain('first-tunnel');
  });

  it('never enables copying a LAN URL even with a stale true public flag', async () => {
    vi.mocked(api.status).mockResolvedValue({...lan, public_is_tunnel: true});
    await mount();
    expect(readout().disabled).toBe(true);
    expect(text()).not.toContain('192.168');
  });

  it('ignores responses from a connection that has since closed', async () => {
    const pending = deferred<Status>();
    vi.mocked(api.status).mockReturnValue(pending.promise);
    await mount();
    await flush(() => lifecycle.onClose?.());
    await flush(() => pending.resolve(active));
    expect(readout().disabled).toBe(true);
    expect(text()).not.toContain('first-tunnel');
  });

  it('recovers failed reconciliation on focus and visibility, with no timer polling', async () => {
    vi.mocked(api.status).mockRejectedValueOnce(new Error('offline'));
    await mount();
    expect(readout().disabled).toBe(true);
    vi.mocked(api.status).mockResolvedValue(active);
    await flush(() => window.dispatchEvent(new Event('focus')));
    expect(text()).toContain('first-tunnel');
    await flush(() => document.dispatchEvent(new Event('visibilitychange')));
    const calls = vi.mocked(api.status).mock.calls.length;
    await flush(() => vi.advanceTimersByTime(120_000));
    expect(api.status).toHaveBeenCalledTimes(calls);
  });

  it('preserves the session clock on resync and cleans up StrictMode subscriptions', async () => {
    vi.mocked(api.status).mockResolvedValue({...active, session_active: true});
    await mount(true);
    const started = store.state.sessionStartedAt;
    await flush(() => vi.advanceTimersByTime(1000));
    await flush(() => lifecycle.onOpen?.());
    expect(store.state.sessionStartedAt).toBe(started);
    expect(disconnect).toHaveBeenCalledTimes(1);
  });
});

describe('processing queue snapshots', () => {
  it('recovers jobs after reconnect and ignores snapshots older than a job event', async () => {
    const old = deferred<import('../lib/types').ProcessingJob[]>();
    vi.mocked(api.jobs).mockReturnValueOnce(old.promise).mockResolvedValue([]);
    await mount();
    const job = {id:'job', name:'clip', status:'processing', operation:'trim', progress:.4, can_pause:true, stage:'encode'} as import('../lib/types').ProcessingJob;
    await emit({type:'jobs_changed',jobs:[job]});
    await flush(()=>old.resolve([]));
    expect(store.state.jobs).toHaveLength(1);expect(store.state.jobs[0].progress).toBe(.4);
    vi.mocked(api.jobs).mockResolvedValue([{...job,status:'completed',progress:1}]);
    await flush(()=>lifecycle.onClose?.());await flush(()=>lifecycle.onOpen?.());
    expect(store.state.jobs[0].status).toBe('completed');
  });

  it('defaults to the queue and switches to Images without restarting status or jobs', async () => {
    await mount();expect(container.querySelector('.processing-queue')).not.toBeNull();
    await act(async()=>{await store.saveConfig({ui:{home_side_panel:'images'}});});
    expect(container.querySelector('.processing-queue')).toBeNull();
    expect(api.saveConfig).toHaveBeenCalledWith({ui:{home_side_panel:'images'}});
  });
});
