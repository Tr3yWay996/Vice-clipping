import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {bindPlaybackShortcuts,playbackShortcut} from './playbackShortcuts';
const cleanups:Array<()=>void>=[];
afterEach(()=>{cleanups.splice(0).reverse().forEach(fn=>fn());document.body.replaceChildren();});
const root=(modal=false)=>{const element=document.createElement('div');if(modal){element.setAttribute('role','dialog');element.setAttribute('aria-modal','true');}document.body.append(element);return element;};
const key=(name:string,target:EventTarget=document.body,extra:KeyboardEventInit={})=>{const e=new KeyboardEvent('keydown',{key:name,bubbles:true,cancelable:true,...extra});target.dispatchEvent(e);return e;};
describe('one shared playback shortcut dispatcher',()=>{
 it('routes only to the top modal owner, even when an editor beneath it has a higher base priority',()=>{
  const editor=root(),viewer=root(true),trim=root(true);const e=vi.fn(()=>true),v=vi.fn(()=>true),t=vi.fn(()=>true);
  cleanups.push(bindPlaybackShortcuts({root:()=>editor,priority:20,handle:e}),bindPlaybackShortcuts({root:()=>viewer,priority:10,handle:v}));
  const unbind=bindPlaybackShortcuts({root:()=>trim,priority:30,handle:t});key(' ');expect(t).toHaveBeenCalledOnce();expect(v).not.toHaveBeenCalled();expect(e).not.toHaveBeenCalled();
  unbind();trim.remove();key(' ');expect(v).toHaveBeenCalledOnce();expect(e).not.toHaveBeenCalled();
  viewer.remove();key(' ');expect(e).toHaveBeenCalledOnce();
 });
 it('leaves text, dropdowns, accessibility widgets and unhandled combinations alone',()=>{
  const el=root();const handle=vi.fn(()=>true);cleanups.push(bindPlaybackShortcuts({root:()=>el,priority:10,handle}));
  for(const html of ['<input>','<textarea></textarea>','<select></select>','<div contenteditable="true"></div>','<div role="combobox"></div>','<div role="switch"></div>']){
   el.innerHTML=html;expect(key(' ',el.firstElementChild!).defaultPrevented).toBe(false);
  }
  expect(handle).not.toHaveBeenCalled();
  const toggle=vi.fn(),mute=vi.fn();
  expect(playbackShortcut(new KeyboardEvent('keydown',{key:' ',ctrlKey:true}),{toggle,mute})).toBe(false);
  expect(playbackShortcut(new KeyboardEvent('keydown',{key:'i',isComposing:true}),{toggle,mute,boundary:vi.fn()})).toBe(false);
  expect(toggle).not.toHaveBeenCalled();
 });
 it('cleans up its single global listener and consumes repeat toggles once',()=>{
  const el=root(),toggle=vi.fn(),mute=vi.fn();const unbind=bindPlaybackShortcuts({root:()=>el,priority:10,handle:e=>playbackShortcut(e,{toggle,mute})});
  expect(key(' ').defaultPrevented).toBe(true);key(' ',document.body,{repeat:true});expect(toggle).toHaveBeenCalledOnce();
  unbind();expect(key(' ').defaultPrevented).toBe(false);expect(toggle).toHaveBeenCalledOnce();
 });
 it('blocks an export dialog nested inside the editor playback root',()=>{
  const editor=root(),handle=vi.fn(()=>true);
  cleanups.push(bindPlaybackShortcuts({root:()=>editor,priority:20,handle}));
  const modal=root(true);editor.append(modal);
  key('ArrowRight');expect(handle).not.toHaveBeenCalled();
 });
 it('routes Space after a mouse click on an ordinary control but preserves Tab activation',()=>{
  const el=root(),toggle=vi.fn(),click=vi.fn();const button=document.createElement('button');el.append(button);button.addEventListener('click',click);
  cleanups.push(bindPlaybackShortcuts({root:()=>el,priority:10,handle:e=>playbackShortcut(e,{toggle,mute:vi.fn()})}));
  button.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true}));button.focus();
  expect(key(' ',button).defaultPrevented).toBe(true);expect(toggle).toHaveBeenCalledOnce();expect(click).not.toHaveBeenCalled();
  key('Tab',button);expect(key(' ',button).defaultPrevented).toBe(false);expect(toggle).toHaveBeenCalledOnce();
 });
 it('keeps transport keys after mouse-focused volume and native range steps after Tab',()=>{
  const el=root();el.innerHTML='<input type="range" data-playback-control="volume"><input type="range"><input type="text">';
  const toggle=vi.fn(),seek=vi.fn(),setVolume=vi.fn(),mute=vi.fn();
  cleanups.push(bindPlaybackShortcuts({root:()=>el,priority:10,handle:e=>playbackShortcut(e,{toggle,mute,seek,setVolume,volume:()=>.4,time:()=>10,duration:()=>50})}));
  const volume=el.firstElementChild as HTMLInputElement;volume.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true}));volume.focus();
  key(' ',volume);key('ArrowRight',volume);key('ArrowUp',volume);key('m',volume);key('End',volume);
  expect(toggle).toHaveBeenCalledOnce();expect(seek.mock.calls).toEqual([[11],[50]]);expect(setVolume).toHaveBeenCalledWith(.45);expect(mute).toHaveBeenCalledOnce();
  key('Tab',volume);expect(key('ArrowRight',volume).defaultPrevented).toBe(false);expect(seek).toHaveBeenCalledTimes(2);
  expect(key(' ',volume).defaultPrevented).toBe(true);expect(toggle).toHaveBeenCalledTimes(2);
  for(const input of [...el.querySelectorAll('input')].slice(1)){input.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true}));input.focus();expect(key(' ',input).defaultPrevented).toBe(false);}
 });
 it('does not take Space from unrelated controls outside the active player',()=>{
  const el=root(),button=document.createElement('button'),toggle=vi.fn();document.body.append(button);
  cleanups.push(bindPlaybackShortcuts({root:()=>el,priority:10,handle:e=>playbackShortcut(e,{toggle,mute:vi.fn()})}));
  button.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true}));button.focus();
  expect(key(' ',button).defaultPrevented).toBe(false);expect(toggle).not.toHaveBeenCalled();
 });
});

