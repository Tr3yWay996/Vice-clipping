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
let engine:EditorEngine,root:HTMLElement,notify:ReturnType<typeof vi.fn<(title:string,tone?:'accent'|'error')=>void>>;
const key=(name:string,extra:KeyboardEventInit={},target:Element=document.body)=>{
 const event=new KeyboardEvent('keydown',{key:name,bubbles:true,cancelable:true,...extra});target.dispatchEvent(event);return event;
};
beforeEach(async()=>{
 vi.stubGlobal('ResizeObserver',class {observe(){} disconnect(){}});
 vi.useFakeTimers();vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>({ok:true,json:async()=>({project:fixture()})})));
 vi.stubGlobal('matchMedia',()=>({matches:true}));
 root=document.createElement('div');root.className='editor';document.body.append(root);
 const nodes=Array.from({length:6},()=>{const el=document.createElement('div');root.append(el);return el;});
 notify=vi.fn();engine=createEditorEngine({clips:()=>[clip],notify,accent:()=> '#0099ff'});await engine.load();
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
});
