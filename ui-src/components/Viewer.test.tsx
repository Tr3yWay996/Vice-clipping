import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {Viewer} from './Viewer';
import type {Clip} from '../lib/types';
const store=vi.hoisted(()=>({state:{config:{ui:{arrow_key_behavior:'playback'}}}}));
vi.mock('../state/store',()=>({useStore:()=>store}));
vi.mock('../lib/api',()=>({api:{markViewed:vi.fn().mockResolvedValue({}),clipKeys:vi.fn().mockResolvedValue(null)}}));
let container:HTMLElement,root:Root;
const renamed=vi.fn();const closed=vi.fn();
const selected=vi.fn();const clip={slug:'one',name:'one.mp4',video_url:'/v/one?v=1',duration:20} as Clip;
const key=async(name:string,extra:KeyboardEventInit={})=>act(async()=>{document.body.dispatchEvent(new KeyboardEvent('keydown',{key:name,bubbles:true,cancelable:true,...extra}));});
const media=()=>container.querySelector('video')!;
beforeEach(async()=>{
 localStorage.clear();store.state.config.ui.arrow_key_behavior='playback';selected.mockClear();renamed.mockClear();closed.mockClear();
 vi.stubGlobal('matchMedia',()=>({matches:true}));container=document.createElement('div');document.body.append(container);root=createRoot(container);
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.unstubAllGlobals();});
async function renderViewer(shown=clip,renameTransition?:{from:string;to:string}){await act(async()=>root.render(<Viewer clip={shown} renameTransition={renameTransition} clips={[clip,{...clip,slug:'two'}]} highlights={[]}
 onHighlightsChange={vi.fn()} onSelect={selected} onClose={closed} onTrim={vi.fn()} trimOpen={false} onShare={vi.fn()}
 onShareMenu={vi.fn()} shareLabel="share" onReveal={vi.fn()} onDelete={vi.fn()} onOpenExternally={vi.fn()} onRename={renamed} notify={vi.fn()}/>));}
async function mount(){await renderViewer();
 Object.defineProperty(media(),'videoWidth',{value:640,configurable:true});Object.defineProperty(media(),'readyState',{value:4,configurable:true});
 Object.defineProperty(media(),'duration',{value:20,configurable:true});
 await act(async()=>{media().dispatchEvent(new Event('loadedmetadata'));media().dispatchEvent(new Event('loadeddata'));});media().currentTime=10;
}
describe('viewer keyboard preference',()=>{
 it('defaults to playback navigation with fine seek, clamping, volume and unchanged playback state',async()=>{
  await mount();const playing=media().paused;
  await key('ArrowLeft');expect(media().currentTime).toBe(9);
  await key('ArrowRight',{shiftKey:true});expect(media().currentTime).toBe(9.1);
  expect(selected).not.toHaveBeenCalled();expect(media().paused).toBe(playing);
  await key('ArrowDown');expect(media().volume).toBe(.95);
  await key('ArrowUp');await key('ArrowUp');expect(media().volume).toBe(1);
  await key('Home');await key('ArrowLeft');expect(media().currentTime).toBe(0);
  await key('End');await key('ArrowRight');expect(media().currentTime).toBe(20);
  await key('m');expect(media().muted).toBe(true);
 });
 it('keeps legacy clip navigation available',async()=>{
  store.state.config.ui.arrow_key_behavior='clips';await mount();
  await key('ArrowRight');expect(selected).toHaveBeenCalledWith('two');expect(media().currentTime).toBe(10);
  await key('ArrowDown');expect(media().volume).toBe(1);
 });
 it('does not respond behind a modal or to browser shortcuts',async()=>{
  await mount();await key('ArrowLeft',{ctrlKey:true});expect(media().currentTime).toBe(10);
  const dialog=document.createElement('div');dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');document.body.append(dialog);
  try{await key('ArrowLeft');expect(media().currentTime).toBe(10);}finally{dialog.remove();}
 });
});

describe('single-click viewer title renaming',()=>{
 it('focuses/selects the name and commits once without touching playback',async()=>{
  await mount();const playing=media().paused;const position=media().currentTime;
  await act(async()=>container.querySelector<HTMLElement>('.viewer-heading h2')!.click());
  const input=container.querySelector<HTMLInputElement>('.viewer-rename')!;
  expect(document.activeElement).toBe(input);expect(input.selectionStart).toBe(0);expect(input.selectionEnd).toBe(3);
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'New name');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true})));
  expect(renamed).toHaveBeenCalledExactlyOnceWith(clip,'New name');expect(media().currentTime).toBe(position);expect(media().paused).toBe(playing);expect(closed).not.toHaveBeenCalled();
 });
 it('cancels with Escape and leaves the viewer open',async()=>{
  await mount();await act(async()=>container.querySelector<HTMLElement>('.viewer-heading h2')!.click());
  const input=container.querySelector<HTMLInputElement>('.viewer-rename')!;
  await act(async()=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true})));
  expect(renamed).not.toHaveBeenCalled();expect(closed).not.toHaveBeenCalled();expect(container.querySelector('.viewer-rename')).toBeNull();expect(media().currentTime).toBe(10);
 });
});

