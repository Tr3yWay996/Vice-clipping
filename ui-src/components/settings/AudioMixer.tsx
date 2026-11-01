import {useEffect, useRef, useState} from 'react';
import {api} from '../../lib/api';
import {t} from '../../lib/i18n';
import type {Draft} from '../../lib/settingsDraft';
import type {
  AudioApplication,
  AudioMatchRule,
  AudioTestResult,
  SmartAudioSource,
} from '../../lib/types';
import {useStore} from '../../state/store';
import type {AudioSource} from './AudioTracks';

const managed = (id: string) => id === 'auto:game' || id.startsWith('rule:');
const uid = () => crypto.randomUUID().replace(/-/g, '');
export function AudioMeter({
  levels,
  label,
}: {
  levels?: number[] | null;
  label: string;
}) {
  return (
    <div className="audio-meter" aria-label={label}>
      {[0, 1].map((channel) => (
        <meter
          key={channel}
          min={0}
          max={1}
          value={levels?.[channel] ?? 0}
          aria-label={`${label} ${channel === 0 ? 'L' : 'R'}`}
        />
      ))}
      {!levels ? <small>{t('audioMixer.noMeter')}</small> : null}
    </div>
  );
}
function RuleMatches({
  rules,
  applications,
  active,
}: {
  rules: AudioMatchRule[];
  applications: AudioApplication[];
  active: boolean;
}) {
  const [matches, setMatches] = useState<number[][]>([]),
    [error, setError] = useState(false);
  const key = JSON.stringify(rules),
    identities = JSON.stringify(
      applications.map((app) => [app.node_id, app.serial]),
    );
  useEffect(() => {
    if (!active) return;
    let alive = true;
    setError(false);
    const timer = setTimeout(
      () =>
        void api
          .audioMatch(rules)
          .then((result) => {
            if (alive) setMatches(result.matches);
          })
          .catch(() => {
            if (alive) {
              setError(true);
              setMatches([]);
            }
          }),
      300,
    );
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [key, identities, active]);
  return (
    <div aria-live="polite">
      {error ? (
        <small>{t('audioMixer.ruleError')}</small>
      ) : (
        matches.map((ids, index) => (
          <small key={index}>
            {t('audioMixer.matches', {
              names:
                applications
                  .filter((app) => ids.includes(app.node_id))
                  .map((app) => `${app.name} (${app.executable})`)
                  .join(', ') || t('audioMixer.none'),
            })}
          </small>
        ))
      )}
    </div>
  );
}
export function AudioMixer({
  draft,
  update,
  sources,
  active,
  onRefresh,
}: {
  draft: Draft;
  update: (patch: Partial<Draft>) => void;
  sources: AudioSource[];
  active: boolean;
  onRefresh: () => void;
}) {
  const {state, dispatch} = useStore();
  const live = state.status.audio;
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [search, setSearch] = useState(''),
    [filter, setFilter] = useState('all'),
    [error, setError] = useState('');
  const [testing, setTesting] = useState(false),
    [test, setTest] = useState<AudioTestResult | null>(null);
  const currentTest = useRef<string | null>(null);
  useEffect(() => {
    if (!active) return;
    const token = uid();
    let alive = true;
    const refresh = () =>
      void api
        .audioState()
        .then((audio) => {
          if (alive) dispatch({type: 'ws', msg: {type: 'audio_state', audio}});
        })
        .catch(() => {
          if (alive) setError(t('audioMixer.unavailable'));
        });
    const lease = () =>
      void api.monitorAudio(token, !document.hidden).catch(() => {});
    refresh();
    lease();
    const timer = setInterval(lease, 20000);
    document.addEventListener('visibilitychange', lease);
    return () => {
      alive = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', lease);
      void api.monitorAudio(token, false).catch(() => {});
    };
  }, [active, dispatch]);
  useEffect(
    () => () => {
      if (currentTest.current)
        void api.deleteAudioTest(currentTest.current).catch(() => {});
    },
    [],
  );
  const add = (id: string, source?: SmartAudioSource) => {
    if (draft.audioTracks.includes(id)) return;
    update({
      audioTracks: [...draft.audioTracks, id],
      audioSources: source
        ? {...draft.audioSources, [id]: source}
        : draft.audioSources,
    });
  };
  const appRule = (app: AudioApplication): AudioMatchRule => ({
    field:
      app.executable &&
      !['wine', 'wine64-preloader', 'wine-preloader'].includes(
        app.executable.toLowerCase(),
      )
        ? 'executable'
        : 'name',
    mode: 'exact',
    value:
      app.executable &&
      !['wine', 'wine64-preloader', 'wine-preloader'].includes(
        app.executable.toLowerCase(),
      )
        ? app.executable
        : app.name,
  });
  const setSource = (id: string, patch: Partial<SmartAudioSource>) =>
    update({
      audioSources: {
        ...draft.audioSources,
        [id]: {...draft.audioSources[id], ...patch},
      },
    });
  const smartDevice = (device: string, name: string) => ({
    name,
    enabled: true,
    ...(device.startsWith('app:')
      ? {
          rules: [
            {
              field: 'name' as const,
              mode: 'exact' as const,
              value: device.slice(4),
            },
          ],
        }
      : device.startsWith('app-inverse:')
        ? {
            exclude: true,
            rules: [
              {
                field: 'name' as const,
                mode: 'exact' as const,
                value: device.slice(12),
              },
            ],
          }
        : {device}),
  });
  const wrapLegacy = (id: string, enabled: boolean) => {
    const next = 'rule:' + uid();
    const source = smartDevice(
      id,
      sources.find((source) => source.id === id)?.label ?? id,
    );
    update({
      audioTracks: draft.audioTracks.map((value) =>
        value === id ? next : value,
      ),
      audioSources: {...draft.audioSources, [next]: {...source, enabled}},
      audioTrackVolumes: {
        ...draft.audioTrackVolumes,
        [next]: draft.audioTrackVolumes[id] ?? 100,
      },
    });
  };
  const applicationName = (app: AudioApplication) =>
    ['fmod audio', 'sdl application', 'wine'].includes(
      app.name.toLowerCase(),
    ) && app.executable
      ? app.executable
      : app.name || app.executable;
  const includes = (text: string) =>
    text.toLocaleLowerCase().includes(search.toLocaleLowerCase());
  const runTest = async () => {
    setTesting(true);
    setError('');
    try {
      if (currentTest.current) await api.deleteAudioTest(currentTest.current);
      const result = await api.testAudio();
      currentTest.current = result.id;
      setTest(result);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setTesting(false);
    }
  };
  const unsupported =
    live?.backend_supported === false || live?.supported === false;
  return (
    <section className="audio-mixer" aria-label={t('audioMixer.title')}>
      <p>{t('audioMixer.help')}</p>
      {(live?.applications ?? []).some((app) => app.tracks.length > 1) ? (
        <p role="status">{t('audioMixer.overlap')}</p>
      ) : null}
      {unsupported ? <p role="status">{t('audioMixer.unavailable')}</p> : null}
      <div className="tracks-add">
        <input
          className="text-input"
          type="search"
          value={search}
          aria-label={t('audioMixer.search')}
          placeholder={t('audioMixer.search')}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select
          className="select"
          value={filter}
          aria-label={t('audioMixer.filterLabel')}
          onChange={(event) => setFilter(event.target.value)}
        >
          {['all', 'applications', 'devices'].map((value) => (
            <option key={value} value={value}>
              {t(`audioMixer.filter.${value}`)}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn btn-quiet btn-sm"
          onClick={() => {
            onRefresh();
            void api
              .audioState()
              .then((audio) =>
                dispatch({type: 'ws', msg: {type: 'audio_state', audio}}),
              )
              .catch(() => setError(t('audioMixer.unavailable')));
          }}
        >
          {t('audioTracks.refresh')}
        </button>
      </div>
      {includes(t('audioMixer.auto')) ? (
        <div className="audio-source-row">
          <span aria-hidden="true">◉</span>
          <div>
            <b>{t('audioMixer.auto')}</b>
            <small>{t('audioMixer.autoHelp')}</small>
          </div>
          <button
            type="button"
            className="btn btn-quiet btn-sm"
            disabled={unsupported || draft.audioTracks.includes('auto:game')}
            onClick={() =>
              add('auto:game', {
                name: t('audioMixer.auto'),
                enabled: true,
                rules: [],
              })
            }
          >
            {t('audioTracks.addTrack')}
          </button>
        </div>
      ) : null}
      {filter !== 'devices'
        ? (live?.applications ?? [])
            .filter((app) =>
              includes(
                [app.name, app.executable, app.application_id].join(' '),
              ),
            )
            .map((app) => {
              const rule = appRule(app);
              const existing = Object.entries(draft.audioSources).find(
                ([id, source]) =>
                  draft.audioTracks.includes(id) &&
                  source.rules?.some(
                    (item) =>
                      item.field === rule.field &&
                      item.mode === rule.mode &&
                      item.value === rule.value,
                  ),
              );
              return (
                <div
                  className="audio-source-row"
                  key={app.serial || app.node_id}
                >
                  <img
                    className="audio-app-icon"
                    src={`/api/audio/icons/${app.node_id}`}
                    alt=""
                    onError={(event) => {
                      event.currentTarget.hidden = true;
                    }}
                  />
                  <div>
                    <b>{applicationName(app)}</b>
                    <small>
                      {app.name} · {app.executable} · PID {app.pid}
                    </small>
                    <small>
                      {app.destination || t('audioMixer.unknownOutput')} ·{' '}
                      {t(
                        app.active
                          ? 'audioMixer.running'
                          : 'audioMixer.inactive',
                      )}
                    </small>
                    {app.tracks.length ? (
                      <small>
                        {t('audioMixer.onTracks', {
                          tracks: app.tracks.join(', '),
                        })}
                      </small>
                    ) : null}
                  </div>
                  <AudioMeter
                    levels={app.levels}
                    label={applicationName(app)}
                  />
                  <button
                    type="button"
                    className="btn btn-quiet btn-sm"
                    disabled={unsupported || Boolean(existing)}
                    onClick={() =>
                      add('rule:' + uid(), {
                        name: applicationName(app),
                        enabled: true,
                        rules: [rule],
                      })
                    }
                  >
                    {t('audioTracks.addTrack')}
                  </button>
                </div>
              );
            })
        : null}
      {filter !== 'applications'
        ? sources
            .filter(
              (source) =>
                source.id !== 'auto:game' &&
                !source.id.startsWith('rule:') &&
                !source.id.startsWith('app') &&
                includes(source.label ?? source.id),
            )
            .map((source) => (
              <div key={source.id} className="audio-source-row">
                <span aria-hidden="true">◉</span>
                <div>
                  <b>{source.label ?? source.id}</b>
                  <small>
                    {t(
                      source.kind === 'input'
                        ? 'audioMixer.input'
                        : 'audioMixer.output',
                    )}
                  </small>
                </div>
                <button
                  type="button"
                  className="btn btn-quiet btn-sm"
                  disabled={unsupported}
                  onClick={() =>
                    add(
                      'rule:' + uid(),
                      smartDevice(source.id, source.label ?? source.id),
                    )
                  }
                >
                  {t('audioTracks.addTrack')}
                </button>
              </div>
            ))
        : null}
      <button
        type="button"
        className="btn btn-quiet btn-sm"
        disabled={unsupported}
        onClick={() =>
          add('rule:' + uid(), {
            name: t('audioMixer.newSource'),
            enabled: true,
            rules: [{field: 'executable', mode: 'contains', value: ''}],
          })
        }
      >
        {t('audioMixer.createRule')}
      </button>
      <p className="srow-help">{t('audioMixer.saveHelp')}</p>
      {draft.audioTracks.map((id, index) => {
        const source = draft.audioSources[id];
        const actual = live?.tracks.find((track) => track.id === id);
        return (
          <details
            key={id}
            className="audio-source-editor"
            onToggle={(event) => {
              const open = event.currentTarget.open;
              setExpanded((previous) => ({...previous, [id]: open}));
            }}
          >
            <summary>
              {t('audioMixer.track', {number: index + 1})} ·{' '}
              {source?.name ||
                sources.find((source) => source.id === id)?.label ||
                id}
            </summary>
            <label>
              <input
                type="checkbox"
                checked={source?.enabled !== false}
                onChange={(event) =>
                  managed(id)
                    ? setSource(id, {enabled: event.target.checked})
                    : wrapLegacy(id, event.target.checked)
                }
              />
              {t('audioMixer.enabled')}
            </label>
            {managed(id) ? (
              <>
                <label>
                  {t('audioMixer.name')}
                  <input
                    className="text-input"
                    maxLength={120}
                    value={source?.name ?? ''}
                    onChange={(event) =>
                      setSource(id, {name: event.target.value})
                    }
                  />
                </label>
                {actual ? (
                  <>
                    <p role="status">{t(`audioMixer.state.${actual.state}`)}</p>
                    <AudioMeter
                      levels={actual.levels}
                      label={source?.name || id}
                    />
                    {actual.recording_connected ? (
                      <small>{t('audioMixer.captureConnected')}</small>
                    ) : null}
                    {actual.ambiguous ? (
                      <p>{t('audioMixer.ambiguous')}</p>
                    ) : null}
                    {actual.error ? (
                      <p role="alert">{t('audioMixer.ruleError')}</p>
                    ) : null}
                  </>
                ) : null}
                {source?.device ? (
                  <small>{source.device}</small>
                ) : (
                  <>
                    {(source?.rules ?? []).map((rule, at) => (
                      <div className="audio-rule" key={at}>
                        <select
                          className="select"
                          aria-label={t('audioMixer.fieldLabel')}
                          value={rule.field}
                          onChange={(event) =>
                            setSource(id, {
                              rules: source!.rules!.map((item, i) =>
                                i === at
                                  ? {
                                      ...item,
                                      field: event.target
                                        .value as AudioMatchRule['field'],
                                    }
                                  : item,
                              ),
                            })
                          }
                        >
                          {[
                            'executable',
                            'executable_path',
                            'name',
                            'application_id',
                            'node_name',
                          ].map((field) => (
                            <option key={field} value={field}>
                              {t(`audioMixer.field.${field}`)}
                            </option>
                          ))}
                        </select>
                        <select
                          className="select"
                          aria-label={t('audioMixer.modeLabel')}
                          value={rule.mode}
                          onChange={(event) =>
                            setSource(id, {
                              rules: source!.rules!.map((item, i) =>
                                i === at
                                  ? {
                                      ...item,
                                      mode: event.target
                                        .value as AudioMatchRule['mode'],
                                    }
                                  : item,
                              ),
                            })
                          }
                        >
                          {['exact', 'contains', 'regex'].map((mode) => (
                            <option key={mode} value={mode}>
                              {t(`audioMixer.mode.${mode}`)}
                            </option>
                          ))}
                        </select>
                        <input
                          className="text-input"
                          maxLength={256}
                          aria-label={t('audioMixer.pattern')}
                          value={rule.value}
                          onChange={(event) =>
                            setSource(id, {
                              rules: source!.rules!.map((item, i) =>
                                i === at
                                  ? {...item, value: event.target.value}
                                  : item,
                              ),
                            })
                          }
                        />
                        <button
                          type="button"
                          className="btn btn-quiet btn-sm"
                          onClick={() =>
                            setSource(id, {
                              rules: source!.rules!.filter((_, i) => i !== at),
                            })
                          }
                        >
                          {t('audioTracks.removeTrack')}
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      className="btn btn-quiet btn-sm"
                      disabled={(source?.rules?.length ?? 0) >= 16}
                      onClick={() =>
                        setSource(id, {
                          rules: [
                            ...(source?.rules ?? []),
                            {field: 'executable', mode: 'contains', value: ''},
                          ],
                        })
                      }
                    >
                      {t('audioMixer.addRule')}
                    </button>
                    <small>
                      {t(
                        id === 'auto:game'
                          ? 'audioMixer.gameRulesHelp'
                          : 'audioMixer.rulesHelp',
                      )}
                    </small>
                    <RuleMatches
                      rules={source?.rules ?? []}
                      applications={live?.applications ?? []}
                      active={active && Boolean(expanded[id])}
                    />
                    {actual ? (
                      <small>
                        {t('audioMixer.matches', {
                          names:
                            (live?.applications ?? [])
                              .filter((app) =>
                                actual.nodes.includes(app.node_id),
                              )
                              .map((app) => `${app.name} (${app.executable})`)
                              .join(', ') || t('audioMixer.none'),
                        })}
                      </small>
                    ) : null}
                  </>
                )}
              </>
            ) : (
              <>
                <p>{t('audioMixer.legacyHelp')}</p>
                <button
                  type="button"
                  className="btn btn-quiet btn-sm"
                  onClick={() => wrapLegacy(id, true)}
                >
                  {t('audioMixer.manage')}
                </button>
              </>
            )}
          </details>
        );
      })}
      <div className="tracks-add">
        <button
          type="button"
          className="btn btn-quiet"
          disabled={testing || !draft.audioTracks.length || unsupported}
          onClick={() => void runTest()}
        >
          {t(testing ? 'audioMixer.testing' : 'audioMixer.test')}
        </button>
        <small>{t('audioMixer.testHelp')}</small>
      </div>
      {test ? (
        <div className="audio-test-results" role="status">
          {test.tracks.map((track) => (
            <div key={track.index}>
              <b>{track.name}</b> · {t(`audioMixer.state.${track.state}`)}
              {track.url ? (
                <audio controls preload="none" src={track.url} />
              ) : null}
            </div>
          ))}
          <button
            type="button"
            className="btn btn-quiet btn-sm"
            onClick={() => {
              void api.deleteAudioTest(test.id);
              currentTest.current = null;
              setTest(null);
            }}
          >
            {t('audioMixer.clearTest')}
          </button>
        </div>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
    </section>
  );
}
