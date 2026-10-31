import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {ImageCard} from './ImageCard';
import type {Image} from '../lib/types';
vi.mock('../lib/clipDrag',()=>({startImageDrag:vi.fn(),endClipDrag:vi.fn()}));
it('uses single-click and F2 inline renaming for screenshot cards without opening the image',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container),rename=vi.fn(),open=vi.fn();
 const image={slug:'shot',name:'Shot.png',display_title:'Nice shot!?'} as Image;
 try {
  await act(async()=>root.render(<ImageCard image={image} actions={{onRename:rename,onOpen:open}}/>));
  await act(async()=>container.querySelector<HTMLElement>('.clip-name')!.click());const input=container.querySelector('input')!;
  expect(document.activeElement).toBe(input);expect(input.value).toBe('Nice shot!?');expect(input.selectionEnd).toBe(11);
  await act(async()=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
  container.querySelector('article')!.focus();await act(async()=>document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'F2',bubbles:true,cancelable:true})));
  expect(document.activeElement).toBe(container.querySelector('input'));expect(open).not.toHaveBeenCalled();expect(rename).not.toHaveBeenCalled();
 }finally{await act(async()=>root.unmount());container.remove();}
});
