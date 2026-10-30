import {useRef, useState, type RefObject} from 'react';
import {useStore} from '../state/store';
import {t} from '../lib/i18n';
import {playQuietly} from '../lib/playback';
import {boostMultiplier, type PlaybackBoost} from '../lib/playbackBoost';

/** Config is shared by every surface and persisted by the daemon. */
export function usePlaybackSpeed() {
  const {state, saveConfig, notify} = useStore();
  const [, redraw] = useState(0);
  const [active, changed] = useState<number | null>(null);
  const value = boostMultiplier(state.config?.ui?.playback_boost ?? 2);
  const current = useRef(value);
  const configured = useRef(value);
  if (configured.current !== value) {configured.current = value; current.current = value;}

  // Wheel changes are coalesced into one config write when the press ends.
  const persist = (next: number) => {
    current.current = boostMultiplier(next);
    redraw(revision => revision + 1);
    void saveConfig({ui:{playback_boost:current.current}}).catch(error =>
      notify({kind:'error', title:t('settings.errSave'), detail:(error as Error).message, tone:'error', holdMs:6000}));
  };
  const finish = (next: number | null) => {
    changed(next);
    if (next === null && current.current !== value) persist(current.current);
  };
  return {value, active, persist,
    actions: {multiplier:() => current.current, setMultiplier:(next:number) => {current.current = next;}, changed:finish},
    control:<label className="player-speed" title={t('speed.help')}>
      <span>{t('speed.label')}</span>
      <select aria-label={t('speed.label')} value={current.current} onChange={event => persist(Number(event.target.value))}>
        {Array.from({length:16}, (_, i) => (i + 1) / 4).map(rate => <option key={rate} value={rate}>{rate.toFixed(2)}×</option>)}
      </select>
      {active !== null ? <output className="player-speed-active" aria-live="polite">{active.toFixed(2)}×</output> : null}
    </label>,
  };
}
export function mediaBoost(ref: RefObject<HTMLVideoElement | null>, actions: Pick<PlaybackBoost,'multiplier'|'setMultiplier'|'changed'>): PlaybackBoost | null {
  const video = ref.current;
  if (!video?.getAttribute('src')) return null;
  return {...actions, rate:() => video.playbackRate, setRate:rate => {video.playbackRate = rate;},
    paused:() => video.paused, play:() => playQuietly(video), pause:() => video.pause()};
}
