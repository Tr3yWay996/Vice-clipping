import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {DetectedGamesSettings} from './DetectedGames';
import {api} from '../../lib/api';
import type {DetectedGame} from '../../lib/types';
import {setLocale} from '../../lib/i18n';
const fixture=vi.hoisted(()=>({state:{games:[] as DetectedGame[],gamesLoaded:true,config:{ui:{game_suggestions:true,game_online_lookup:false}}},saveConfig:vi.fn().mockResolvedValue({}),refreshGames:vi.fn().mockResolvedValue(undefined)}));
vi.mock('../../state/store',()=>({useStore:()=>fixture}));
vi.mock('../../lib/api',()=>({api:{editGame:vi.fn().mockResolvedValue({ok:true}),createGame:vi.fn().mockResolvedValue({id:'new'}),gameAction:vi.fn().mockResolvedValue({ok:true}),uploadGameArtwork:vi.fn().mockResolvedValue({asset:'a'.repeat(64)+'.png',url:'/art'}),searchGameArtwork:vi.fn().mockResolvedValue({matches:[]}),previewGameArtwork:vi.fn()}}));
const game=(id:string,status:DetectedGame['status']='recognized'):DetectedGame=>({id,name:id==='one'?'Killing Floor 2':'Unknown Game',automatic_name:'KFGame',source:id==='one'?'steam':'process',status,user_rules:false,
 rules:{executables:[id+'.exe'],paths:[],classes:[],steam_ids:[],titles:[]},steam_app_id:null,artwork_override:null,automatic_artwork:null,artwork_url:null,last_detected:null,clip_count:3});
let root:Root,container:HTMLElement;
const click=async(button:HTMLElement)=>act(async()=>button.click());
const button=(text:string)=>[...container.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===text)!;
const input=(label:string)=>container.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
const set=async(el:HTMLInputElement|HTMLSelectElement,value:string)=>act(async()=>{
 Object.getOwnPropertyDescriptor(el.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value')!.set!.call(el,value);
 el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));
});
beforeEach(async()=>{
 vi.clearAllMocks();fixture.state.games=[game('one'),game('two','pending')];setLocale('en');
 container=document.createElement('div');document.body.append(container);root=createRoot(container);
 await act(async()=>root.render(<DetectedGamesSettings/>));
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();setLocale('en');});
describe('Detected Games Settings',()=>{
 it('keeps suggestions passive and supports search, filters and remembered decisions',async()=>{
  expect(container.querySelector('[role=dialog]')).toBeNull();expect(container.querySelectorAll('.game-library-row')).toHaveLength(2);
  await set(input('Search games or identifiers'),'Killing');expect(container.querySelectorAll('.game-library-row')).toHaveLength(1);
  await set(input('Search games or identifiers'),'');
  await set(container.querySelector('select[aria-label="Show"]')!,'pending');expect(container.querySelectorAll('.game-library-row')).toHaveLength(1);
  await click(button('Ask later'));expect(api.gameAction).toHaveBeenCalledWith('two','later',undefined);expect(fixture.refreshGames).toHaveBeenCalled();
  await click(button('Not a game'));expect(api.gameAction).toHaveBeenCalledWith('two','reject',undefined);
 });
 it('saves a corrected pending name and confirms it in one operation',async()=>{
  await click(container.querySelectorAll<HTMLButtonElement>('.game-library-open')[1]);
  await set(input('Display name'),'My Corrected Game');await click(button('Save game'));
  expect(api.editGame).toHaveBeenCalledWith('two',expect.objectContaining({name:'My Corrected Game',confirm:true}));
  expect(container.querySelector('[role=dialog]')?.getAttribute('data-closing')).toBe('true');
 });
 it('previews custom artwork and automatic reset before saving',async()=>{
  await click(container.querySelector<HTMLButtonElement>('.game-library-open')!);
  const file=new File(['png'],'Été.png',{type:'image/png'});
  const picker=input('Import local artwork');Object.defineProperty(picker,'files',{value:[file],configurable:true});
  await act(async()=>picker.dispatchEvent(new Event('change',{bubbles:true})));
  expect(api.uploadGameArtwork).toHaveBeenCalledWith('one',file);
  expect(container.querySelector<HTMLImageElement>('.game-art-preview img')!.src).toContain('a'.repeat(64));
  expect(api.editGame).not.toHaveBeenCalled();
  await click(button('Restore automatic artwork'));await click(button('Restore automatic name'));await click(button('Save game'));
  expect(api.editGame).toHaveBeenCalledWith('one',expect.objectContaining({reset_name:true,artwork_override:null}));
 });
 it('requires confirmation before removing or merging identities',async()=>{
  await click(container.querySelector<HTMLButtonElement>('.game-library-open')!);await click(button('Remove learned game'));
  expect(api.gameAction).not.toHaveBeenCalled();expect(container.querySelectorAll('[role=dialog]')).toHaveLength(2);
  await click(button('Continue'));expect(api.gameAction).toHaveBeenCalledWith('one','remove',undefined);
 });
 it('uses natural French controls and never starts online search while disabled',async()=>{
  setLocale('fr');await act(async()=>root.render(<DetectedGamesSettings/>));
  await click(container.querySelector<HTMLButtonElement>('.game-library-open')!);
  expect(input('Nom affiché')).not.toBeNull();expect(button('Enregistrer le jeu')).not.toBeUndefined();
  expect(button('Trouver une autre illustration').disabled).toBe(true);expect(api.searchGameArtwork).not.toHaveBeenCalled();
 });
});
