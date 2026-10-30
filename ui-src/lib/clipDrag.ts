import {useCallback, useEffect, useRef, useState} from 'react';

import {api} from './api';
import {clipTitle, imageSlug, imageTitle, type Clip, type Image, type Playlist} from './types';
import {t} from './i18n';

/**
 * Dragging a clip onto a playlist, shared by the sidebar rows and the tiles on
 * Home so the two cannot drift apart.
 */

/** How long the target holds its caught state after a successful drop. */
const CAUGHT_MS = 600;

let ghost: HTMLElement | null = null;

/**
 * Hand the drag a small pill instead of the card.
 *
 * Without setDragImage the browser drags a snapshot of the whole card, which
 * at 230px covers whatever you are aiming at. The editor's library has always
 * done this; the same element and the same class are used here.
 */
export function startClipDrag(event: React.DragEvent, clip: Clip): void {
  beginDrag(event, clip.slug, clipTitle(clip), clip.thumb_url);
  attachVideoFile(event, clip);
}

/**
 * The same gesture for a screenshot. The prefixed slug is what travels, so the
 * drop target and the daemon both see the membership key they already expect
 * and no target had to learn what an image is.
 */
export function startImageDrag(event: React.DragEvent, image: Image): void {
  beginDrag(event, imageSlug(image.slug), imageTitle(image), image.thumb_url ?? image.image_url);
}

function beginDrag(event: React.DragEvent, slug: string, label: string, thumb?: string): void {
  event.dataTransfer.effectAllowed = 'copy';
  event.dataTransfer.setData('text/plain', slug);
  event.dataTransfer.setData('application/x-vice-clip', slug);

  clearGhost();
  const el = document.createElement('div');
  el.className = 'clip-drag-ghost';
  if (thumb) {
    const img = document.createElement('img');
    img.src = thumb;
    img.alt = '';
    el.appendChild(img);
  }
  const name = document.createElement('span');
  name.className = 'clip-drag-ghost-name';
  name.textContent = label;
  el.appendChild(name);
  document.body.appendChild(el);
  ghost = el;
  event.dataTransfer.setDragImage(el, 24, 20);
}

export function endClipDrag(): void {
  clearGhost();
}

function clearGhost() {
  ghost?.remove();
  ghost = null;
}

export interface DropTarget {
  /** Spread onto the element that accepts the clip. */
  props: {
    ref: (element: HTMLElement | null) => void;
    onDragOver: (e: React.DragEvent) => void;
    onDragLeave: () => void;
    onDrop: (e: React.DragEvent) => void;
  };
  /** A clip is hovering over this target right now. */
  over: boolean;
  /** This target just caught a clip, for the length of the animation. */
  caught: boolean;
}

/**
 * Accept clips dropped onto a playlist.
 *
 * A clip already in the playlist is a no-op rather than an error: the drop
 * looks like it worked because as far as the user wanted, it did.
 */
