import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {createEditorEngine,type EditorEngine} from './editor';
import type {EdProject} from './editorTypes';
import type {Clip} from '../lib/types';
const clip={slug:'source',name:'source.mp4',video_url:'/video/source?v=1',duration:20,vcodec:'h264',audio_tracks:[{index:0},{index:1}]} as Clip;
const fixture=():EdProject=>({version:1,tracks:[{id:'V1',type:'video',label:'V1'},{id:'A1',type:'audio',label:'A1'},{id:'T1',type:'text',label:'T1'}],items:[
 {id:'v',kind:'clip',trackId:'V1',clipId:'source',start:5,dur:10,offset:2,muted:true,trans:{fx:'crossfade',len:1}},
 {id:'a',kind:'audio',trackId:'A1',clipId:'source',start:5,dur:10,offset:2,volume:.6},
 {id:'next',kind:'clip',trackId:'V1',clipId:'source',start:15,dur:2,offset:0,trans:{fx:'crossfade',len:1}},
]});
const renameSource=vi.fn();
let boostMultiplier=2;
let previewClips:Clip[];
let audioMedia:HTMLAudioElement[];
let engine:EditorEngine,root:HTMLElement,notify:ReturnType<typeof vi.fn<(title:string,tone?:'accent'|'error')=>void>>;
const key=(name:string,extra:KeyboardEventInit={},target:Element=document.body)=>{
 const event=new KeyboardEvent('keydown',{key:name,bubbles:true,cancelable:true,...extra});target.dispatchEvent(event);return event;
};
beforeEach(async()=>{
 vi.stubGlobal('ResizeObserver',class {observe(){} disconnect(){}});
 audioMedia=[];const NativeAudio=window.Audio;
 vi.stubGlobal('Audio',function(){const media=new NativeAudio();audioMedia.push(media);return media;});
 vi.useFakeTimers();vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>({ok:true,json:async()=>({project:fixture()})})));
 vi.stubGlobal('matchMedia',()=>({matches:true}));
 root=document.createElement('div');root.className='editor';document.body.append(root);
 const nodes=Array.from({length:6},()=>{const el=document.createElement('div');root.append(el);return el;});
 notify=vi.fn();renameSource.mockClear();boostMultiplier=2;previewClips=[clip];engine=createEditorEngine({clips:()=>previewClips,notify,accent:()=> '#0099ff',renameSource,
  playbackBoost:()=>({multiplier:()=>boostMultiplier,setMultiplier:rate=>{boostMultiplier=rate;}})});await engine.load();
 engine.mount({stage:nodes[0],stageWrap:nodes[1],timelineCanvas:nodes[2],timelineScroll:nodes[3],libraryScroll:nodes[4],fadeOverlay:nodes[5]});
 engine.select('v');engine.seek(8);
});
afterEach(()=>{engine.destroy();root.remove();vi.useRealTimers();vi.unstubAllGlobals();vi.restoreAllMocks();});
describe('editor shared transport and non-ripple keyboard trimming',()=>{
 it('trims source offsets and matching detached audio in one undo transaction without moving playback',()=>{
  key('i');expect(engine.snapshot().playhead).toBe(8);
  expect(engine.project()!.items.find(i=>i.id==='v')).toMatchObject({start:8,dur:7,offset:5});
  expect(engine.project()!.items.find(i=>i.id==='a')).toMatchObject({start:8,dur:7,offset:5});
  expect(engine.project()!.items.find(i=>i.id==='v')!.trans).toBeUndefined();
  engine.seek(12);key('o');
  expect(engine.project()!.items.find(i=>i.id==='v')).toMatchObject({start:8,dur:4,offset:5});
  expect(engine.project()!.items.find(i=>i.id==='a')).toMatchObject({start:8,dur:4,offset:5});
  expect(engine.project()!.items.find(i=>i.id==='next')).toMatchObject({start:15,dur:2,offset:0});
  expect(engine.project()!.items.find(i=>i.id==='next')!.trans).toBeUndefined();
  key('z',{ctrlKey:true});key('z',{ctrlKey:true});expect(engine.project()).toEqual(fixture());
  expect(engine.snapshot().playhead).toBe(12);
  key('z',{ctrlKey:true,shiftKey:true});expect(engine.project()!.items[0].start).toBe(8);
 });
 it('rejects missing selection, crossed boundaries and independently edited detached audio atomically',()=>{
  const original=JSON.stringify(engine.project());engine.select(null);key('i');expect(JSON.stringify(engine.project())).toBe(original);
  engine.select('v');engine.seek(14.8);key('i');expect(JSON.stringify(engine.project())).toBe(original);
  engine.project()!.items[1].start=6;engine.project()!.items[1].dur=9;engine.project()!.items[1].offset=3;
  const independent=JSON.stringify(engine.project());engine.seek(8);key('i');expect(JSON.stringify(engine.project())).toBe(independent);
  expect(engine.snapshot().canUndo).toBe(false);expect(notify).toHaveBeenCalled();
 });
 it('preserves editing shortcuts and stops routing when a dialog or text field owns input',()=>{
  const input=document.createElement('input');root.append(input);key(' ',{},input);expect(engine.snapshot().playing).toBe(false);
  key('i',{},input);expect(engine.project()!.items[0].start).toBe(5);
  const dialog=document.createElement('div');dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');root.append(dialog);
  key('i');key(' ');expect(engine.snapshot().playing).toBe(false);expect(engine.project()!.items[0].start).toBe(5);dialog.remove();
  key('s');expect(engine.project()!.items.filter(i=>i.kind==='clip')).toHaveLength(3);
  key('z',{ctrlKey:true});expect(engine.project()).toEqual(fixture());
  key('d',{ctrlKey:true});expect(engine.project()!.items).toHaveLength(4);
  key('Delete');expect(engine.project()!.items).toHaveLength(3);
  const position=engine.snapshot().playhead;engine.destroy();key('ArrowRight');expect(engine.snapshot().playhead).toBe(position);
 });
 it('uses shared seek steps, monitoring gain and mute without modifying track gains or project data',()=>{
  key('ArrowRight');expect(engine.snapshot().playhead).toBe(9);
  key('ArrowLeft',{shiftKey:true});expect(engine.snapshot().playhead).toBe(8.9);
  key('Home');expect(engine.snapshot().playhead).toBe(0);key('End');expect(engine.snapshot().playhead).toBe(17);
  engine.seek(8);engine.setMonitoring(.4,false);
  expect(engine.project()!.items[1].volume).toBe(.6);
  key('ArrowUp');const video=root.querySelector<HTMLVideoElement>('video:not(.ed-vhide)')!;
  expect(video.volume).toBeCloseTo(.45);expect(engine.project()!.items[1].volume).toBe(.6);
  const before=JSON.stringify(engine.project());key('m');expect(JSON.stringify(engine.project())).toBe(before);
  key(' ',{ctrlKey:true});expect(engine.snapshot().playing).toBe(false);
 });
 it('applies fine and repeated exact seeks after the decoder finishes a previous seek',()=>{
  const video=root.querySelector<HTMLVideoElement>('video:not(.ed-vhide)')!;
  let seeking=false;
  Object.defineProperty(video,'readyState',{value:4,configurable:true});
  Object.defineProperty(video,'seeking',{get:()=>seeking,configurable:true});
  (video as HTMLVideoElement & {_warmUntil:number})._warmUntil=0;
  engine.seek(8.1);expect(video.currentTime).toBeCloseTo(5.1);
  seeking=true;engine.seek(8.2);engine.seek(8.3);expect(video.currentTime).toBeCloseTo(5.1);
  seeking=false;video.dispatchEvent(new Event('seeked'));
  expect(video.currentTime).toBeCloseTo(5.3);expect(engine.snapshot().playhead).toBe(8.3);
  expect(engine.snapshot().playing).toBe(false);
 });
 it('parks an explicit paused seek immediately and prevents a stale warm-up timer from moving it',()=>{
  const video=root.querySelector<HTMLVideoElement>('video:not(.ed-vhide)')!;
  Object.defineProperty(video,'readyState',{value:4,configurable:true});
  expect(video.paused).toBe(true);
  video.dispatchEvent(new Event('loadedmetadata'));
  vi.advanceTimersByTime(400);
  expect(video.paused).toBe(true);expect(video.currentTime).toBe(5);
  expect(engine.snapshot().playhead).toBe(8);expect(engine.snapshot().playing).toBe(false);
 });
});

