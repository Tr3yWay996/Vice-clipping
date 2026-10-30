/** Playback-only state; never written into an editor project or export. */
export interface PlaybackBoost {
  rate: () => number;
  setRate: (rate: number) => void;
  paused: () => boolean;
  play: () => void;
  pause: () => void;
  multiplier: () => number;
  setMultiplier: (rate: number) => void;
  changed?: (rate: number | null) => void;
}
export const HOLD_MS = 250;
export const boostMultiplier = (value: unknown): number => {
  const n = Number(value);
  return Number.isFinite(n) && n >= .25 && n <= 4 ? Math.round(n * 4) / 4 : 2;
};

/** One press, one tap or hold. Repeat events never enter this machine. */
export function createSpacePress(boost: PlaybackBoost, tap: () => void) {
  let active = false, done = false;
  const rate = boost.rate(), paused = boost.paused();
  const timer = window.setTimeout(() => {
    if (done) return;
    active = true;
    const next = boostMultiplier(boost.multiplier());
    boost.setRate(next); boost.changed?.(next);
    if (paused) boost.play();
  }, HOLD_MS);
  return {
    wheel(delta: number) {
      if (!active || !delta) return false;
      const next = Math.max(.25, Math.min(4, boostMultiplier(boost.multiplier()) + (delta < 0 ? .25 : -.25)));
      boost.setMultiplier(next); boost.setRate(next); boost.changed?.(next);
      return true;
    },
    finish(cancel = false) {
      if (done) return;
      done = true; window.clearTimeout(timer);
      if (active) {
        boost.setRate(rate);
        if (paused) boost.pause();
        boost.changed?.(null);
      } else if (!cancel) tap();
    },
  };
}
