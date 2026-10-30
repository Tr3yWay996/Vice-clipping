import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {Trash} from './Trash';
import {OverlayRoot} from '../components/OverlayPortal';
import {api} from '../lib/api';
import {setLocale} from '../lib/i18n';
import type {TrashSnapshot} from '../lib/types';
const fixture=vi.hoisted(()=>({state:{trash:null as TrashSnapshot|null,trashUnavailable:false},refreshTrash:vi.fn().mockResolvedValue(undefined),refreshClips:vi.fn(),refreshImages:vi.fn(),refreshPlaylists:vi.fn(),refreshGames:vi.fn()}));
vi.mock('../state/store',()=>({useStore:()=>fixture}));
vi.mock('../lib/api',()=>({api:{trashAction:vi.fn()}}));
let container:HTMLElement,root:Root;
const click=async(element:HTMLElement)=>act(async()=>element.click());
const button=(text:string)=>[...container.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent===text)!;
beforeEach(async()=>{
 vi.clearAllMocks();setLocale('en');fixture.state.trashUnavailable=false;
 fixture.state.trash={items:[{id:'one',name:'Match #1.mp4',kind:'clip',size:1234,original_dir:'/recordings',game:'Game',created_at:'2020-01-01T00:00:00Z',deleted_at:'2026-10-30T00:00:00Z',remaining_seconds:86400,available:true,state:'trashed',thumbnail_url:null},{id:'two',name:'Shot.png',kind:'image',size:400,original_dir:'/pictures',game:null,created_at:'2020-01-02T00:00:00Z',deleted_at:'2026-10-30T00:00:00Z',remaining_seconds:null,available:false,state:'trashed',thumbnail_url:null}],total_bytes:1634,retention_days:30,error:null};
 vi.mocked(api.trashAction).mockResolvedValue({ok:true,results:[]});
 container=document.createElement('div');document.body.append(container);root=createRoot(container);
 await act(async()=>root.render(<OverlayRoot><Trash/></OverlayRoot>));
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();setLocale('en');});
describe('recoverable Trash',()=>{
 it('shows recording/deletion metadata, retention and unavailable storage',()=>{
  expect(container.querySelectorAll('.trash-card')).toHaveLength(2);expect(container.textContent).toContain('Match #1.mp4');
  expect(container.textContent).toContain('1 day remaining');expect(container.textContent).toContain('Kept until you delete it manually');
  expect(container.textContent).toContain('Recorded:');expect(container.textContent).toContain('Deleted:');expect(container.textContent).toContain('/recordings');
  expect(container.textContent).toContain('Reconnect the original drive');
 });
 it('restores selected items and all media through the shared API',async()=>{
  await click(container.querySelector('input[aria-label="Select Match #1.mp4"]')!);
  await click(button('Restore selected'));expect(api.trashAction).toHaveBeenCalledWith('restore',['one'],false,undefined);
  await click(button('Restore all'));expect(api.trashAction).toHaveBeenCalledWith('restore',[],true,undefined);
  expect(fixture.refreshTrash).toHaveBeenCalled();expect(fixture.refreshPlaylists).toHaveBeenCalled();
 });
 it('requires explicit confirmation for permanent deletion and Empty Trash',async()=>{
  await click(button('Delete permanently'));expect(api.trashAction).not.toHaveBeenCalled();
  const dialog=container.querySelector('[role=dialog]')!;expect(dialog.textContent).toContain('cannot be undone');
  await click(dialog.querySelector<HTMLButtonElement>('.btn-danger-solid')!);
  expect(api.trashAction).toHaveBeenCalledWith('purge',['one'],false,undefined);
 });
 it('confirms emptying everything and exposes safe alternative restoration',async()=>{
  await click(button('Empty Trash'));const dialog=container.querySelector('[role=dialog]')!;
  await click(dialog.querySelector<HTMLButtonElement>('.btn-danger-solid')!);expect(api.trashAction).toHaveBeenCalledWith('purge',[],true,undefined);
  await click(button('Restore to current library folder'));expect(api.trashAction).toHaveBeenCalledWith('restore',['one'],false,'library');
 });
 it('keeps failed items visible and displays per-item failures',async()=>{
  vi.mocked(api.trashAction).mockResolvedValue({ok:false,results:[{id:'one',ok:false,code:'destination'}]});
  await click(button('Restore'));expect(container.querySelector('[data-id=one]')?.textContent).toContain('The original folder is unavailable');
  expect(container.querySelectorAll('.trash-card')).toHaveLength(2);
 });
 it('uses the French Corbeille controls',async()=>{
  setLocale('fr');await act(async()=>root.render(<OverlayRoot><Trash/></OverlayRoot>));
  expect(button('Vider la corbeille')).toBeDefined();expect(button('Restaurer')).toBeDefined();expect(container.textContent).toContain('Corbeille');
 });
});
