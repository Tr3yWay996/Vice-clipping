import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {connectWs, onWsMessage} from './ws';

class Socket {
  static all: Socket[] = [];
  static fail = false;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: {data: string}) => void) | null = null;
  close = vi.fn();
  constructor(public url: string) {
    if (Socket.fail) throw new Error('offline');
    Socket.all.push(this);
  }
}
beforeEach(() => {
  vi.useFakeTimers();
  Socket.all = [];
  Socket.fail = false;
  vi.stubGlobal('WebSocket', Socket);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('WebSocket subscription lifecycle', () => {
  it('notifies on every successful connection so missed events can be reconciled', () => {
    const onOpen = vi.fn(),
      onClose = vi.fn(),
      onMessage = vi.fn();
    const cleanup = connectWs(onMessage, {onOpen, onClose});
    Socket.all[0].onopen?.();
    expect(onOpen).toHaveBeenCalledTimes(1);
    Socket.all[0].onerror?.();
    Socket.all[0].onclose?.();
    expect(onClose).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(3000);
    expect(Socket.all).toHaveLength(2);
    Socket.all[1].onopen?.();
    expect(onOpen).toHaveBeenCalledTimes(2);
    Socket.all[1].onmessage?.({
      data: JSON.stringify({type: 'tunnel_url', url: 'https://new.trycloudflare.com'}),
    });
    expect(onMessage).toHaveBeenCalledWith({
      type: 'tunnel_url',
      url: 'https://new.trycloudflare.com',
    });
    cleanup();
  });

  it('uses secure WebSockets for an HTTPS interface', () => {
    vi.stubGlobal('location', {protocol: 'https:', host: 'vice.example.com'});
    const cleanup = connectWs(vi.fn());
    expect(Socket.all[0].url).toBe('wss://vice.example.com/ws');
    cleanup();
  });

  it('cancels queued reconnects and ignores late frames or open events after disposal', () => {
    const onMessage = vi.fn(),
      onOpen = vi.fn();
    const cleanup = connectWs(onMessage, {onOpen});
    const socket = Socket.all[0];
    socket.onclose?.();
    cleanup();
    vi.advanceTimersByTime(9000);
    socket.onopen?.();
    socket.onmessage?.({data: '{"type":"config_changed"}'});
    expect(Socket.all).toHaveLength(1);
    expect(onOpen).not.toHaveBeenCalled();
    expect(onMessage).not.toHaveBeenCalled();
    expect(socket.close).toHaveBeenCalledTimes(1);
  });

  it('preserves shared export listeners and recovers from unreadable messages', () => {
    const onMessage = vi.fn(),
      extra = vi.fn();
    const stopExtra = onWsMessage(extra),
      cleanup = connectWs(onMessage);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    Socket.all[0].onmessage?.({data: 'bad JSON'});
    Socket.all[0].onmessage?.({data: '{"type":"export_progress","progress":0.5}'});
    expect(onMessage).toHaveBeenCalledTimes(1);
    expect(extra).toHaveBeenCalledTimes(1);
    stopExtra();
    Socket.all[0].onmessage?.({data: '{"type":"export_done"}'});
    expect(extra).toHaveBeenCalledTimes(1);
    cleanup();
    warn.mockRestore();
  });

  it('retries a construction failure without leaking a reconnect after cleanup', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    Socket.fail = true;
    const cleanup = connectWs(vi.fn());
    Socket.fail = false;
    vi.advanceTimersByTime(3000);
    expect(Socket.all).toHaveLength(1);
    cleanup();
    vi.advanceTimersByTime(9000);
    expect(Socket.all).toHaveLength(1);
    warn.mockRestore();
  });
});
