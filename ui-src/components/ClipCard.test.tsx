import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {ClipCard} from './ClipCard';
import type {Clip} from '../lib/types';
vi.mock('../lib/clipDrag',()=>({prepareClipDrag:vi.fn(),startClipDrag:vi.fn(),endClipDrag:vi.fn()}));
let root:Root,container:HTMLElement;
beforeEach(()=>{container=document.createElement('div');document.body.append(container);root=createRoot(container);});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();});
it('F2 edits only the focused library card, selects its name and cancels without opening it',async()=>{
 const rename=vi.fn(),open=vi.fn();const clip={slug:'one',name:'First.mp4'} as Clip;
 await act(async()=>root.render(<><ClipCard clip={clip} actions={{onRename:rename,onOpen:open}}/><ClipCard clip={{...clip,slug:'two',name:'Second.mp4'}} actions={{onRename:rename,onOpen:open}}/></>));
 const cards=container.querySelectorAll('article');(cards[1] as HTMLElement).focus();
 await act(async()=>document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'F2',bubbles:true,cancelable:true})));
 expect(cards[0].querySelector('input')).toBeNull();const input=cards[1].querySelector('input')!;
 expect(input.value).toBe('Second');expect(document.activeElement).toBe(input);expect(input.selectionEnd).toBe(6);
 await act(async()=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
 expect(rename).not.toHaveBeenCalled();expect(open).not.toHaveBeenCalled();expect(cards[1].querySelector('input')).toBeNull();
});
it('clicking a title preserves leading spaces, punctuation and Unicode on blur without opening or dragging',async()=>{
 const rename=vi.fn(),open=vi.fn();const clip={slug:'original',name:'Original.mp4',display_title:"Ça, c'était beau."} as Clip;
 await act(async()=>root.render(<ClipCard clip={clip} draggable actions={{onRename:rename,onOpen:open}}/>));
 const title=container.querySelector('.clip-name')!;await act(async()=>title.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true})));
 const input=container.querySelector('input')!;expect(input.value).toBe("Ça, c'était beau.");expect(document.activeElement).toBe(input);expect(input.selectionEnd).toBe(input.value.length);
 await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'  What a save!? 🎮  ');input.dispatchEvent(new Event('input',{bubbles:true}));});
 await act(async()=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true})));
 expect(rename).toHaveBeenCalledExactlyOnceWith(clip,'  What a save!? 🎮  ');expect(open).not.toHaveBeenCalled();
});
