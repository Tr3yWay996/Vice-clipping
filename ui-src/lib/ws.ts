import type {WsMessage} from './types';

/**
 * Extra listeners on the same socket, for messages the store does not keep.
 *
 * Export progress is the only one: it belongs to whichever screen started the
 * render, arrives many times a second, and would otherwise re-render the whole
 * app through the store for a progress bar nobody else is watching.
 */
const extra = new Set<(msg: WsMessage) => void>();

export function onWsMessage(fn: (msg: WsMessage) => void): () => void {
  extra.add(fn);
  return () => extra.delete(fn);
}

/**
 * The daemon's WebSocket. Reconnects on close, because the daemon restarting
 * under a window that stays open is normal (package upgrade, watchdog).
 */
export function connectWs(
  onMessage: (msg: WsMessage) => void,
  lifecycle: {onOpen?: () => void; onClose?: () => void} = {},
): () => void {
  let socket: WebSocket | null = null;
  let retry: number | undefined;
  let closed = false;

  const open = () => {
    if (closed) return;
    try {
      socket = new WebSocket(
        `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`,
      );
      socket.onopen = () => {
        if (!closed) lifecycle.onOpen?.();
      };
      socket.onmessage = event => {
        if (closed) return;
        try {
          const msg = JSON.parse(event.data as string) as WsMessage;
          onMessage(msg);
          extra.forEach(fn => fn(msg));
        } catch (err) {
          console.warn('Ignored an unreadable WebSocket frame', err);
        }
      };
      socket.onclose = () => {
        if (!closed) {
          lifecycle.onClose?.();
          retry = window.setTimeout(open, 3000);
        }
      };
      socket.onerror = () => {
        // onclose always follows, and that is where the retry lives.
      };
    } catch (err) {
      console.warn('WebSocket could not be opened, retrying', err);
      if (!closed) retry = window.setTimeout(open, 3000);
    }
  };

  open();

  return () => {
    closed = true;
    window.clearTimeout(retry);
    socket?.close();
  };
}
