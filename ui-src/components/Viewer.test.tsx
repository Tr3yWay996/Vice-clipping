import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {Viewer} from './Viewer';
import type {Clip} from '../lib/types';
const store=vi.hoisted(()=>({state:{config:{ui:{arrow_key_behavior:'playback'}}}}));
vi.mock('../state/store',()=>({useStore:()=>store}));
vi.mock('../lib/api',()=>({api:{markViewed:vi.fn().mockResolvedValue({}),clipKeys:vi.fn().mockResolvedValue(null)}}));
let container:HTMLElement,root:Root;
const selected=vi.fn();const clip={slug:'one',name:'one.mp4',video_url:'/v/one?v=1',duration:20} as Clip;
const key=async(name:string,extra:KeyboardEventInit={})=>act(async()=>{document.body.dispatchEvent(new KeyboardEvent('keydown',{key:name,bubbles:true,cancelable:true,...extra}));});
const media=()=>container.querySelector('video')!;
beforeEach(async()=>{
 localStorage.clear();store.state.config.ui.arrow_key_behavior='playback';selected.mockClear();
 vi.stubGlobal('matchMedia',()=>({matches:true}));container=document.createElement('div');document.body.append(container);root=createRoot(container);
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.unstubAllGlobals();});
async function mount(){await act(async()=>root.render(<Viewer clip={clip} clips={[clip,{...clip,slug:'two'}]} highlights={[]}
 onHighlightsChange={vi.fn()} onSelect={selected} onClose={vi.fn()} onTrim={vi.fn()} trimOpen={false} onShare={vi.fn()}
 onShareMenu={vi.fn()} shareLabel="share" onReveal={vi.fn()} onDelete={vi.fn()} onOpenExternally={vi.fn()} onRename={vi.fn()} notify={vi.fn()}/>));
 Object.defineProperty(media(),'duration',{value:20,configurable:true});
 await act(async()=>media().dispatchEvent(new Event('loadedmetadata')));media().currentTime=10;
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
