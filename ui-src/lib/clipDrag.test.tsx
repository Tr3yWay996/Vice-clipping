import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {api} from './api';
import {attachVideoFile, endClipDrag, fileUri, prepareClipDrag, startClipDrag, usePlaylistDropTarget} from './clipDrag';
import type {Clip, Playlist} from './types';
vi.mock('./api', () => ({api: {originalFile: vi.fn(), addClipToPlaylist: vi.fn().mockResolvedValue({ok:true})}}));
const clip = {slug:'match', name:'Été #1.mp4', video_url:'/video/match?v=one', duration:10} as Clip;
function drag() {
 const data=new Map<string,string>();
 return {event:{dataTransfer:{setData:(type:string,value:string)=>data.set(type,value),getData:(type:string)=>data.get(type)??'',setDragImage:vi.fn()},preventDefault:vi.fn(),currentTarget:document.body} as unknown as React.DragEvent,data};
}
afterEach(()=>{delete (window as any).pywebview;endClipDrag();vi.clearAllMocks();});
describe('original clip file dragging',()=>{
 it('uses encoded original file URIs and preserves playlist drops without preparing a conversion',async()=>{
  const uri=fileUri('/videos/Été #1.mp4');
  vi.mocked(api.originalFile).mockResolvedValue({uri,path:'/videos/Été #1.mp4',filename:'Été #1.mp4',size:20});
  prepareClipDrag(clip);await Promise.resolve();
  const {event,data}=drag();startClipDrag(event,clip);
  expect(uri).toBe('file:///videos/%C3%89t%C3%A9%20%231.mp4');
  expect(data.get('text/uri-list')).toBe(uri+'\r\n');
  expect(data.get('application/x-vice-clip')).toBe('match');
  expect(event.preventDefault).not.toHaveBeenCalled();
  expect(document.querySelector('.clip-drag-ghost')).not.toBeNull();
  const container=document.createElement('div');document.body.append(container);const root=createRoot(container);
  function Target(){const drop=usePlaylistDropTarget({id:'p',name:'Favorites',clip_slugs:[]} as unknown as Playlist,vi.fn());return <div {...drop.props}/>;}
  try{
   await act(async()=>root.render(<Target/>));
   const drop=new Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(drop,'dataTransfer',{value:event.dataTransfer});
   await act(async()=>container.firstElementChild!.dispatchEvent(drop));
   expect(api.addClipToPlaylist).toHaveBeenCalledWith('p','match');
   vi.mocked(api.addClipToPlaylist).mockClear();
   await act(async()=>container.firstElementChild!.dispatchEvent(new CustomEvent('vice-native-clip-drop', {
    bubbles:true,detail:{slug:'native-match'},
   })));
   expect(api.addClipToPlaylist).toHaveBeenCalledWith('p','native-match');
  }finally{await act(async()=>root.unmount());container.remove();}
 });
 it('uses the native bridge with an identifier only and reports rejected targets',async()=>{
  const native=vi.fn().mockResolvedValue({ok:false,reason:'rejected'});
  (window as any).pywebview={api:{drag_clip:native,file_drag_capabilities:vi.fn().mockResolvedValue(true)}};
  const fallback=vi.fn();window.addEventListener('vice-drag-unavailable',fallback);
  try{
   const {event}=drag();attachVideoFile(event,clip);
   await Promise.resolve();await Promise.resolve();
   expect(event.preventDefault).toHaveBeenCalled();
   expect(native).toHaveBeenCalledWith('match',false,expect.any(Object));
   expect(fallback).toHaveBeenCalledOnce();
  }finally{window.removeEventListener('vice-drag-unavailable',fallback);}
 });
 it('retains the HTML file fallback on non-Qt desktops and reuses explicitly prepared files',async()=>{
  const native=vi.fn();(window as any).pywebview={api:{drag_clip:native,file_drag_capabilities:vi.fn().mockResolvedValue(false)}};
  prepareClipDrag(clip);await Promise.resolve();
  const {event,data}=drag();attachVideoFile(event,clip,'/cache/Prepared é.mp4');
  expect(native).not.toHaveBeenCalled();expect(event.preventDefault).not.toHaveBeenCalled();
  expect(data.get('text/uri-list')).toBe('file:///cache/Prepared%20%C3%A9.mp4\r\n');
 });
});
