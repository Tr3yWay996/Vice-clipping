import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {api} from '../lib/api';
import {connectWs} from '../lib/ws';
import {StoreProvider,useStore} from '../state/store';
import {MediaGallery} from './MediaGallery';
import {LibraryToolbar} from './LibraryToolbar';
import {clipTitle,type Clip,type WsMessage,type RenamePlan,type ProcessingJob} from '../lib/types';
import {setLocale} from '../lib/i18n';
vi.mock('../lib/api',()=>({api:{trash:vi.fn().mockResolvedValue({items:[],total_bytes:0,retention_days:30,error:null}),games:vi.fn().mockResolvedValue([]),jobs:vi.fn().mockResolvedValue([]),status:vi.fn().mockResolvedValue({}),getConfig:vi.fn().mockResolvedValue({sharing:{},ui:{}}),clips:vi.fn(),images:vi.fn().mockResolvedValue([]),playlists:vi.fn().mockResolvedValue([]),renamePreview:vi.fn(),libraryActions:vi.fn(),jobControl:vi.fn().mockResolvedValue({ok:true})}}));
vi.mock('../lib/ws',()=>({connectWs:vi.fn()}));
vi.mock('../lib/clipDrag',()=>({prepareClipDrag:vi.fn(),startClipDrag:vi.fn(),endClipDrag:vi.fn()}));
vi.mock('../lib/clipboard',()=>({copyToClipboard:vi.fn().mockResolvedValue(true)}));
const clips=['a','b','c','d'].map((slug,index)=>({slug,library_id:slug,name:slug+'.mp4',display_title:slug,video_url:'/v/'+slug,created_at:`2020-01-0${4-index}`,duration:10} as Clip));
let root:Root,container:HTMLElement,store:ReturnType<typeof useStore>,message:(msg:WsMessage)=>void;
const rename=vi.fn(),open=vi.fn();
function Harness(){store=useStore();return <><LibraryToolbar/><MediaGallery clips={store.visibleClips} clipActions={{onRename:rename,onOpen:open,onBeginRename:rename}}/></>;}
const click=async(element:Element,extra:MouseEventInit={})=>act(async()=>element.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,...extra})));
const key=async(element:Element,name:string,extra:KeyboardEventInit={})=>act(async()=>element.dispatchEvent(new KeyboardEvent('keydown',{key:name,bubbles:true,cancelable:true,...extra})));
const cards=()=>container.querySelectorAll<HTMLElement>('.clip-card');
const button=(text:string)=>[...container.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent===text)!;
beforeEach(async()=>{
 vi.clearAllMocks();vi.mocked(api.jobs).mockResolvedValue([]);vi.mocked(api.games).mockResolvedValue([]);setLocale('en');vi.mocked(api.clips).mockResolvedValue(clips);vi.mocked(connectWs).mockImplementation(callback=>{message=callback;return ()=>{};});
 container=document.createElement('div');document.body.append(container);root=createRoot(container);await act(async()=>root.render(<StoreProvider><Harness/></StoreProvider>));
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.useRealTimers();setLocale('en');});
describe('shared gallery interactions',()=>{
 it('single-click titles select their exact text, confirm and cancel without opening the viewer',async()=>{
  await click(cards()[0].querySelector('.clip-name')!);const input=cards()[0].querySelector('input')!;expect(document.activeElement).toBe(input);expect(input.selectionEnd).toBe(1);expect(open).not.toHaveBeenCalled();
  await key(input,'Escape');expect(rename).not.toHaveBeenCalled();
  await click(cards()[0].querySelector('.clip-thumb')!);expect(open).toHaveBeenCalledExactlyOnceWith(clips[0]);
 });
 it('Ctrl/Shift thumbnail clicks select ordered ranges and checkboxes toggle without playback or drag',async()=>{
  await click(cards()[1].querySelector('.clip-thumb')!,{ctrlKey:true});expect(store.state.selectedMedia).toEqual(['b']);
  await click(cards()[3].querySelector('.clip-thumb')!,{shiftKey:true});expect(store.state.selectedMedia).toEqual(['b','c','d']);expect(open).not.toHaveBeenCalled();
  expect(cards()[0].draggable).toBe(false);await click(cards()[2].querySelector('.media-select')!);expect(store.state.selectedMedia).toEqual(['b','d']);
  expect(cards()[1].getAttribute('data-selected')).toBe('true');
 });
 it('Select All is scoped to filtered results and Escape exits selection without consuming text input keys',async()=>{
  await act(async()=>store.dispatch({type:'setSearch',query:'b'}));expect(cards()).toHaveLength(1);
  const gallery=container.querySelector('.media-gallery')!;await key(gallery,'a',{ctrlKey:true});expect(store.state.selectedMedia).toEqual(['b']);
  await click(cards()[0].querySelector('.clip-name')!);const input=cards()[0].querySelector<HTMLInputElement>('.clip-rename')!;
  await key(input,'a',{ctrlKey:true});expect(store.state.selectedMedia).toEqual(['b']);await key(input,'Escape');
  await key(gallery,'Escape');expect(store.state.selectionMode).toBe(false);expect(store.state.selectedMedia).toEqual([]);
 });
 it('F2 targets the one selected source and retains selection across a semantic rename',async()=>{
  await click(cards()[0].querySelector('.clip-thumb')!,{ctrlKey:true});await key(container.querySelector('.media-gallery')!,'F2');expect(rename).toHaveBeenCalledWith(clips[0]);
  await act(async()=>message({type:'clip_renamed',old_slug:'a',clip:{...clips[0],slug:'renamed',name:'new!.mp4',display_title:'new!'}}));
  expect(store.state.selectedMedia).toEqual(['a']);expect(cards()[0].getAttribute('data-selected')).toBe('true');expect(cards()[0].textContent).toContain('new!');expect(cards()[0].textContent).not.toContain('New');
 });
 it('follows authoritative job IDs, not filenames, and exposes the shared queue controls',async()=>{
  const job={id:'job',operation:'trim',mode:'copy',source_media_ids:['b'],name:'a.mp4',status:'processing',stage:'encode',progress:.42,elapsed:1,remaining:2,speed:1,can_pause:true} as ProcessingJob;
  await act(async()=>message({type:'jobs_changed',jobs:[job]}));expect(cards()[0].querySelector('.media-job')).toBeNull();expect(cards()[1].querySelector('.media-job')!.textContent).toContain('42%');
  await click(cards()[1].querySelector('.media-job')!);expect(store.state.queueJobId).toBe('job');expect(container.querySelector('[role=dialog]')!.textContent).toContain('Pause');
  await click(button('Pause'));expect(api.jobControl).toHaveBeenCalledWith('job','pause');
 });
 it('previews and confirms exact bulk names and reports mixed successes truthfully',async()=>{
  await click(cards()[0].querySelector('.clip-thumb')!,{ctrlKey:true});await click(cards()[1].querySelector('.clip-thumb')!,{ctrlKey:true});
  const plans=clips.slice(0,2).map(clip=>({id:clip.library_id!,title:clipTitle(clip)+' !',previous_title:clipTitle(clip),filename:clipTitle(clip)+' !.mp4',revision:'r',physical_rename:true} as RenamePlan));
  vi.mocked(api.renamePreview).mockResolvedValue({items:plans,valid:true});vi.useFakeTimers();await click(button('Bulk rename'));await act(async()=>vi.advanceTimersByTime(160));
  expect(container.textContent).toContain('a !');expect(api.libraryActions).not.toHaveBeenCalled();
  vi.mocked(api.libraryActions).mockResolvedValue({results:[{id:'a',ok:true},{id:'b',ok:false,code:'busy'}]});await click(button('Apply to 2 items'));
  expect(api.libraryActions).toHaveBeenCalledWith('rename',['a','b'],expect.objectContaining({confirm:true,plans}));expect(container.textContent).toContain('1 succeeded · 1 failed · 2 attempted');expect(container.textContent).toContain('being processed');expect(store.state.selectedMedia).toEqual(['b']);
 });
 it('bulk deletion requires confirmation and delegates to managed Trash',async()=>{
  await click(cards()[0].querySelector('.clip-thumb')!,{ctrlKey:true});await click(button('Move to Trash'));expect(api.libraryActions).not.toHaveBeenCalled();expect(container.textContent).toContain('They can be restored');
  vi.mocked(api.libraryActions).mockResolvedValue({results:[{id:'a',ok:true}]});await click(button('Apply to 1 items'));expect(api.libraryActions).toHaveBeenCalledWith('trash',['a'],expect.objectContaining({confirm:true}));
 });
 it('shows the shared controls in French',async()=>{
  setLocale('fr');await act(async()=>root.render(<StoreProvider><Harness/></StoreProvider>));expect(container.textContent).toContain('Sélectionner');
 });
});