describe('recoverable source references with unsaved editor changes',()=>{
 it('keeps rejected autosaves dirty so a later save can retry',async()=>{
  key('i');const expected=JSON.stringify(engine.project());
  vi.mocked(fetch).mockResolvedValue({ok:false,status:503} as Response);
  await engine.saveNow();expect(engine.isDirty()).toBe(true);expect(JSON.stringify(engine.project())).toBe(expected);
  vi.mocked(fetch).mockResolvedValue({ok:true} as Response);
  await engine.saveNow();expect(engine.isDirty()).toBe(false);expect(JSON.stringify(engine.project())).toBe(expected);
 });
 it('merges trash/restore identities through current edits and undo history',async()=>{
  key('i');expect(engine.isDirty()).toBe(true);
  const remote=fixture();remote.items.forEach(item=>{item.clipId='trash:entry';item.sourceName='Original match.mp4'});
  vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({project:remote})} as Response);
  await engine.onProjectChanged();expect(engine.project()!.items[0].start).toBe(8);
  expect(engine.project()!.items.every(item=>item.clipId==='trash:entry')).toBe(true);expect(root.textContent).toContain('Original match.mp4');
  key('z',{ctrlKey:true});expect(engine.project()!.items[0].start).toBe(5);expect(engine.project()!.items[0].clipId).toBe('trash:entry');
  remote.items.forEach(item=>{item.clipId='restored-collision-name';delete item.sourceName});
  await engine.onProjectChanged();expect(engine.project()!.items[0].clipId).toBe('restored-collision-name');
  expect(engine.project()!.items[0].sourceName).toBeUndefined();expect(engine.project()!.items[0].start).toBe(5);
 });
 it('does not let undo resurrect permanently removed source references',async()=>{
  key('i');const remote=fixture();remote.items=[];
  vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({project:remote})} as Response);
  await engine.onProjectChanged();expect(engine.project()!.items).toEqual([]);
  key('z',{ctrlKey:true});expect(engine.project()!.items).toEqual([]);
 });
 it('keeps unsaved edits when source reconciliation cannot reach the daemon',async()=>{
  key('i');const expected=JSON.stringify(engine.project());vi.mocked(fetch).mockRejectedValue(new Error('offline'));
  await expect(engine.onProjectChanged()).resolves.toBeUndefined();expect(JSON.stringify(engine.project())).toBe(expected);expect(engine.isDirty()).toBe(true);
 });
});