export function usePlaylistDropTarget(
  playlist: Playlist,
  onDone: (message: string, tone: 'accent' | 'error') => void,
): DropTarget {
  const [over, setOver] = useState(false);
  const [caught, setCaught] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const target = useRef<HTMLElement | null>(null);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const celebrate = useCallback(() => {
    setCaught(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCaught(false), CAUGHT_MS);
  }, []);

  const accept = useCallback(
    (slug: string) => {
      setOver(false);
      if (!slug) return;
      if (playlist.clip_slugs?.includes(slug)) {
        celebrate();
        onDone(t('card.alreadyIn', {playlist: playlist.name}), 'accent');
        return;
      }
      void api
        .addClipToPlaylist(playlist.id, slug)
        .then(result => {
          if (result.ok === false) throw new Error(result.error || t('card.errAddClip'));
          celebrate();
          onDone(t('card.addedTo', {playlist: playlist.name}), 'accent');
        })
        .catch((err: Error) => onDone(err.message, 'error'));
    },
    [playlist.id, playlist.name, playlist.clip_slugs, celebrate, onDone],
  );

  useEffect(() => {
    const nativeDrop = (event: Event) => {
      if (event.target instanceof Node && target.current?.contains(event.target)) {
        const slug = (event as CustomEvent<{slug: string}>).detail?.slug;
        if (slug) accept(slug);
      }
    };
    const end = () => setOver(false);
    window.addEventListener('vice-native-clip-drop', nativeDrop);
    window.addEventListener('vice-native-drag-end', end);
    return () => {
      window.removeEventListener('vice-native-clip-drop', nativeDrop);
      window.removeEventListener('vice-native-drag-end', end);
    };
  }, [accept]);

  return {
    over,
    caught,
    props: {
      ref: element => {target.current = element;},
      onDragOver: e => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
        setOver(true);
      },
      onDragLeave: () => setOver(false),
      onDrop: event => {
        event.preventDefault();
        accept(event.dataTransfer.getData('application/x-vice-clip') || event.dataTransfer.getData('text/plain'));
      },
    },
  };
}

/** Shared with prepared-file drags from the share sheet. */
export function fileUri(path: string): string {
  return `file://${path.split('/').map(encodeURIComponent).join('/')}`;
}
const files = new Map<string, {uri: string}>();
type DragBridge = {
  drag_clip?: (slug: string, prepared: boolean, appearance: {background: string; foreground: string}) => Promise<{ok: boolean; reason?: string}>;
  file_drag_capabilities?: () => Promise<boolean>;
};
let checkedBridge: DragBridge | undefined;
let nativeSupported = true;
function nativeBridge(): DragBridge | undefined {
  const bridge = (window as unknown as {pywebview?: {api?: DragBridge}}).pywebview?.api;
  if (bridge !== checkedBridge) {
    checkedBridge = bridge;
    nativeSupported = true;
    if (bridge?.file_drag_capabilities) void bridge.file_drag_capabilities()
      .then(supported => {if (checkedBridge === bridge) nativeSupported = supported;})
      .catch(() => {if (checkedBridge === bridge) nativeSupported = false;});
  }
  return nativeSupported ? bridge : undefined;
}
export function prepareClipDrag(clip: Clip): void {
  nativeBridge();
  const key = clip.video_url;
  if (files.has(key)) return;
  void api.originalFile(clip.slug).then(file => {
    files.set(key, file);
    if (files.size > 64) files.delete(files.keys().next().value!);
  }).catch(() => {});
}
export function attachVideoFile(event: React.DragEvent, clip: Clip, preparedPath?: string): void {
  const bridge = nativeBridge()?.drag_clip;
  event.dataTransfer.effectAllowed = 'copy';
  event.dataTransfer.setData('application/x-vice-clip', clip.slug);
  if (bridge) {
    // Cancel Chromium's own drag before Qt starts the native file drag. The
    // native QMimeData retains the internal identifier for playlist targets.
    event.preventDefault();
    const appearance = getComputedStyle(ghost ?? event.currentTarget);
    void bridge(clip.slug, Boolean(preparedPath), {background: appearance.backgroundColor, foreground: appearance.color}).then(result => {
      if (!result.ok && result.reason !== 'cancelled') window.dispatchEvent(new Event('vice-drag-unavailable'));
    }).catch(() => window.dispatchEvent(new Event('vice-drag-unavailable'))).finally(() => {
      clearGhost();
      window.dispatchEvent(new Event('vice-native-drag-end'));
    });
    return;
  }
  const uri = preparedPath ? fileUri(preparedPath) : files.get(clip.video_url)?.uri;
  if (uri) {
    event.dataTransfer.setData('text/uri-list', `${uri}\r\n`);
    event.dataTransfer.setData('text/plain', uri);
  } else {
    window.dispatchEvent(new Event('vice-drag-unavailable'));
  }
}
