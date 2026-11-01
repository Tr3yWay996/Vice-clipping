import {act, useState} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach, beforeEach, it, expect} from 'vitest';
import {AudioWarningPreferences} from './AudioWarningPreferences';
import type {AudioWarningPreferences as Preferences} from '../../lib/types';
let container: HTMLElement, root: Root, value: Preferences;
function Harness() {
  const [prefs, setPrefs] = useState<Preferences>({
    critical: true,
    disconnected: true,
    silence: false,
    silence_seconds: 180,
    ignored_sources: ['auto:game'],
    ignored_conditions: [],
  });
  value = prefs;
  return (
    <AudioWarningPreferences
      value={prefs}
      sourceNames={{'auto:game': 'My Game'}}
      onChange={setPrefs}
    />
  );
}
beforeEach(async () => {
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(<Harness />));
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});
it('starts with silence disabled and critical/disconnection warnings enabled', () => {
  expect(
    [
      ...container.querySelectorAll<HTMLInputElement>('input[type=checkbox]'),
    ].map((input) => input.checked),
  ).toEqual([true, true, false]);
  expect(
    container.querySelector<HTMLInputElement>('input[type=number]')!.disabled,
  ).toBe(true);
});
it('exposes configurable silence duration only when enabled and restores source warnings by name', async () => {
  await act(async () =>
    container
      .querySelectorAll<HTMLInputElement>('input[type=checkbox]')[2]
      .click(),
  );
  expect(value.silence).toBe(true);
  const duration =
    container.querySelector<HTMLInputElement>('input[type=number]')!;
  expect(duration.disabled).toBe(false);
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!.call(duration, '120');
    duration.dispatchEvent(new Event('input', {bubbles: true}));
  });
  expect(value.silence_seconds).toBe(120);
  expect(container.textContent).toContain('My Game');
  await act(async () =>
    container.querySelector<HTMLButtonElement>('button')!.click(),
  );
  expect(value.ignored_sources).toEqual([]);
});