describe('editor playback-only speed and source renaming',()=>{
 it('boosts video and detached audio without modifying project speed, timing, monitoring or export data',async()=>{
  const original=JSON.stringify(engine.project());
  key(' ');await vi.advanceTimersByTimeAsync(260);
  expect(engine.snapshot().playing).toBe(true);
  for(const media of root.querySelectorAll<HTMLMediaElement>('video,audio'))expect(media.playbackRate).toBe(2);
  document.body.dispatchEvent(new KeyboardEvent('keyup',{key:' ',bubbles:true,cancelable:true}));
  expect(engine.snapshot().playing).toBe(false);
  for(const media of root.querySelectorAll<HTMLMediaElement>('video,audio'))expect(media.playbackRate).toBe(1);
  expect(JSON.stringify(engine.project())).toBe(original);expect(engine.snapshot().canUndo).toBe(false);
 });
 it('routes F2 to the selected source or focused library card, never the project',()=>{
  key('F2');expect(renameSource).toHaveBeenCalledExactlyOnceWith(clip);renameSource.mockClear();
  engine.select(null);const library=root.querySelector<HTMLElement>('.ed-lib-clip')!;library.focus();key('F2');expect(renameSource).toHaveBeenCalledExactlyOnceWith(clip);
  renameSource.mockClear();const field=document.createElement('input');root.append(field);key('F2',{},field);expect(renameSource).not.toHaveBeenCalled();
 });
});


it('keeps the same decoder source during rename reconciliation even if another recording reuses the old slug',async()=>{
 previewClips=[{...clip,library_id:'stable'}];engine.setClips(previewClips);engine.seek(8);
 const video=root.querySelector<HTMLVideoElement>('video:not(.ed-vhide)')!;const src=video.getAttribute('src');
 previewClips=[{...clip,slug:'New title!?',name:'New title!?.mp4',library_id:'stable'}, {...clip,library_id:'different',video_url:'/wrong-video'}];
 engine.setClips(previewClips);engine.seek(8.2);
 expect(root.querySelector('[data-item=v]')!.classList.contains('missing')).toBe(false);expect(video.getAttribute('src')).toBe(src);
 const remote=fixture();remote.items.forEach(item=>{item.clipId='New title!?';});vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({project:remote})} as Response);
 await engine.onProjectChanged();expect(engine.project()!.items[0].clipId).toBe('New title!?');expect(video.getAttribute('src')).toBe(src);
});

