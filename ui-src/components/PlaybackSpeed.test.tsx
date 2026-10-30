import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {usePlaybackSpeed,mediaBoost} from './PlaybackSpeed';
import {usePlaybackShortcuts} from '../lib/playbackShortcuts';
import {useRef} from 'react';
const store=vi.hoisted(()=>({state:{config:{ui:{playback_boost:2}}},saveConfig:vi.fn().mockResolvedValue({ok:true}),notify:vi.fn()}));
vi.mock('../state/store',()=>({useStore:()=>store}));
let root:Root,container:HTMLElement;
function Player(){const speed=usePlaybackSpeed();const el=useRef<HTMLDivElement>(null),video=useRef<HTMLVideoElement>(null);
 usePlaybackShortcuts(true,el,10,()=>false,()=>mediaBoost(video,speed.actions));return <div ref={el}><video ref={video} src="/sample.mp4"/>{speed.control}</div>;}
beforeEach(async()=>{vi.clearAllMocks();store.state.config.ui.playback_boost=2;container=document.createElement('div');document.body.append(container);root=createRoot(container);await act(async()=>root.render(<Player/>));});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.useRealTimers();});
it('persists one wheel adjustment per release and loads the saved multiplier on reopening',async()=>{
 vi.useFakeTimers();await act(async()=>document.body.dispatchEvent(new KeyboardEvent('keydown',{key:' ',bubbles:true,cancelable:true})));
 await act(async()=>vi.advanceTimersByTime(260));
 for(let i=0;i<2;i++)await act(async()=>document.body.dispatchEvent(new WheelEvent('wheel',{deltaY:-100,bubbles:true,cancelable:true})));
 expect(container.querySelector('video')!.playbackRate).toBe(2.5);expect(store.saveConfig).not.toHaveBeenCalled();
 await act(async()=>document.body.dispatchEvent(new KeyboardEvent('keyup',{key:' ',bubbles:true,cancelable:true})));
 expect(store.saveConfig).toHaveBeenCalledExactlyOnceWith({ui:{playback_boost:2.5}});expect(container.querySelector('video')!.playbackRate).toBe(1);
 store.state.config.ui.playback_boost=2.5;await act(async()=>root.render(<Player key="reopened"/>));expect(container.querySelector('select')!.value).toBe('2.5');
});
it('offers keyboard-accessible multiplier configuration and a 2× reset',async()=>{
 const select=container.querySelector('select')!;expect(select.getAttribute('aria-label')).toBe('Hold speed');expect(select.options).toHaveLength(16);
 await act(async()=>{select.value='3';select.dispatchEvent(new Event('change',{bubbles:true}));});expect(store.saveConfig).toHaveBeenLastCalledWith({ui:{playback_boost:3}});expect(select.value).toBe('3');
 await act(async()=>{select.value='2';select.dispatchEvent(new Event('change',{bubbles:true}));});expect(store.saveConfig).toHaveBeenLastCalledWith({ui:{playback_boost:2}});
});