describe('Space tap/hold ownership and recovery',()=>{
 let rate:number,paused:boolean,multiplier:number,toggle:ReturnType<typeof vi.fn<() => void>>;
 beforeEach(()=>{vi.useFakeTimers();rate=1.25;paused=true;multiplier=2;toggle=vi.fn(()=>{paused=!paused;});});
 afterEach(()=>vi.useRealTimers());
 function bind(el:HTMLElement){const control={rate:()=>rate,setRate:(n:number)=>{rate=n;},paused:()=>paused,
  play:()=>{paused=false;},pause:()=>{paused=true;},multiplier:()=>multiplier,setMultiplier:(n:number)=>{multiplier=n;}};
  const unbind=bindPlaybackShortcuts({root:()=>el,priority:10,handle:e=>playbackShortcut(e,{toggle,mute:vi.fn()}),boost:()=>control});cleanups.push(unbind);return unbind;
 }
 const up=()=>document.body.dispatchEvent(new KeyboardEvent('keyup',{key:' ',bubbles:true,cancelable:true}));
 it('toggles once on short release, ignores repeat, and prevents page scrolling',()=>{
  bind(root());expect(key(' ').defaultPrevented).toBe(true);key(' ',document.body,{repeat:true});
  vi.advanceTimersByTime(100);expect(toggle).not.toHaveBeenCalled();up();expect(toggle).toHaveBeenCalledOnce();expect(paused).toBe(false);expect(rate).toBe(1.25);
 });
 it.each([true,false])('boosts, adjusts and restores rate and prior paused=%s without a toggle',initial=>{
  paused=initial;bind(root());key(' ');vi.advanceTimersByTime(250);expect(rate).toBe(2);expect(paused).toBe(false);
  const event=new WheelEvent('wheel',{deltaY:-1,bubbles:true,cancelable:true});document.body.dispatchEvent(event);expect(event.defaultPrevented).toBe(true);expect(rate).toBe(2.25);
  for(let n=0;n<50;n++)document.body.dispatchEvent(new WheelEvent('wheel',{deltaY:1,bubbles:true,cancelable:true}));expect(rate).toBe(.25);
  up();expect(rate).toBe(1.25);expect(paused).toBe(initial);expect(toggle).not.toHaveBeenCalled();
 });
 it.each(['blur','typing','unmount','modal'])('restores on %s, discards pending taps and ignores a late release',async reason=>{
  const el=root();const unbind=bind(el);key(' ');vi.advanceTimersByTime(300);
  if(reason==='blur')window.dispatchEvent(new Event('blur'));
  if(reason==='typing'){const input=document.createElement('input');el.append(input);input.focus();}
  if(reason==='unmount')unbind();
  if(reason==='modal'){root(true);await Promise.resolve();}
  expect(rate).toBe(1.25);expect(paused).toBe(true);up();expect(toggle).not.toHaveBeenCalled();
 });
 it('does not boost or consume Space while typing or on native buttons',()=>{
  const el=root();bind(el);for(const tag of ['input','button']){const child=document.createElement(tag);el.append(child);key(' ',child);vi.advanceTimersByTime(300);up();expect(rate).toBe(1.25);expect(toggle).not.toHaveBeenCalled();}
 });
});
