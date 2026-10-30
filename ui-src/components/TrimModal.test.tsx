import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {api} from '../lib/api';
import {TrimModal} from './TrimModal';
import type {Clip} from '../lib/types';
import type {KeyframeInfo} from '../lib/trimming';
import {setLocale} from '../lib/i18n';

vi.mock('../lib/api', () => ({api: {keyframes: vi.fn(), trimClip: vi.fn()}}));
const info: KeyframeInfo = {
  timestamps: [0, 11, 22, 39, 51, 59],
  total_keyframes: 6,
  total_frames: 3600,
  frames_estimated: false,
  average_fps: 60,
  nominal_fps: 60,
  average_interval: 11.8,
  min_interval: 8,
  max_interval: 17,
};
const clip = {
  slug: 'session',
  name: 'session.mp4',
  video_url: '/v/session?v=revision',
  vcodec: 'h264',
} as Clip;
let container: HTMLDivElement, root: Root;
let close = vi.fn<() => void>();
const video = () => container.querySelector('video')!;
const timeline = () => container.querySelector<HTMLElement>('.trim-timeline')!;
const startHandle = () => container.querySelectorAll<HTMLButtonElement>('.trim-handle')[0];
const endHandle = () => container.querySelectorAll<HTMLButtonElement>('.trim-handle')[1];
const checkbox = () => container.querySelector<HTMLInputElement>('input[type=checkbox]')!;
const value = (element: Element) => Number(element.getAttribute('aria-valuenow'));
const button = (text: string) =>
  Array.from(container.querySelectorAll('button')).find((b) => b.textContent === text)!;
const click = async (element: HTMLElement) => {
  await act(async () => element.click());
};
const pointer = async (element: Element, type: string, x: number, shift = false) => {
  await act(async () => {
    const event = new MouseEvent(type, {bubbles: true, clientX: x, button: 0, shiftKey: shift});
    Object.defineProperty(event, 'pointerId', {value: 1});
    element.dispatchEvent(event);
  });
};
const boundaryClick = async (seconds: number) => {
  await pointer(timeline(), 'pointerdown', (seconds / 60) * 1000, true);
  await pointer(timeline(), 'pointerup', (seconds / 60) * 1000, true);
};
const key = async (element: Element, name: string) => {
  await act(async () =>
    element.dispatchEvent(new KeyboardEvent('keydown', {key: name, bubbles: true})),
  );
};
async function mount() {
  await act(async () =>
    root.render(
      <TrimModal
        clip={clip}
        highlights={[{id: 'mark', time: 20, label: 'Win', color: '#ff0'}]}
        onClose={close}
        onSaved={vi.fn()}
        notify={vi.fn()}
        onRename={vi.fn()}
        onReveal={vi.fn()}
        onOpenExternally={vi.fn()}
      />,
    ),
  );
  Object.defineProperty(video(), 'duration', {value: 60, configurable: true});
  await act(async () => video().dispatchEvent(new Event('loadedmetadata')));
}
beforeEach(async () => {
  vi.clearAllMocks();
  vi.mocked(api.keyframes).mockResolvedValue(info);
  close = vi.fn();
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  setLocale('en');
});

