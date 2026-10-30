import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {describe,it,expect,vi,afterEach} from 'vitest';
import {ProcessingQueuePanel, LiquidProgress} from './ProcessingQueuePanel';
import {api} from '../lib/api';
import {setLocale} from '../lib/i18n';
import type {ProcessingJob} from '../lib/types';
const fixture=vi.hoisted(()=>({state:{jobs:[] as ProcessingJob[],jobsLoaded:true,clips:[]},notify:vi.fn()}));
vi.mock('../state/store',()=>({useStore:()=>fixture}));
vi.mock('../lib/api',()=>({api:{jobControl:vi.fn().mockResolvedValue({ok:true})}}));
const job=(id:string,status:ProcessingJob['status']='completed'):ProcessingJob=>({id,operation:'trim',name:`clip-${id}.mp4`,source_revision:'source',output_path:'/clip.mp4',created_at:'2026-10-30T00:00:00Z',started_at:'2026-10-30T00:00:00Z',finished_at:null,duration:10,progress:status==='completed'?1:.4,elapsed:2,remaining:3,speed:2.4,stage:'encode',status,error:null,result_path:'/clip.mp4',can_pause:true});
afterEach(()=>{setLocale('en');vi.clearAllMocks();});
describe('processing queue panel',()=>{
 it('prioritizes running work, paginates history and sends real control requests',async()=>{
  fixture.state.jobs=[job('active','processing'),...Array.from({length:40},(_,i)=>job(String(i)))];
  const container=document.createElement('div');const root=createRoot(container);
  try{
   await act(async()=>root.render(<ProcessingQueuePanel/>));
   expect(container.querySelectorAll('.queue-job')).toHaveLength(20);
   expect(container.querySelector('.queue-job')?.getAttribute('data-status')).toBe('processing');
   const pause=[...container.querySelectorAll('button')].find(b=>b.textContent==='Pause')!;
   await act(async()=>pause.click());expect(api.jobControl).toHaveBeenCalledWith('active','pause');
   const more=[...container.querySelectorAll('button')].find(b=>b.textContent?.includes('more jobs'))!;
   await act(async()=>more.click());expect(container.querySelectorAll('.queue-job')).toHaveLength(40);
  }finally{await act(async()=>root.unmount());}
 });
 it('uses indeterminate progress when unknown and renders paused/completed states accurately',async()=>{
  const container=document.createElement('div');const root=createRoot(container);setLocale('fr');
  try{
   await act(async()=>root.render(<LiquidProgress job={{...job('one','processing'),progress:null}}/>));
   expect(container.querySelector('[role=progressbar]')?.hasAttribute('aria-valuenow')).toBe(false);
   expect(container.textContent).toContain('Traitement en cours');
   await act(async()=>root.render(<LiquidProgress job={job('one','paused')}/>));
   expect(container.querySelector('[data-status=paused]')).not.toBeNull();
   expect(container.querySelector('[role=progressbar]')?.getAttribute('aria-valuenow')).toBe('40');
   await act(async()=>root.render(<LiquidProgress job={job('one')}/>));
   expect(container.querySelector('[role=progressbar]')?.getAttribute('aria-valuenow')).toBe('100');
  }finally{await act(async()=>root.unmount());}
 });
});
