import {act, useState} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {AudioMixer} from './AudioMixer';
import {api} from '../../lib/api';
import {setLocale} from '../../lib/i18n';
import type {Draft} from '../../lib/settingsDraft';
import type {SmartAudioState, AudioApplication} from '../../lib/types';
const fixture = vi.hoisted(() => ({
  state: {status: {audio: {} as SmartAudioState}},
  dispatch: vi.fn(),
}));
vi.mock('../../state/store', () => ({useStore: () => fixture}));
vi.mock('../../lib/api', () => ({
  api: {
    audioState: vi.fn(),
    monitorAudio: vi.fn().mockResolvedValue({ok: true}),
    audioMatch: vi.fn().mockResolvedValue({matches: [[273]]}),
    testAudio: vi.fn(),
    deleteAudioTest: vi.fn().mockResolvedValue({ok: true}),
  },
}));
let root: Root, container: HTMLElement, current: Draft;
const app: AudioApplication = {
  node_id: 273,
  serial: 'game',
  name: 'FMOD Audio',
  application_id: '',
  executable: 'BeamNG.drive.x64',
  pid: 42,
  node_name: 'FMOD Audio',
  destination: 'Speakers',
  active: true,
  muted: false,
  levels: [0.1, 0.6],
  tracks: [1],
};
const base = () =>
  ({
    audioTracks: ['auto:game', 'device:old-mic'],
    audioSources: {'auto:game': {name: 'Game', enabled: true, rules: []}},
    audioTrackVolumes: {'auto:game': 50},
  }) as unknown as Draft;
function Harness({active = true}: {active?: boolean}) {
  const [draft, setDraft] = useState(base());
  current = draft;
  return (
    <AudioMixer
      draft={draft}
      update={(patch) => setDraft((previous) => ({...previous, ...patch}))}
      sources={[{id: 'device:old-mic', label: 'Old microphone', kind: 'input'}]}
      active={active}
      onRefresh={() => {}}
    />
  );
}
const button = (text: string) =>
  [...container.querySelectorAll<HTMLButtonElement>('button')].find(
    (b) => b.textContent === text,
  )!;
const click = async (el: HTMLElement) => act(async () => el.click());
const set = async (el: HTMLInputElement, value: string) =>
  act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!.call(el, value);
    el.dispatchEvent(new Event('input', {bubbles: true}));
  });
beforeEach(async () => {
  vi.clearAllMocks();
  setLocale('en');
  fixture.state.status.audio = {
    supported: true,
    backend_supported: true,
    error: null,
    meter_error: null,
    recording: true,
    applications: [app],
    tracks: [
      {
        id: 'auto:game',
        name: 'Game',
        enabled: true,
        nodes: [273],
        levels: [0.2, 0.4],
        state: 'active',
        recording_connected: true,
      },
    ],
  };
  vi.mocked(api.audioState).mockResolvedValue(fixture.state.status.audio);
  vi.mocked(api.testAudio).mockResolvedValue({
    id: 'sample',
    duration: 3,
    tracks: [
      {
        index: 0,
        name: 'Game',
        source: 'auto:game',
        state: 'captured',
        url: '/api/audio/tests/sample/0',
      },
    ],
  });
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(<Harness />));
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  setLocale('en');
});
describe('Smart audio mixer', () => {
  it('shows actual stereo levels, executable, destination and recorded track association', () => {
    expect(container.textContent).toContain('BeamNG.drive.x64');
    expect(container.textContent).toContain('Speakers');
    expect(container.textContent).toContain('Track');
    const meters = container.querySelectorAll<HTMLMeterElement>(
      '.audio-source-row meter',
    );
    expect([...meters].map((m) => m.value)).toEqual([0.1, 0.6]);
    expect(container.querySelector('img')?.getAttribute('src')).toBe(
      '/api/audio/icons/273',
    );
  });
  it('creates a persistent executable rule without changing earlier tracks or gains', async () => {
    const row = [
      ...container.querySelectorAll<HTMLElement>('.audio-source-row'),
    ].find((row) => row.textContent?.includes('FMOD Audio'))!;
    await click(row.querySelector('button')!);
    const id = current.audioTracks[2];
    expect(current.audioTracks.slice(0, 2)).toEqual([
      'auto:game',
      'device:old-mic',
    ]);
    expect(current.audioSources[id].rules).toEqual([
      {field: 'executable', mode: 'exact', value: 'BeamNG.drive.x64'},
    ]);
    expect(current.audioTrackVolumes['auto:game']).toBe(50);
  });
  it('filters sources and keeps unavailable application rules editable', async () => {
    await set(container.querySelector('input[type=search]')!, 'absent');
    expect(container.querySelector('.audio-app-icon')).toBeNull();
    await click(button('Create an application rule'));
    const id = current.audioTracks[current.audioTracks.length - 1];
    expect(current.audioSources[id].rules?.[0].field).toBe('executable');
  });
  it('renames and disables a logical source in its original slot', async () => {
    const details = container.querySelector('details')!;
    await click(details.querySelector('summary')!);
    await set(
      details.querySelector('input[type=text], input:not([type])')!,
      'My game',
    );
    expect(current.audioSources['auto:game'].name).toBe('My game');
    await click(details.querySelector('input[type=checkbox]')!);
    expect(current.audioSources['auto:game'].enabled).toBe(false);
    expect(current.audioTracks[0]).toBe('auto:game');
  });
  it('tests applied capture settings and offers disposable sample playback', async () => {
    await click(button('Test Audio Capture'));
    expect(api.testAudio).toHaveBeenCalledOnce();
    expect(container.querySelector('audio')?.getAttribute('src')).toBe(
      '/api/audio/tests/sample/0',
    );
    const clear = container.querySelector<HTMLButtonElement>(
      '.audio-test-results button',
    )!;
    await click(clear);
    expect(api.deleteAudioTest).toHaveBeenCalledWith('sample');
    expect(container.querySelector('audio')).toBeNull();
  });
  it('acquires and releases monitoring only while audio settings are visible', async () => {
    expect(api.monitorAudio).toHaveBeenCalledWith(expect.any(String), true);
    await act(async () => root.render(<Harness active={false} />));
    expect(api.monitorAudio).toHaveBeenLastCalledWith(
      expect.any(String),
      false,
    );
  });
  it('keeps French controls translated and missing meters distinct from silence', async () => {
    setLocale('fr');
    fixture.state.status.audio.applications = [{...app, levels: null}];
    await act(async () => root.render(<Harness />));
    expect(container.textContent).toContain('Tester');
    expect(container.textContent).not.toContain('audioMixer.');
    expect(container.querySelector('.audio-meter small')).not.toBeNull();
  });
});