describe('unified trimming timeline', () => {
  it('normal clicks seek freely without modifying trim boundaries in either keyframe mode', async () => {
    await mount();
    for (const show of [false, true]) {
      if (show) await click(checkbox());
      await pointer(timeline(), 'pointerdown', 250);
      await pointer(timeline(), 'pointerup', 250);
      expect(value(startHandle())).toBe(0);
      expect(value(endHandle())).toBe(60);
      expect(video().currentTime).toBe(15);
    }
  });

  it('has one timeline, custom playback, volume and synchronized media time', async () => {
    await mount();
    expect(video().controls).toBe(false);
    expect(container.querySelectorAll('.trim-timeline').length).toBe(1);
    expect(container.querySelector('.player-volume-range')).not.toBeNull();
    video().currentTime = 12.3;
    await act(async () => video().dispatchEvent(new Event('timeupdate')));
    expect(value(container.querySelector('.trim-seek')!)).toBe(12.3);
    expect(container.querySelector('.trim-playhead')?.getAttribute('style')).toContain('20.5%');
    await click(container.querySelector('[aria-label="Play"]')!);
    expect(video().paused).toBe(false);
    await click(container.querySelector('[aria-label="Pause"]')!);
    expect(video().paused).toBe(true);
  });
  it('Shift-clicks move the nearest boundary without seeking', async () => {
    await mount();
    await boundaryClick(10);
    await boundaryClick(50);
    await boundaryClick(15);
    await boundaryClick(45);
    expect(value(startHandle())).toBe(15);
    expect(value(endHandle())).toBe(45);
    expect(video().currentTime).toBe(0);
    expect(value(container.querySelector('.trim-seek')!)).toBe(0);
  });
  it('background drags scrub without changing either boundary in both modes', async () => {
    await mount();
    for (const show of [false, true]) {
      if (show) await click(checkbox());
      await pointer(timeline(), 'pointerdown', 100);
      await pointer(timeline(), 'pointermove', 300);
      await pointer(timeline(), 'pointerup', 400);
      expect(video().currentTime).toBe(24);
      expect(value(startHandle())).toBe(0);
      expect(value(endHandle())).toBe(60);
    }
    expect(api.keyframes).toHaveBeenCalledTimes(1);
  });
  it('handles adjust only their endpoint, enforce minimum, and cancel safely', async () => {
    await mount();
    await pointer(startHandle(), 'pointerdown', 0);
    await pointer(startHandle(), 'pointermove', 998);
    await pointer(startHandle(), 'pointerup', 998);
    expect(value(startHandle())).toBe(59.5);
    expect(value(endHandle())).toBe(60);
    await pointer(timeline(), 'pointerdown', 100);
    await pointer(timeline(), 'pointercancel', 100);
    expect(value(startHandle())).toBe(59.5);
  });
  it('showing keys snaps clicks and handles; hiding restores free editing', async () => {
    await mount();
    await click(checkbox());
    await boundaryClick(15);
    expect(value(startHandle())).toBe(11);
    expect(video().currentTime).toBe(0);
    const markers = container.querySelectorAll<HTMLElement>('.trim-keyframe');
    expect(markers.length).toBe(6);
    expect(parseFloat(markers[2].style.left)).toBeCloseTo((22 / 60) * 100);
    await pointer(endHandle(), 'pointerdown', 1000);
    await pointer(endHandle(), 'pointermove', 760);
    await pointer(endHandle(), 'pointerup', 760);
    expect(value(endHandle())).toBe(51);
    await click(checkbox());
    await boundaryClick(15);
    expect(value(startHandle())).toBe(15);
    expect(container.querySelector('.trim-keyframe')).toBeNull();
  });
  it('manual snapping adjusts both endpoints with visualization disabled', async () => {
    await mount();
    await boundaryClick(15);
    await boundaryClick(45);
    await click(button('Snap selection to keyframes'));
    expect(value(startHandle())).toBe(11);
    expect(value(endHandle())).toBe(39);
    expect(video().currentTime).toBe(0);
    expect(checkbox().checked).toBe(false);
    await boundaryClick(15);
    expect(value(startHandle())).toBe(15);
  });
  it('an impossible manual snap leaves selection intact and explains why', async () => {
    vi.mocked(api.keyframes).mockResolvedValue({...info, timestamps: [22], total_keyframes: 1});
    await mount();
    await boundaryClick(15);
    await boundaryClick(45);
    await click(button('Snap selection to keyframes'));
    expect(value(startHandle())).toBe(15);
    expect(value(endHandle())).toBe(45);
    expect(container.querySelector('[role=status]')?.textContent).toContain('No two keyframes');
  });
  it('statistics are collapsed initially and display counts, estimates, intervals and rates', async () => {
    vi.mocked(api.keyframes).mockResolvedValue({...info, frames_estimated: true});
    await mount();
    const details = container.querySelector<HTMLDetailsElement>('details:not(.playback-shortcuts)')!;
    expect(details.open).toBe(false);
    await click(details.querySelector('summary')!);
    expect(details.open).toBe(true);
    expect(details.textContent).toContain('3,600 (estimated)');
    expect(details.textContent).toContain('1 keyframe per 600.0 frames (0.17%)');
    expect(details.textContent).toContain('Every 11.800 seconds');
    expect(details.textContent).toContain('8.000–17.000 s');
    expect(details.textContent).toContain('60.000 FPS average · 60.000 nominal');
    await click(details.querySelector('summary')!);
    expect(details.open).toBe(false);
  });
  it('translates keyframe controls and formats French statistics with decimal commas', async () => {
    setLocale('fr');
    await mount();
    const details = container.querySelector<HTMLDetailsElement>('details:not(.playback-shortcuts)')!;
    await click(details.querySelector('summary')!);
    expect(details.textContent).toContain('Informations sur les images clés');
    expect(details.textContent).toContain('Toutes les 11,800 secondes');
    expect(details.textContent).toContain('0,17 %');
    expect(container.textContent).not.toContain('Show keyframes');
    expect(container.textContent).toContain('Maj + clic');
  });
  it('preserves highlights, keyboard seeking, boundary adjustment, looping and Escape', async () => {
    await mount();
    expect(container.querySelector('.trim-hl')?.getAttribute('title')).toBe('Win');
    await key(container.querySelector('.trim-seek')!, 'ArrowRight');
    expect(video().currentTime).toBe(1);
    await key(startHandle(), 'ArrowRight');
    expect(value(startHandle())).toBe(1);
    await click(checkbox());
    await key(startHandle(), 'ArrowRight');
    expect(value(startHandle())).toBe(11);
    await click(button('Preview'));
    video().currentTime = 60;
    await act(async () => video().dispatchEvent(new Event('timeupdate')));
    expect(video().currentTime).toBe(11);
    await key(timeline(), 'Escape');
    expect(close).toHaveBeenCalledTimes(1);
  });
  it('handles document-level Space, seek, mute and I/O after ordinary pointer interactions', async () => {
    await mount();
    await key(document.body, ' ');
    expect(video().paused).toBe(false);
    await click(container.querySelector('.trim-readout')!);
    await key(document.body, ' ');
    expect(video().paused).toBe(true);
    video().currentTime = 15;
    await key(document.body, 'i');
    expect(value(startHandle())).toBe(15);
    expect(value(endHandle())).toBe(60);
    expect(video().currentTime).toBe(15);
    await key(document.body, 'ArrowRight');
    expect(video().currentTime).toBe(16);
    video().currentTime = 45;
    await key(document.body, 'o');
    expect(value(endHandle())).toBe(45);
    expect(video().currentTime).toBe(45);
    video().currentTime = 44.8;
    await key(document.body, 'i');
    expect(value(startHandle())).toBe(15);
    expect(value(endHandle())).toBe(45);
    expect(video().currentTime).toBe(44.8);
    expect(container.querySelector('[role=status]')?.textContent).toContain('at least');
    await key(document.body, 'Home');expect(video().currentTime).toBe(0);
    await key(document.body, 'End');expect(video().currentTime).toBe(60);
    await key(document.body, 'm');expect(video().muted).toBe(true);
    await key(document.body, 'm');expect(video().muted).toBe(false);
  });
  it('keeps a paused reference frame and playing state through every boundary edit', async () => {
    await mount();video().currentTime = 30;
    await act(async()=>video().dispatchEvent(new Event('timeupdate')));
    await boundaryClick(10);await boundaryClick(50);
    await pointer(startHandle(), 'pointerdown', 100);
    await pointer(startHandle(), 'pointermove', 250);
    await pointer(startHandle(), 'pointerup', 250);
    expect(video().currentTime).toBe(30);expect(video().paused).toBe(true);
    expect(value(startHandle())).toBe(15);expect(value(endHandle())).toBe(50);
    await key(startHandle(), 'ArrowLeft');expect(video().currentTime).toBe(30);
    await click(checkbox());await click(button('Snap selection to keyframes'));
    expect(video().currentTime).toBe(30);
    await key(document.body, ' ');expect(video().paused).toBe(false);
    await key(document.body, 'i');expect(value(startHandle())).toBe(22);
    await key(document.body, 'o');expect(value(endHandle())).toBe(39);
    expect(video().currentTime).toBe(30);expect(video().paused).toBe(false);
    await boundaryClick(15);expect(video().currentTime).toBe(30);expect(video().paused).toBe(false);
    await click(button('Snap selection to keyframes'));expect(video().currentTime).toBe(30);expect(video().paused).toBe(false);
  });
  it('keeps native input keys and ignores shortcuts behind another dialog or after closing', async () => {
    await mount();
    const input=document.createElement('input');container.querySelector('.trim-modal')!.append(input);
    await key(input,' ');await key(input,'i');expect(video().paused).toBe(true);expect(value(startHandle())).toBe(0);
    const dialog=document.createElement('div');dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');document.body.append(dialog);
    try{await key(document.body,' ');expect(video().paused).toBe(true);}finally{dialog.remove();}
    const media=video();await act(async()=>root.render(<div/>));
    await key(document.body,' ');expect(media.paused).toBe(true);
  });
  it('supports short clips and rejects crossed I/O without changing the partner', async () => {
    await mount();Object.defineProperty(video(),'duration',{value:.2,configurable:true});
    await act(async()=>video().dispatchEvent(new Event('loadedmetadata')));
    video().currentTime=.1;await key(document.body,'i');await key(document.body,'o');
    expect(value(startHandle())).toBe(0);expect(value(endHandle())).toBe(.2);expect(video().currentTime).toBe(.1);
  });
  it('failed analysis leaves ordinary trimming usable and communicates failure', async () => {
    vi.mocked(api.keyframes).mockRejectedValue(new Error('missing ffprobe'));
    await mount();
    await boundaryClick(15);
    expect(value(startHandle())).toBe(15);
    expect(checkbox().disabled).toBe(true);
    expect(container.querySelector('[role=status]')?.textContent).toContain(
      'Free trimming still works',
    );
  });
});
