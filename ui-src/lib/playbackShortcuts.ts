import {useEffect, useRef, type RefObject} from 'react';

export interface PlaybackShortcutContext {
  root: () => HTMLElement | null;
  priority: number;
  handle: (event: KeyboardEvent) => boolean;
}
const contexts: PlaybackShortcutContext[] = [];

/** Native editing and accessibility controls keep their own keys. */
export function ownsKeyboardInput(event: KeyboardEvent): boolean {
  const target = event.target instanceof Element ? event.target : null;
  return Boolean(event.isComposing || target?.closest(
    'input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="combobox"], [role="listbox"], [role="menu"], [role="switch"], [role="checkbox"], [role="radio"], [role="tablist"]',
  ));
}

function dispatch(event: KeyboardEvent) {
  if (event.defaultPrevented || ownsKeyboardInput(event)) return;
  if (document.querySelector('[role="listbox"], [role="menu"]')) return;
  const active = contexts.filter(context => context.root()?.isConnected)
    .sort((a, b) => b.priority - a.priority);
  const dialogs = [...document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')]
    .filter(dialog => !dialog.closest('[data-closing="true"]') && !dialog.hidden);
  const dialog = dialogs[dialogs.length - 1];
  // A dialog without playback shortcuts still blocks underlying players.
  const owner = active.find(context => !dialog ||
    context.root()?.closest('[role="dialog"][aria-modal="true"]') === dialog);
  if (!owner) return;
  if (owner.handle(event)) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
}

/** One document listener, shared by React surfaces and the imperative editor. */
export function bindPlaybackShortcuts(context: PlaybackShortcutContext): () => void {
  if (!contexts.length) document.addEventListener('keydown', dispatch);
  contexts.push(context);
  return () => {
    const at = contexts.indexOf(context);
    if (at !== -1) contexts.splice(at, 1);
    if (!contexts.length) document.removeEventListener('keydown', dispatch);
  };
}

export function usePlaybackShortcuts(active: boolean, root: RefObject<HTMLElement | null>, priority: number,
  handle: (event: KeyboardEvent) => boolean): void {
  const latest = useRef(handle);
  latest.current = handle;
  useEffect(() => active ? bindPlaybackShortcuts({root: () => root.current, priority,
    handle: event => latest.current(event)}) : undefined, [active, root, priority]);
}

export interface PlaybackActions {
  toggle: () => void;
  mute: () => void;
  time?: () => number;
  duration?: () => number;
  seek?: (seconds: number) => void;
  volume?: () => number;
  setVolume?: (volume: number) => void;
  arrowMode?: 'playback' | 'clips';
  stepClip?: (direction: -1 | 1) => void;
  boundary?: (boundary: 'start' | 'end') => void;
}

/** Timestamp steps work with actual media time, independent of nominal FPS. */
export function playbackShortcut(event: KeyboardEvent, actions: PlaybackActions): boolean {
  if (event.defaultPrevented || event.ctrlKey || event.altKey || event.metaKey || ownsKeyboardInput(event)) return false;
  const key = event.key.toLowerCase();
  const target = event.target instanceof Element ? event.target : null;
  if (key === ' ' || event.code === 'Space') {
    if (target?.closest('button:not([role="slider"]), a, summary, [role="button"]')) return false;
    if (!event.repeat) actions.toggle();
  } else if (key === 'm') {
    if (!event.repeat) actions.mute();
  } else if ((key === 'i' || key === 'o') && actions.boundary) {
    if (!event.repeat) actions.boundary(key === 'i' ? 'start' : 'end');
  } else if (key === 'arrowleft' || key === 'arrowright') {
    const direction = key === 'arrowleft' ? -1 : 1;
    if (actions.arrowMode === 'clips' && actions.stepClip) actions.stepClip(direction);
    else if (actions.seek && actions.time && actions.duration) actions.seek(Math.max(0,
      Math.min(actions.duration(), actions.time() + direction * (event.shiftKey ? .1 : 1))));
    else return false;
  } else if ((key === 'arrowup' || key === 'arrowdown') && actions.setVolume && actions.volume) {
    if (actions.arrowMode === 'clips') return false;
    actions.setVolume(Math.max(0, Math.min(1, actions.volume() + (key === 'arrowup' ? .05 : -.05))));
  } else if ((key === 'home' || key === 'end') && actions.seek && actions.duration) {
    actions.seek(key === 'home' ? 0 : actions.duration());
  } else return false;
  event.preventDefault();
  return true;
}
