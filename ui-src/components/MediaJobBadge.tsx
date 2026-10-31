import {useEffect,useState} from 'react';
import {t,currentLocale} from '../lib/i18n';
import type {ProcessingJob} from '../lib/types';

export function jobForMedia(jobs:ProcessingJob[], id?:string):ProcessingJob|undefined {
  if(!id)return;
  const found=jobs.filter(job=>job.source_media_ids?.includes(id));
  return [...found].reverse().find(job=>['queued','processing','paused'].includes(job.status)) ?? found[found.length-1];
}
export function MediaJobBadge({job,onOpen}:{job?:ProcessingJob;onOpen:()=>void}) {
  const [expired,setExpired]=useState(false);
  const terminal=job && ['completed','cancelled'].includes(job.status);
  useEffect(()=>{
    setExpired(false);
    if(!terminal)return;
    const remaining=Math.max(0,5000-(Date.now()-Date.parse(job.finished_at ?? '')));
    const timer=setTimeout(()=>setExpired(true),Number.isFinite(remaining)?remaining:0);
    return ()=>clearTimeout(timer);
  },[job?.id,job?.status,job?.finished_at,terminal]);
  if(!job || terminal && (expired || Date.now()-Date.parse(job.finished_at??'')>=5000))return null;
  const active=['queued','processing','paused'].includes(job.status);
  const percent=job.progress===null?'':new Intl.NumberFormat(currentLocale(),{style:'percent',maximumFractionDigits:0}).format(job.progress);
  return <button type="button" className="media-job" data-status={job.status} aria-label={t('library.processingDetails')} onClick={event=>{event.stopPropagation();onOpen();}}>
    <span>{t(`queue.state.${job.status}`)}{job.status==='processing'?` · ${t(`queue.operation.${job.operation}`)}${percent?` · ${percent}`:''}`:''}{job.mode?` · ${t(`library.jobMode.${job.mode}`)}`:''}</span>
    {active?<span className="media-job-track" role="progressbar" aria-label={t('queue.progress')} aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={job.progress===null?undefined:Math.round(job.progress*100)}>
      <i data-indeterminate={job.progress===null||undefined} style={{width:job.progress===null?'30%':`${job.progress*100}%`}}/>
    </span>:null}
  </button>;
}