describe('viewer transport across a confirmed filename change',()=>{
 for(const paused of [true,false]) it(`preserves the current time and ${paused?'paused':'playing'} state without a new view`,async()=>{
  await mount();if(paused)media().pause();else await media().play();media().currentTime=12.5;
  const api=await import('../lib/api');vi.mocked(api.api.markViewed).mockClear();
  await renderViewer({...clip,slug:'renamed',name:'Renamed.mp4',video_url:'/v/renamed?v=new'},{from:'one',to:'renamed'});
  media().currentTime=0;await act(async()=>media().dispatchEvent(new Event('loadedmetadata')));
  expect(media().currentTime).toBe(12.5);expect(media().paused).toBe(paused);expect(api.api.markViewed).not.toHaveBeenCalled();
 });
});

describe('viewer F2 and temporary speed',()=>{
 it('opens the existing selected inline name on F2, respecting text and modal priority',async()=>{
  await mount();await key('F2');const input=container.querySelector<HTMLInputElement>('.viewer-rename')!;
  expect(document.activeElement).toBe(input);expect(input.selectionEnd).toBe(3);expect(media().currentTime).toBe(10);
  await act(async()=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
  const modal=document.createElement('div');modal.setAttribute('role','dialog');modal.setAttribute('aria-modal','true');document.body.append(modal);
  await key('F2');expect(container.querySelector('.viewer-rename')).toBeNull();modal.remove();
 });
 it('boosts while held and restores on release and clip change',async()=>{
  await mount();vi.useFakeTimers();media().playbackRate=1.5;media().pause();
  try{
   await key(' ');await act(async()=>vi.advanceTimersByTime(260));expect(media().playbackRate).toBe(2);expect(media().paused).toBe(false);
   expect(container.querySelector('output')?.textContent).toBe('2.00×');
   await act(async()=>document.body.dispatchEvent(new KeyboardEvent('keyup',{key:' ',bubbles:true,cancelable:true})));
   expect(media().playbackRate).toBe(1.5);expect(media().paused).toBe(true);expect(container.querySelector('output')).toBeNull();
   await key(' ');await act(async()=>vi.advanceTimersByTime(260));
   await renderViewer({...clip,slug:'two',video_url:'/v/two?v=2'});expect(media().playbackRate).toBe(1.5);
  }finally{vi.useRealTimers();}
 });
});

it('keeps playback keys after mouse focus on volume and buttons in inline/fullscreen mode',async()=>{
 await mount();await act(async()=>media().pause());
 const press=async(target:HTMLElement,name:string)=>act(async()=>{target.dispatchEvent(new KeyboardEvent('keydown',{key:name,bubbles:true,cancelable:true}));target.dispatchEvent(new KeyboardEvent('keyup',{key:name,bubbles:true,cancelable:true}));});
 const pointerFocus=async(target:HTMLElement)=>act(async()=>{target.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true,button:0}));target.focus();});
 const volume=container.querySelector<HTMLInputElement>('.player-volume-range')!;await pointerFocus(volume);await press(volume,' ');expect(media().paused).toBe(false);
 await press(volume,' ');expect(media().paused).toBe(true);await press(volume,'ArrowRight');expect(media().currentTime).toBe(11);
 const button=container.querySelector<HTMLElement>('.player-volume button')!;await pointerFocus(button);await press(button,' ');expect(media().paused).toBe(false);
 await act(async()=>container.querySelector<HTMLButtonElement>('button[aria-label="Fill the window"]')!.click());
 const expanded=container.querySelector<HTMLInputElement>('.viewer-expanded-bar .player-volume-range')!;await pointerFocus(expanded);await press(expanded,' ');expect(media().paused).toBe(true);
});

it('seeks and scrubs both viewer timelines immediately, updates readout, and clears buffering feedback',async()=>{
 await mount();await act(async()=>media().pause());
 const pointer=async(track:HTMLElement,type:string,x:number)=>act(async()=>{const event=new MouseEvent(type,{bubbles:true,button:0,clientX:x});Object.defineProperty(event,'pointerId',{value:1});track.dispatchEvent(event);});
 const track=container.querySelector<HTMLElement>('.viewer-timeline')!;
 await pointer(track,'pointerdown',500);expect(media().currentTime).toBe(10);expect(document.activeElement).toBe(track);
 await pointer(track,'pointermove',750);await pointer(track,'pointerup',250);expect(media().currentTime).toBe(5);expect(container.querySelector('.viewer-progress')!.getAttribute('style')).toContain('25%');
 await act(async()=>media().dispatchEvent(new Event('waiting')));expect(container.querySelector('[role=status]')?.textContent).toContain('Loading preview');
 await act(async()=>media().dispatchEvent(new Event('canplay')));expect(container.querySelector('[role=status]')).toBeNull();
 await act(async()=>container.querySelector<HTMLButtonElement>('button[aria-label="Fill the window"]')!.click());
 const fullscreen=container.querySelector<HTMLElement>('.viewer-expanded-bar .player-track')!;await pointer(fullscreen,'pointerdown',750);expect(media().currentTime).toBe(15);await pointer(fullscreen,'pointerup',500);expect(media().currentTime).toBe(10);expect(media().paused).toBe(true);
});
