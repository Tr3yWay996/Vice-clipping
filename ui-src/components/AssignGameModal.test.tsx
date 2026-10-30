import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {AssignGameModal} from './AssignGameModal';
import {api} from '../lib/api';
import {setLocale} from '../lib/i18n';
const store=vi.hoisted(()=>({state:{games:[{id:'rocket',name:'Rocket League'}],clips:[{slug:'old',name:'Old clip.mp4',game:null},{slug:'different',name:'Different game.mp4',game:'Other game'}],images:[{slug:'shot',name:'Screenshot.png',game:null}]},
 refreshClips:vi.fn().mockResolvedValue(undefined),refreshImages:vi.fn().mockResolvedValue(undefined),refreshGames:vi.fn().mockResolvedValue(undefined),refreshPlaylists:vi.fn().mockResolvedValue(undefined)}));
vi.mock('../state/store',()=>({useStore:()=>store}));
vi.mock('../lib/api',()=>({api:{assignGame:vi.fn().mockResolvedValue({ok:true})}}));
let root:Root,container:HTMLElement;const close=vi.fn();
beforeEach(async()=>{vi.clearAllMocks();setLocale('en');container=document.createElement('div');document.body.append(container);root=createRoot(container);await act(async()=>root.render(<AssignGameModal gameId="rocket" onClose={close}/>));});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();setLocale('en');});
const click=async(el:HTMLElement)=>act(async()=>el.click());
const button=(text:string)=>[...container.querySelectorAll('button')].find(button=>button.textContent===text)!;
it('requires explicit selection and a named review before assigning clips and images',async()=>{
 expect(container.textContent).not.toContain('Different game');expect(button('Review 0 selected').disabled).toBe(true);
 const options=container.querySelectorAll<HTMLInputElement>('.game-assign-list input');expect(options).toHaveLength(2);
 await click(options[0]);await click(options[1]);expect(api.assignGame).not.toHaveBeenCalled();
 await click(button('Review 2 selected'));expect(container.textContent).toContain('Assign these 2 recordings to Rocket League?');
 expect(container.textContent).toContain('Old clip');expect(container.textContent).toContain('Screenshot.png');expect(api.assignGame).not.toHaveBeenCalled();
 await click(button('Assign 2 recordings'));expect(api.assignGame).toHaveBeenCalledExactlyOnceWith('rocket',['old','img:shot']);
 expect(store.refreshClips).toHaveBeenCalledOnce();expect(store.refreshImages).toHaveBeenCalledOnce();expect(close).toHaveBeenCalledOnce();
});
it('lets the user return to the selection and keeps failed assignments reviewable',async()=>{
 await click(container.querySelector<HTMLInputElement>('.game-assign-list input')!);await click(button('Review 1 selected'));await click(button('Back'));
 expect(container.querySelector<HTMLInputElement>('.game-assign-list input')!.checked).toBe(true);
 await click(button('Review 1 selected'));vi.mocked(api.assignGame).mockRejectedValueOnce(new Error('Offline'));
 await click(button('Assign 1 recording'));expect(container.querySelector('[role=alert]')!.textContent).toBe('Offline');expect(close).not.toHaveBeenCalled();
});
it('localizes the selection and review into French',async()=>{
 setLocale('fr');await act(async()=>root.render(<AssignGameModal gameId="rocket" onClose={close}/>));
 expect(container.textContent).toContain('Associer à Rocket League');expect(container.textContent).toContain('Sans étiquette uniquement');
});
