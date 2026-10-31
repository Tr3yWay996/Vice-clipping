import {useState} from 'react';
import {api} from '../lib/api';
import {t, currentLocale} from '../lib/i18n';
import {formatDuration} from '../lib/format';
import {useStore} from '../state/store';
import type {ProcessingJob} from '../lib/types';

export function LiquidProgress({job}: {job: ProcessingJob}) {
  const fraction = job.progress;
  const percent = fraction === null ? null : new Intl.NumberFormat(currentLocale(), {style: 'percent', maximumFractionDigits: 0}).format(fraction);
  return <div className="queue-progress-wrap" data-status={job.status}>
    <div className="queue-progress" role="progressbar" aria-label={t('queue.progress')}
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={fraction === null ? undefined : Math.round(fraction * 100)}>
      <div className="queue-liquid" data-indeterminate={fraction === null || undefined}
        style={{width: fraction === null ? '35%' : `${fraction * 100}%`}}/>
    </div>
    <span className="mono">{percent ?? t('queue.indeterminate')}</span>
  </div>;
}

export function JobRow({job}: {job: ProcessingJob}) {
  const {state, notify} = useStore();
  const [busy, setBusy] = useState(false);
  const clip = state.clips.find(clip => Boolean(clip.library_id && job.source_media_ids?.includes(clip.library_id)));
  const active = ['queued', 'processing', 'paused'].includes(job.status);
  const control = async (action: string) => {
    setBusy(true);
    try {await api.jobControl(job.id, action);}
    catch (error) {notify({kind:'error', title:t('queue.controlFailed'), detail:(error as Error).message, tone:'error', holdMs:6000});}
    finally {setBusy(false);}
  };
  const button = (action: string, disabled = false, title?: string) => <button type="button" className="btn btn-quiet btn-sm"
    disabled={busy || disabled} title={title} onClick={() => void control(action)}>{t(`queue.${action}`)}</button>;
  return <article className="queue-job" data-status={job.status} aria-label={job.name}>
    <header>{clip?.thumb_url ? <img src={clip.thumb_url} alt=""/> : null}
      <div><b title={job.name}>{job.name}</b><span>{t(`queue.operation.${job.operation}`)}{job.mode?` · ${t(`library.jobMode.${job.mode}`)}`:''} · {t(`queue.state.${job.status}`)}</span></div>
    </header>
    {(active || job.status === 'completed') ? <LiquidProgress job={job}/> : null}
    {job.status === 'processing' || job.status === 'paused' ? <p className="queue-timing">
      {t(`queue.stage.${job.stage}`)} · {t('queue.elapsed', {time:formatDuration(job.elapsed)})}
      {job.remaining === null ? '' : ` · ${t('queue.remaining', {time:formatDuration(job.remaining)})}`}
      {job.speed && job.speed > 0 ? ` · ${t('queue.speed', {speed: new Intl.NumberFormat(currentLocale(), {maximumFractionDigits:1}).format(job.speed)})}` : ''}
    </p> : null}
    {job.error ? <details className="queue-error"><summary>{t('queue.errorDetails')}</summary><pre>{job.error}</pre></details> : null}
    <div className="queue-controls">
      {job.status === 'queued' ? button('pause') : null}
      {job.status === 'processing' ? button('pause', !job.can_pause, !job.can_pause ? t('queue.pauseUnavailable') : undefined) : null}
      {job.status === 'paused' ? button('resume') : null}
      {active ? button('cancel', job.stage === 'saving', job.stage === 'saving' ? t('queue.pauseUnavailable') : undefined) : null}
      {['failed','interrupted','cancelled'].includes(job.status) ? button('retry') : null}
      {job.status === 'completed' ? <>{button('open')}{button('reveal')}</> : null}
      {!active ? button('remove') : null}
    </div>
  </article>;
}

export function ProcessingQueuePanel() {
  const {state} = useStore();
  const [visibleCount, setVisibleCount] = useState(20);
  const running = state.jobs.filter(job => job.status === 'processing' || (job.status === 'paused' && job.started_at));
  const waiting = state.jobs.filter(job => job.status === 'queued' || (job.status === 'paused' && !job.started_at));
  const history = [...state.jobs].reverse().filter(job => !['processing', 'queued', 'paused'].includes(job.status));
  const ordered = [...running, ...waiting, ...history];
  const active = state.jobs.filter(job => job.status === 'processing' || job.status === 'paused').length;
  const queued = state.jobs.filter(job => job.status === 'queued').length;
  return <aside className="home-images processing-queue" aria-label={t('queue.title')}>
    <header className="home-images-head"><div><h2>{t('queue.title')}</h2>
      <p>{t('queue.activeCount', {count:active})} · {t('queue.queuedCount', {count:queued})}</p>
    </div></header>
    <p className="queue-background-help">{t('queue.backgroundHelp')}</p>
    <div className="queue-list">
      {!state.jobsLoaded ? <p>{t('queue.loading')}</p> : state.jobs.length === 0
        ? <div className="queue-empty"><b>{t('queue.emptyTitle')}</b><p>{t('queue.emptyHelp')}</p></div>
        : ordered.slice(0, visibleCount).map(job => <JobRow key={job.id} job={job}/>)}
      {ordered.length > visibleCount ? <button type="button" className="btn btn-quiet btn-sm" onClick={() => setVisibleCount(count => count + 20)}>{t('queue.showMore', {count: ordered.length - visibleCount})}</button> : null}
    </div>
  </aside>;
}
