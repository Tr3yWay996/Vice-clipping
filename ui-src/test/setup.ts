import {vi} from 'vitest';

Object.assign(globalThis, {IS_REACT_ACT_ENVIRONMENT: true});
vi.stubGlobal(
  'ResizeObserver',
  class {
    observe() {}
    disconnect() {}
  },
);
Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
  value: () => ({left: 0, top: 0, width: 1000, height: 40, right: 1000, bottom: 40}),
  configurable: true,
});
HTMLElement.prototype.setPointerCapture = vi.fn();
HTMLElement.prototype.releasePointerCapture = vi.fn();
HTMLElement.prototype.hasPointerCapture = () => true;
HTMLMediaElement.prototype.load = vi.fn();
HTMLMediaElement.prototype.play = vi.fn(function (this: HTMLMediaElement) {
  Object.defineProperty(this, 'paused', {value: false, configurable: true});
  this.dispatchEvent(new Event('play'));
  return Promise.resolve();
});
HTMLMediaElement.prototype.pause = vi.fn(function (this: HTMLMediaElement) {
  Object.defineProperty(this, 'paused', {value: true, configurable: true});
  this.dispatchEvent(new Event('pause'));
});
