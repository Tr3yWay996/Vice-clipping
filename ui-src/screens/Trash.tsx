import {useEffect, useState} from 'react';
import {api} from '../lib/api';
import {currentLocale, t} from '../lib/i18n';
import {formatBytes, formatNumber} from '../lib/format';
import {useStore} from '../state/store';
import {Modal} from '../components/Modal';
import {OverlayPortal} from '../components/OverlayPortal';
import {IconTrash} from '../components/Icons';

export function Trash() {
  const {state, refreshTrash, refreshClips, refreshImages, refreshPlaylists, refreshGames} = useStore();
  const [selected,setSelected]=useState<Set<string>>(new Set());
  const [confirm,setConfirm]=useState<{ids:string[];all:boolean}|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [failures,setFailures]=useState<Record<string,string>>({});
  const [limit,setLimit]=useState(30);
  const snapshot=state.trash;
  const items=snapshot?.items ?? [];
  useEffect(()=>{void refreshTrash();},[refreshTrash]);
  useEffect(()=>{setSelected(previous=>new Set([...previous].filter(id=>items.some(item=>item.id===id))));},[snapshot]);
  const run=async(action:'restore'|'purge',ids:string[],all=false,destination?:'library')=>{
    setBusy(true);setError('');setFailures({});
    try {
      const result=await api.trashAction(action,ids,all,destination);
      setFailures(Object.fromEntries(result.results.filter(result=>!result.ok).map(result=>[result.id,t(`trash.errors.${result.code ?? 'storage'}`)])));
      setConfirm(null);
      await refreshTrash();
      // Reconcile library metadata too when a socket event was missed.
      void Promise.all([refreshClips(),refreshImages(),refreshPlaylists(),refreshGames()]);
    } catch(error) {setError((error as Error).message);}
    finally {setBusy(false);}
  };
  const date=(value:string)=>new Date(value).toLocaleString(currentLocale());
  const toggle=(id:string)=>setSelected(previous=>{const next=new Set(previous);next.has(id)?next.delete(id):next.add(id);return next;});
  return <section className="trash-screen">
    <header className="trash-heading"><div><h1>{t('trash.title')}</h1><p>{t('trash.description')}</p></div>
      <button type="button" className="btn btn-quiet btn-sm" disabled={busy} onClick={()=>void refreshTrash()}>{t('trash.refresh')}</button></header>
    <p>{t('trash.storage',{size:formatBytes(snapshot?.total_bytes ?? 0)})} · {t('trash.count',{count:items.length,formatted:formatNumber(items.length)})}</p>
    <div className="trash-tools">
      <label><input type="checkbox" aria-label={t('trash.selectAll')} checked={items.length>0 && selected.size===items.length} disabled={busy || !items.length}
        onChange={event=>setSelected(new Set(event.target.checked?items.map(item=>item.id):[]))}/>{t('trash.selectAll')}</label>
      <button type="button" className="btn btn-sm" disabled={busy || !items.length} onClick={()=>void run('restore',[],true)}>{t('trash.restoreAll')}</button>
      <button type="button" className="btn btn-quiet btn-danger btn-sm" disabled={busy || !items.length} onClick={()=>setConfirm({ids:[],all:true})}>{t('trash.empty')}</button>
      {selected.size ? <><span>{t('trash.selected',{count:selected.size})}</span>
        <button type="button" className="btn btn-sm" disabled={busy} onClick={()=>void run('restore',[...selected])}>{t('trash.restoreSelected')}</button>
        <button type="button" className="btn btn-quiet btn-danger btn-sm" disabled={busy} onClick={()=>setConfirm({ids:[...selected],all:false})}>{t('trash.deleteSelected')}</button></>:null}
    </div>
    <div aria-live="polite">
      {busy?<p>{t('trash.working')}</p>:null}
      {error?<p role="alert" className="trash-error">{error}</p>:null}
      {state.trashUnavailable || snapshot?.error ? <p role="alert" className="trash-error">{t(`trash.errors.${snapshot?.error ?? 'connection'}`)}</p> :
        !snapshot?<p>{t('trash.loading')}</p>:!items.length?<p>{t('trash.emptyState')}</p>:null}
    </div>
    <div className="trash-grid">
      {items.slice(0,limit).map(item=><article key={item.id} className="clip-card trash-card" data-id={item.id}>
        <div className="clip-thumb trash-thumb">
          <span className="clip-thumb-empty" aria-hidden="true"><IconTrash size={28}/></span>
          {item.thumbnail_url?<img src={item.thumbnail_url} loading="lazy" alt="" onError={event=>event.currentTarget.hidden=true}/>:null}
          <label className="trash-select"><input type="checkbox" aria-label={t('trash.selectItem',{name:item.display_title??item.name})} checked={selected.has(item.id)} disabled={busy} onChange={()=>toggle(item.id)}/></label>
        </div>
        <div className="clip-body">
          <h2 className="clip-name" title={item.name}>{item.display_title??item.name}</h2>
          <span className="clip-game">{item.game || t('common.untagged')}</span>
          <p className="clip-meta">{t(`trash.kind.${item.kind}`)} · {formatBytes(item.size)}</p>
          <p className="clip-meta">{t('trash.recorded',{date:date(item.created_at)})}</p>
          <p className="clip-meta">{t('trash.deleted',{date:date(item.deleted_at)})}</p>
          <p className="clip-meta">{item.remaining_seconds===null?t('trash.keptForever'):item.remaining_seconds===0?t('trash.eligible'):t('trash.remaining',{count:Math.ceil(item.remaining_seconds/86400)})}</p>
          <p className="clip-meta trash-location" title={item.original_dir}>{t('trash.originalFolder',{path:item.original_dir})}</p>
          {!item.available?<p className="trash-error">{t('trash.unavailable')}</p>:null}
          {failures[item.id]?<p role="alert" className="trash-error">{failures[item.id]}</p>:null}
          <div className="trash-tools">
            <button type="button" className="btn btn-sm" disabled={busy || ['deleting','restored'].includes(item.state)} onClick={()=>void run('restore',[item.id])}>{t('trash.restore')}</button>
            <button type="button" className="btn btn-quiet btn-danger btn-sm" disabled={busy} onClick={()=>setConfirm({ids:[item.id],all:false})}>{t('trash.deletePermanently')}</button>
          </div>
          <details><summary>{t('trash.otherLocation')}</summary><p className="clip-meta">{t('trash.alternativeHelp')}</p>
            <button type="button" className="btn btn-quiet btn-sm" disabled={busy} onClick={()=>void run('restore',[item.id],false,'library')}>{t('trash.restoreToLibrary')}</button>
          </details>
        </div>
      </article>)}
    </div>
    {items.length>limit?<button type="button" className="btn btn-quiet" onClick={()=>setLimit(value=>value+30)}>{t('trash.more')}</button>:null}
    <OverlayPortal><Modal open={confirm!==null} title={confirm?.all?t('trash.empty'):t('trash.deletePermanently')} onClose={()=>!busy&&setConfirm(null)}
      footer={<><button type="button" className="btn btn-quiet" disabled={busy} onClick={()=>setConfirm(null)}>{t('common.cancel')}</button>
        <button type="button" className="btn btn-danger-solid" disabled={busy} onClick={()=>confirm&&void run('purge',confirm.ids,confirm.all)}>{t('trash.deletePermanently')}</button></>}>
      <p>{t('trash.confirmPermanent',{count:confirm?.all?items.length:confirm?.ids.length ?? 0})}</p>
      {error?<p role="alert" className="trash-error">{error}</p>:null}
    </Modal></OverlayPortal>
  </section>;
}
