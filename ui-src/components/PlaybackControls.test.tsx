import {act, useRef} from 'react';
import {createRoot} from 'react-dom/client';
import {describe, it, expect, vi} from 'vitest';
import {PlayPauseButton, PlaybackTime, VolumeControl, usePlaybackAudio} from './PlaybackControls';
import {useScrubSeek} from '../lib/playback';
import {setLocale} from '../lib/i18n';

function Controls() {
  const video = useRef<HTMLVideoElement>(null);
  const {volume, muted, setVolume, toggleMuted} = usePlaybackAudio(video);
  return <section><video ref={video}/><VolumeControl volume={volume} muted={muted} onChange={setVolume} onToggleMute={toggleMuted}/>
    <button onClick={() => setVolume(.25)}>test-level</button><PlayPauseButton paused onToggle={() => {}}/>
    <PlaybackTime current={1.5} duration={10}/></section>;
}

describe('shared playback surfaces', () => {
  it('shares volume/mute state and localized readouts across viewer and trim controls', async () => {
    localStorage.clear();setLocale('fr');
    const container = document.createElement('div');document.body.append(container);
    const root=createRoot(container);
    try {
      await act(async()=>root.render(<><Controls/><Controls/></>));
      expect(container.querySelectorAll('video')[0].volume).toBe(1);
      await act(async()=>container.querySelector<HTMLButtonElement>('button[aria-pressed]')!.click());
      expect([...container.querySelectorAll('video')].every(video=>video.muted)).toBe(true);
      await act(async()=>[...container.querySelectorAll('button')].find(button=>button.textContent==='test-level')!.click());
      expect([...container.querySelectorAll('video')].every(video=>video.volume===.25 && !video.muted)).toBe(true);
      expect(container.textContent).toContain('1,5s');
      expect(localStorage.getItem('vice-volume')).toBe('0.25');
    } finally {await act(async()=>root.unmount());container.remove();setLocale('en');localStorage.clear();}
  });

  it('coalesces scrub movements to one seek per frame and commits the exact final time', async () => {
    let seek!: ReturnType<typeof useScrubSeek>['seek'];
    let media!: HTMLVideoElement;
    function Probe(){const ref=useRef<HTMLVideoElement>(null);seek=useScrubSeek(ref).seek;return <video ref={ref}/>;}
    const container=document.createElement('div');const root=createRoot(container);
    await act(async()=>root.render(<Probe/>));media=container.querySelector('video')!;
    const frame=vi.spyOn(globalThis,'requestAnimationFrame').mockReturnValue(123);
    const cancel=vi.spyOn(globalThis,'cancelAnimationFrame').mockImplementation(()=>{});
    try {
      seek(1,false);seek(2,false);seek(3,false);
      expect(frame).toHaveBeenCalledTimes(1);expect(media.currentTime).toBe(0);
      seek(3.125,true);expect(media.currentTime).toBe(3.125);expect(cancel).toHaveBeenCalledWith(123);
    } finally {await act(async()=>root.unmount());frame.mockRestore();cancel.mockRestore();}
  });
});