/** Decoder times are controlled independently of the animation clock. */
describe('explicit editor seeking and authoritative media clocks',()=>{
 const current=()=>root.querySelector<HTMLVideoElement>('video:not(.ed-vhide)')!;
 function ready(){
  for(const media of [...root.querySelectorAll('video'),...audioMedia]){
   Object.defineProperty(media,'readyState',{value:4,configurable:true});
   media.dispatchEvent(new Event('loadedmetadata'));
  }
 }
 function longClip(){
  previewClips=[{...clip,duration:70}];
  const project=engine.project()!;
  project.items=project.items.filter(item=>item.id!=='next');
  project.items.forEach(item=>{item.start=0;item.dur=60;item.offset=2;delete item.trans;});
  engine.setClips(previewClips);engine.seek(10);ready();
 }
 it.each([false,true])('seeks 10s to 30s in the same clip with playing=%s and aligns detached audio',playing=>{
  longClip();engine.setPlaying(playing);
  const video=current(),audio=audioMedia[0],source=video.getAttribute('src'),project=JSON.stringify(engine.project());
  const setter=vi.spyOn(video,'currentTime','set');engine.seek(30);
  expect(video.currentTime).toBe(32);expect(audio.currentTime).toBe(32);expect(engine.snapshot()).toMatchObject({playhead:30,playing});
  vi.advanceTimersByTime(160);
  expect(engine.snapshot().playhead).toBe(30);expect(setter).toHaveBeenCalledTimes(1);
  expect(video.getAttribute('src')).toBe(source);expect(JSON.stringify(engine.project())).toBe(project);expect(engine.snapshot().canUndo).toBe(false);
 });
 it('lets the final rapid request win for video/audio while a previous seek is decoding',()=>{
  longClip();engine.setPlaying(true);const video=current(),audio=audioMedia[0];let seeking=true;
  for(const media of [video,audio])Object.defineProperty(media,'seeking',{get:()=>seeking,configurable:true});
  engine.seek(30);engine.seek(11);engine.seek(34);
  expect(engine.snapshot().playhead).toBe(34);expect(video.currentTime).toBe(12);
  vi.advanceTimersByTime(1000);expect(engine.snapshot()).toMatchObject({playhead:34,playing:true,preparing:true});
  seeking=false;video.dispatchEvent(new Event('seeked'));audio.dispatchEvent(new Event('seeked'));
  expect(video.currentTime).toBe(36);expect(audio.currentTime).toBe(36);
  vi.advanceTimersByTime(32);expect(engine.snapshot()).toMatchObject({playhead:34,playing:true,preparing:false});
 });
 it('freezes on stalled video, pauses detached audio, and resumes without wall-clock catch-up',()=>{
  longClip();engine.setPlaying(true);engine.seek(30);const video=current(),audio=audioMedia[0];
  Object.defineProperty(video,'readyState',{value:2,configurable:true});video.dispatchEvent(new Event('waiting'));
  expect(audio.paused).toBe(true);vi.advanceTimersByTime(4000);
  expect(engine.snapshot()).toMatchObject({playhead:30,playing:true,preparing:true});
  Object.defineProperty(video,'readyState',{value:4,configurable:true});video.dispatchEvent(new Event('canplay'));
  expect(audio.paused).toBe(false);video.currentTime=32.25;audio.currentTime=32.25;vi.advanceTimersByTime(32);
  expect(engine.snapshot()).toMatchObject({playhead:30.25,preparing:false});
 });
 it('uses the video clock even after a large decoder jump, without corrective seeks each frame',()=>{
  longClip();engine.setPlaying(true);const video=current();video.currentTime=32;
  const setter=vi.spyOn(video,'currentTime','set');vi.advanceTimersByTime(1000);
  expect(engine.snapshot().playhead).toBe(30);expect(setter).not.toHaveBeenCalled();
 });
 it('restarts the decoder and detached audio when Play wraps from the final frame',()=>{
  longClip();engine.seek(59.995);engine.setPlaying(true);
  expect(engine.snapshot()).toMatchObject({playhead:0,playing:true});
  expect(current().currentTime).toBe(2);expect(audioMedia[0].currentTime).toBe(2);
 });
 it('stops all tracks for detached-audio buffering and preserves the requested playhead',()=>{
  longClip();engine.setPlaying(true);engine.seek(30);const video=current(),audio=audioMedia[0];
  Object.defineProperty(audio,'readyState',{value:1,configurable:true});audio.dispatchEvent(new Event('waiting'));
  vi.advanceTimersByTime(500);expect(video.paused).toBe(true);expect(engine.snapshot()).toMatchObject({playhead:30,preparing:true});
  Object.defineProperty(audio,'readyState',{value:4,configurable:true});audio.dispatchEvent(new Event('canplay'));
  expect(video.paused).toBe(false);expect(audio.currentTime).toBe(32);expect(engine.snapshot().preparing).toBe(false);
 });
 it('follows detached audio in an audio-only region and wall time only in an empty gap',()=>{
  engine.project()!.items=engine.project()!.items.filter(item=>item.kind==='audio');engine.seek(8);ready();engine.setPlaying(true);
  audioMedia[0].currentTime=6;vi.advanceTimersByTime(32);expect(engine.snapshot().playhead).toBe(9);
  engine.seek(0);vi.advanceTimersByTime(1000);expect(engine.snapshot().playhead).toBeGreaterThan(.9);expect(engine.snapshot().playhead).toBeLessThan(1.1);
 });
 it('crosses a preloaded cut and synchronizes an explicit transition seek, overlays and lower tracks',()=>{
  const second={...clip,slug:'second',video_url:'/v/second',duration:70};previewClips=[{...clip,duration:70},second];
  engine.project()!.tracks.unshift({id:'V2',type:'video',label:'Lower'});
  // Track order determines the master; keep V1 above the overlapping V2.
  engine.project()!.tracks.reverse();
  engine.project()!.items=[
   {id:'one',kind:'clip',trackId:'V1',clipId:'source',start:0,dur:20,offset:2},
   {id:'two',kind:'clip',trackId:'V1',clipId:'second',start:20,dur:20,offset:0,trans:{fx:'crossfade',len:1}},
   {id:'under',kind:'clip',trackId:'V2',clipId:'source',start:18,dur:10,offset:5},
   {id:'sound',kind:'audio',trackId:'A1',clipId:'second',start:20,dur:20,offset:0},
   {id:'caption',kind:'text',trackId:'T1',start:20,dur:1,text:'Transition caption'},
  ];
  engine.setClips(previewClips);engine.seek(19);ready();engine.setPlaying(true);
  const outgoing=[...root.querySelectorAll<HTMLVideoElement>('video')].filter(video=>video.getAttribute('src')===clip.video_url&&!video.classList.contains('ed-vhide')).sort((a,b)=>Number(b.style.zIndex)-Number(a.style.zIndex))[0]!;
  outgoing.currentTime=22;vi.advanceTimersByTime(20);expect(engine.snapshot().playhead).toBe(20);
  engine.seek(20.5);ready();engine.seek(20.5);
  const incoming=[...root.querySelectorAll<HTMLVideoElement>('video:not(.ed-vhide)')].find(video=>video.getAttribute('src')==='/v/second')!;
  expect(incoming.currentTime).toBe(.5);expect(incoming.style.opacity).toBe('0.5');expect(root.textContent).toContain('Transition caption');
  expect(audioMedia[audioMedia.length-1].currentTime).toBe(.5);
  const under=[...root.querySelectorAll<HTMLVideoElement>('video:not(.ed-vhide)')].find(video=>Number(video.style.zIndex)<Number(incoming.style.zIndex)&&video!==outgoing)!;
  expect(under.currentTime).toBe(7.5);expect(engine.snapshot().playing).toBe(true);
 });
 it('scrubs ruler/empty lanes immediately, coalesces movement, and cleans up cancelled drags',()=>{
  longClip();const ruler=root.querySelector<HTMLElement>('#ed-ruler')!;
  const pointer=(element:Element,type:string,seconds:number)=>{const event=new MouseEvent(type,{bubbles:true,button:0,clientX:seconds*engine.snapshot().pps});Object.defineProperty(event,'pointerId',{value:1});element.dispatchEvent(event);};
  pointer(ruler,'pointerdown',30);expect(current().currentTime).toBe(32);
  pointer(ruler,'pointermove',31);pointer(ruler,'pointermove',32);pointer(ruler,'pointerup',33);expect(current().currentTime).toBe(35);
  pointer(ruler,'pointermove',40);vi.advanceTimersByTime(20);expect(engine.snapshot().playhead).toBe(33);
  const lane=root.querySelector<HTMLElement>('.ed-lane.video')!;pointer(lane,'pointerdown',10);expect(engine.snapshot().playhead).toBe(10);
  pointer(lane,'pointermove',11);pointer(lane,'pointercancel',11);vi.advanceTimersByTime(20);expect(engine.snapshot().playhead).toBe(10);
 });
 it('toggles from a video click while preserving the non-destructive project',()=>{
  longClip();const original=JSON.stringify(engine.project());current().click();expect(engine.snapshot().playing).toBe(true);
  current().click();expect(engine.snapshot().playing).toBe(false);expect(JSON.stringify(engine.project())).toBe(original);
 });
});
