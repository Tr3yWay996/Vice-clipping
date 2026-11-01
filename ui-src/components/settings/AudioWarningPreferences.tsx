import type {AudioWarningPreferences as Preferences} from '../../lib/types';
import {t} from '../../lib/i18n';
export function AudioWarningPreferences({
  value,
  onChange,
  sourceNames = {},
}: {
  value: Partial<Preferences>;
  sourceNames?: Record<string, string>;
  onChange: (next: Preferences) => void;
}) {
  const prefs = {
    critical: true,
    disconnected: true,
    silence: false,
    silence_seconds: 180,
    ignored_sources: [],
    ignored_conditions: [],
    ...value,
  };
  return (
    <details className="audio-source-editor">
      <summary>{t('audioWorkflow.warningPreferences')}</summary>
      {(['critical', 'disconnected', 'silence'] as const).map((key) => (
        <label key={key}>
          <input
            type="checkbox"
            checked={prefs[key]}
            onChange={(event) =>
              onChange({...prefs, [key]: event.target.checked})
            }
          />
          {t(`audioWorkflow.${key}`)}
        </label>
      ))}
      <label>
        {t('audioWorkflow.silenceDuration')}
        <input
          type="number"
          min={30}
          max={86400}
          disabled={!prefs.silence}
          value={prefs.silence_seconds}
          onChange={(event) =>
            onChange({
              ...prefs,
              silence_seconds: Math.max(
                30,
                Math.min(86400, Number(event.target.value) || 180),
              ),
            })
          }
        />
      </label>
      {(['ignored_sources', 'ignored_conditions'] as const).map((key) =>
        prefs[key].map((id) => (
          <div key={key + id}>
            {sourceNames[id.split('|')[0]] ??
              (id.startsWith('auto:game')
                ? t('audioMixer.auto')
                : id.split('|')[0])}
            {id.includes('|')
              ? ' · ' + t(`audioMixer.state.${id.split('|')[1]}`)
              : ''}{' '}
            <button
              type="button"
              className="btn btn-quiet btn-sm"
              onClick={() =>
                onChange({
                  ...prefs,
                  [key]: prefs[key].filter((value) => value !== id),
                })
              }
            >
              {t('audioWorkflow.restoreWarning')}
            </button>
          </div>
        )),
      )}
    </details>
  );
}
