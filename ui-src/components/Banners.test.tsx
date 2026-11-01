import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {beforeEach, afterEach, it, expect, vi} from 'vitest';
import {Banners} from './Banners';
import type {AudioWarning} from '../lib/types';
const fixture = vi.hoisted(() => ({
  state: {
    dismissed: [],
    status: {
      ready: true,
      cpu_fallback: false,
      codec_fallback: false,
      recorder_error: null,
      audio: {
        warnings: [] as AudioWarning[],
        tracks: [{state: 'quiet', enabled: true, name: 'Game'}],
      },
    },
    config: {recording: {audio_warning_preferences: {}}},
  },
  dispatch: vi.fn(),
  saveConfig: vi.fn().mockResolvedValue({}),
}));
vi.mock('../state/store', () => ({useStore: () => fixture}));
vi.mock('../lib/env', () => ({H264_SUPPORTED: true}));
let root: Root, container: HTMLElement;
const warning = (id = 'failure:1'): AudioWarning => ({
  id,
  source: 'auto:game',
  name: 'Game',
  state: 'disconnected',
  kind: 'disconnected',
});
const render = () => act(async () => root.render(<Banners />));
beforeEach(async () => {
  vi.clearAllMocks();
  sessionStorage.clear();
  fixture.state.status.audio.warnings = [];
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await render();
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});
it('never turns ordinary quiet diagnostics into intrusive banners', () => {
  expect(container.querySelector('[role=status]')).toBeNull();
});
it('deduplicates the same episode and keeps it dismissed until a genuinely new failure', async () => {
  fixture.state.status.audio.warnings = [warning()];
  await render();
  expect(container.querySelectorAll('[role=status]')).toHaveLength(1);
  const original = container.querySelector('[role=status]');
  await render();
  expect(container.querySelector('[role=status]')).toBe(original);
  await act(async () =>
    container.querySelector<HTMLButtonElement>('.banner-close')!.click(),
  );
  await render();
  expect(container.querySelector('[role=status]')).toBeNull();
  fixture.state.status.audio.warnings = [];
  await render();
  fixture.state.status.audio.warnings = [warning('failure:2')];
  await render();
  expect(container.querySelector('[role=status]')).not.toBeNull();
});
it('remembers dismissal across interface remounts and clears visible failures on recovery', async () => {
  fixture.state.status.audio.warnings = [warning()];
  await render();
  await act(async () =>
    container.querySelector<HTMLButtonElement>('.banner-close')!.click(),
  );
  await act(async () => root.unmount());
  root = createRoot(container);
  await render();
  expect(container.querySelector('[role=status]')).toBeNull();
  fixture.state.status.audio.warnings = [warning('new')];
  await render();
  fixture.state.status.audio.warnings = [];
  await render();
  expect(container.querySelector('[role=status]')).toBeNull();
});
it.each([
  ['Silence this warning', 'ignored_conditions', 'auto:game|disconnected'],
  ['Silence this source', 'ignored_sources', 'auto:game'],
])('persists %s without restarting capture', async (label, key, value) => {
  fixture.state.status.audio.warnings = [warning()];
  await render();
  await act(async () =>
    [...container.querySelectorAll<HTMLButtonElement>('button')]
      .find((b) => b.textContent === label)!
      .click(),
  );
  expect(fixture.saveConfig).toHaveBeenCalledWith({
    recording: {audio_warning_preferences: {[key]: [value]}},
  });
  expect(container.querySelector('[role=status]')).toBeNull();
});
