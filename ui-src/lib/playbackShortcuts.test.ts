import {afterEach,describe,expect,it,vi} from 'vitest';
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
});