describe('recovered queue states and batch safety',()=>{
 it('recovers indicators from the startup snapshot and follows pause, failure and completion after rename',async()=>{
  vi.useFakeTimers();const job={id:'persisted',operation:'trim',mode:'replace',source_media_ids:['c'],name:'unrelated old filename.mp4',status:'paused',stage:'encode',progress:.6,elapsed:1,remaining:2,speed:1,can_pause:true,finished_at:null} as ProcessingJob;
  vi.mocked(api.jobs).mockResolvedValue([job]);await act(async()=>root.render(<StoreProvider key="reopened"><Harness/></StoreProvider>));
  expect(cards()[2].querySelector('.media-job')!.textContent).toContain('Paused');expect(cards()[0].querySelector('.media-job')).toBeNull();
  await act(async()=>message({type:'clip_renamed',old_slug:'c',clip:{...clips[2],slug:'C exact!',display_title:'C exact!'}}));
  expect(cards()[2].querySelector('.media-job')!.textContent).toContain('Paused');
  await act(async()=>message({type:'jobs_changed',jobs:[{...job,status:'failed',error:'Encoder unavailable'}]}));expect(cards()[2].querySelector('.media-job')!.textContent).toContain('Failed');
  await act(async()=>message({type:'jobs_changed',jobs:[{...job,status:'completed',progress:1,finished_at:new Date().toISOString()}]}));expect(cards()[2].querySelector('.media-job')!.textContent).toContain('Completed');
  await act(async()=>vi.advanceTimersByTime(5100));expect(cards()[2].querySelector('.media-job')).toBeNull();
 });
 it('does not enable rename application for a collision preview',async()=>{
  await click(cards()[0].querySelector('.clip-thumb')!,{ctrlKey:true});
  vi.mocked(api.renamePreview).mockResolvedValue({items:[{id:'a',code:'collision'} as RenamePlan],valid:false});vi.useFakeTimers();await click(button('Bulk rename'));await act(async()=>vi.advanceTimersByTime(160));
  expect(button('Apply to 1 items').disabled).toBe(true);expect(container.textContent).toContain('No file was overwritten');expect(api.libraryActions).not.toHaveBeenCalled();
 });
 it('stops bulk work between chunks and reports only the items actually attempted',async()=>{
  const many=Array.from({length:25},(_,i)=>({...clips[0],slug:`clip${i}`,name:`clip${i}.mp4`,display_title:`clip${i}`,library_id:`id${i}`}));
  vi.mocked(api.clips).mockResolvedValue(many);await act(async()=>store.dispatch({type:'setClips',clips:many}));
  await key(container.querySelector('.media-gallery')!,'a',{ctrlKey:true});await click(button('Move to Trash'));
  let resolve!:(value:{results:Array<{id:string;ok:boolean}>})=>void;const pending=new Promise<{results:Array<{id:string;ok:boolean}>}>(yes=>{resolve=yes;});
  vi.mocked(api.libraryActions).mockReturnValueOnce(pending);
  await act(async()=>{button('Apply to 25 items').click();});expect(api.libraryActions).toHaveBeenCalledOnce();
  await click(button('Stop after this batch'));await act(async()=>resolve({results:many.slice(0,20).map(item=>({id:item.library_id,ok:true}))}));
  expect(api.libraryActions).toHaveBeenCalledOnce();expect(container.textContent).toContain('20 succeeded · 0 failed · 20 attempted');expect(store.state.selectedMedia).toHaveLength(5);
 });
 it('assigns or removes a game through stable media IDs and explicit confirmation',async()=>{
  await act(async()=>store.dispatch({type:'gamesSnapshot',games:[{id:'rocket',name:'Rocket League',status:'confirmed'} as import('../lib/types').DetectedGame]}));
  await click(cards()[0].querySelector('.clip-thumb')!,{ctrlKey:true});await click(button('Assign game'));
  const select=container.querySelector<HTMLSelectElement>('select[aria-label="Choose a game"]')!;
  await act(async()=>{select.value='rocket';select.dispatchEvent(new Event('change',{bubbles:true}));});
  vi.mocked(api.libraryActions).mockResolvedValue({results:[{id:'a',ok:true}]});await click(button('Apply to 1 items'));
  expect(api.libraryActions).toHaveBeenCalledWith('game',['a'],expect.objectContaining({game_id:'rocket',confirm:true}));
 });
});
