import {useEffect, useSyncExternalStore, useCallback, type RefObject} from 'react';
import {t} from '../lib/i18n';
import {formatDuration} from '../lib/format';
const stroke = {viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeLinecap: 'round', strokeLinejoin: 'round'} as const;
let fallbackVolume = 1;
let fallbackMuted = false;
const audioListeners = new Set<() => void>();
const subscribeAudio = (listener: () => void) => {audioListeners.add(listener); return () => {audioListeners.delete(listener);};};
const audioChanged = () => audioListeners.forEach(listener => listener());
export const VOLUME_KEY = 'vice-volume';
export const MUTED_KEY = 'vice-muted';

export function storedVolume(): number {
  try {
    const raw = Number(localStorage.getItem(VOLUME_KEY) ?? 1);
    return Number.isFinite(raw) && raw >= 0 && raw <= 1 ? raw : 1;
  } catch {
    return fallbackVolume;
  }
}

export function storedMuted(): boolean {
  try {
    return localStorage.getItem(MUTED_KEY) === '1';
  } catch {
    return fallbackMuted;
  }
}

export function VolumeControl({
  volume,
  muted,
  onChange,
  onToggleMute,
}: {
  volume: number;
  muted: boolean;
  onChange: (next: number) => void;
  onToggleMute: () => void;
}) {
  // Muted shows an empty track, so the control always agrees with what is
  // coming out of the speakers rather than with the number behind it.
  const shown = muted ? 0 : volume;

  return (
    <div className="player-volume">
      <button
        type="button"
        className="player-btn"
        onClick={onToggleMute}
        aria-pressed={muted}
        title={muted ? t('viewer.unmuteHint') : t('viewer.muteHint')}
        aria-label={muted ? t('viewer.unmute') : t('viewer.mute')}>
        <SpeakerGlyph level={shown} />
      </button>
      <input
        type="range"
        data-playback-control="volume"
        className="player-volume-range"
        min={0}
        max={1}
        step={0.01}
        value={shown}
        aria-label={t('viewer.volume')}
        style={{['--filled' as string]: `${shown * 100}%`}}
        onChange={e => onChange(Number(e.target.value))}
      />
    </div>
  );
}
export const PlayGlyph = () => (
  <svg viewBox="0 0 24 24" width={16} height={16} fill="currentColor" aria-hidden="true">
    <path d="M7 4l13 8-13 8z" />
  </svg>
);
export const PauseGlyph = () => (
  <svg viewBox="0 0 24 24" width={16} height={16} fill="currentColor" aria-hidden="true">
    <path d="M7 4h3.5v16H7zM13.5 4H17v16h-3.5z" />
  </svg>
);
const SpeakerGlyph = ({level}: {level: number}) => (
  <svg {...stroke} width={15} height={15} strokeWidth={2}>
    <path d="M4 9.5h3L11 6v12L7 14.5H4z" />
    {level <= 0 ? (
      <path d="m15 9.5 4.5 5M19.5 9.5l-4.5 5" />
    ) : level < 0.55 ? (
      <path d="M14.8 9.8a3 3 0 0 1 0 4.4" />
    ) : (
      <path d="M14.8 9.8a3 3 0 0 1 0 4.4M17.3 7.6a6.5 6.5 0 0 1 0 8.8" />
    )}
  </svg>
);

export function usePlaybackAudio(ref?: RefObject<HTMLVideoElement | null>) {
  const volume = useSyncExternalStore(subscribeAudio, storedVolume, () => 1);
  const muted = useSyncExternalStore(subscribeAudio, storedMuted, () => false);
  useEffect(() => {
    const video = ref?.current;
    if (video) {video.volume = volume; video.muted = muted;}
  });
  const setVolume = useCallback((level: number) => {
    const next = Math.round(Math.max(0, Math.min(1, level)) * 1000) / 1000;
    fallbackVolume = next;
    if (next > 0) fallbackMuted = false;
    try {
      localStorage.setItem(VOLUME_KEY, String(next));
      if (next > 0) localStorage.setItem(MUTED_KEY, '0');
    } catch { /* Optional storage. */ }
    audioChanged();
  }, []);
  const toggleMuted = useCallback(() => {
    fallbackMuted = !storedMuted();
    try {localStorage.setItem(MUTED_KEY, fallbackMuted ? '1' : '0');} catch { /* Optional storage. */ }
    audioChanged();
  }, []);
  return {volume, muted, setVolume, toggleMuted};
}
export function PlayPauseButton({paused, onToggle, disabled, className = 'player-main'}: {
  paused: boolean; onToggle: () => void; disabled?: boolean; className?: string;
}) {
  return <button type="button" className={className} disabled={disabled} onClick={onToggle}
    aria-label={paused ? t('viewer.play') : t('viewer.pause')}>
    {paused ? <PlayGlyph/> : <PauseGlyph/>}
  </button>;
}
export function PlaybackTime({current, duration}: {current: number; duration: number}) {
  return <span className="mono player-tc">{formatDuration(current, true)} / {formatDuration(duration, true)}</span>;
}
export function VideoLoading({preparing}: {preparing: boolean}) {
  return preparing ? <div className="video-overlay" role="status" onClick={event => event.stopPropagation()}>
    <span className="video-spinner" aria-hidden="true"/><p>{t('viewer.loadingPreview')}</p>
  </div> : null;
}
