import {createSpacePress, type PlaybackBoost} from './playbackBoost';
import {useEffect, useRef, type RefObject} from 'react';

export interface PlaybackShortcutContext {
  root: () => HTMLElement | null;
  priority: number;
  handle: (event: KeyboardEvent) => boolean;
  boost?: () => PlaybackBoost | null;
}
const contexts: PlaybackShortcutContext[] = [];

/** Native editing and accessibility controls keep their own keys. */
export function ownsKeyboardInput(event: KeyboardEvent): boolean {
  const target = event.target instanceof Element ? event.target : null;
  return Boolean(event.isComposing || target?.closest(
    'input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="combobox"], [role="listbox"], [role="menu"], [role="switch"], [role="checkbox"], [role="radio"], [role="tablist"]',
  ));
}

function owner() {
  const active = contexts.filter(context => context.root()?.isConnected)
    .sort((a, b) => b.priority - a.priority || Number(Boolean(b.root()?.contains(document.activeElement))) - Number(Boolean(a.root()?.contains(document.activeElement))));
  const dialogs = [...document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')]
    .filter(dialog => !dialog.closest('[data-closing="true"]') && !dialog.hidden);
  const dialog = dialogs[dialogs.length - 1];
  return active.find(context => !dialog || context.root()?.closest('[role="dialog"][aria-modal="true"]') === dialog);
}
let press: {owner: PlaybackShortcutContext; state: ReturnType<typeof createSpacePress>} | null = null;
const cancelPress = () => {press?.state.finish(true); press = null;};
const checkOwner = () => {if (press && (owner() !== press.owner || document.querySelector('[role="listbox"], [role="menu"]'))) cancelPress();};
const visibility = () => {if (document.hidden) cancelPress();};
const focus = (event: FocusEvent) => {if (ownsKeyboardInput(event as unknown as KeyboardEvent)) cancelPress();};
const release = (event: KeyboardEvent) => {
  if ((event.code === 'Space' || event.key === ' ') && press) {
    const current = press; press = null;
    current.state.finish(owner() !== current.owner || ownsKeyboardInput(event));
    event.preventDefault(); event.stopImmediatePropagation();
  }
};
const wheel = (event: WheelEvent) => {
  checkOwner();
  if (press?.state.wheel(event.deltaY)) {event.preventDefault(); event.stopImmediatePropagation();}
};
const observer = typeof MutationObserver === 'undefined' ? null : new MutationObserver(checkOwner);
function dispatch(event: KeyboardEvent) {
  checkOwner();
  if (event.defaultPrevented || ownsKeyboardInput(event)) return;
  if (document.querySelector('[role="listbox"], [role="menu"]')) return;
  const context = owner();
  if (!context) return;
  const target = event.target instanceof Element ? event.target : null;
  const space = event.key === ' ' || event.code === 'Space';
  const boost = space && !event.ctrlKey && !event.altKey && !event.metaKey &&
    !target?.closest('button:not([role="slider"]), a, summary, [role="button"]') ? context.boost?.() : null;
  if (boost) {
    if (!event.repeat && !press) press = {owner:context, state:createSpacePress(boost, () => {
      // The original keydown is consumed now; a tap is dispatched on release.
      context.handle(new KeyboardEvent('keydown', {key:' ', code:'Space', cancelable:true}));
    })};
    event.preventDefault(); event.stopImmediatePropagation();
  } else if (context.handle(event)) {
    event.preventDefault(); event.stopImmediatePropagation();
  }
}

/** One document listener, shared by React surfaces and the imperative editor. */
export function bindPlaybackShortcuts(context: PlaybackShortcutContext): () => void {
  if (!contexts.length) {
    document.addEventListener('keydown', dispatch);
    document.addEventListener('keyup', release);
    document.addEventListener('wheel', wheel, {passive:false});
    document.addEventListener('visibilitychange', visibility);
    document.addEventListener('focusin', focus);
    window.addEventListener('blur', cancelPress);
    observer?.observe(document.body, {childList:true, subtree:true, attributes:true, attributeFilter:['hidden','data-closing','aria-modal']});
  }
  contexts.push(context);
  checkOwner();
  return () => {
    const at = contexts.indexOf(context);
    if (at !== -1) contexts.splice(at, 1);
    if (press?.owner === context) cancelPress();
    if (!contexts.length) {
      document.removeEventListener('keydown', dispatch);
      document.removeEventListener('keyup', release);
      document.removeEventListener('wheel', wheel);
      document.removeEventListener('visibilitychange', visibility);
      document.removeEventListener('focusin', focus);
      window.removeEventListener('blur', cancelPress);
      observer?.disconnect();
    }
  };
}

export function usePlaybackShortcuts(active: boolean, root: RefObject<HTMLElement | null>, priority: number,
  handle: (event: KeyboardEvent) => boolean, boost?: () => PlaybackBoost | null, scope?: unknown): void {
  const latest = useRef(handle);
  latest.current = handle;
  const latestBoost = useRef(boost); latestBoost.current = boost;
  useEffect(() => active ? bindPlaybackShortcuts({root: () => root.current, priority,
    handle: event => latest.current(event), boost: () => latestBoost.current?.() ?? null}) : undefined, [active, root, priority, scope]);
}

export interface PlaybackActions {
  toggle: () => void;
  rename?: () => void;
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
  } else if (key === 'f2' && actions.rename) {
    if (!event.repeat) actions.rename();
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
