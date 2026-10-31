import {useEffect,useRef,useState} from 'react';
import {useStore} from '../state/store';
import {api} from '../lib/api';
import {copyToClipboard} from '../lib/clipboard';
import {t} from '../lib/i18n';
import {clipTitle,imageTitle,libraryKey,type LibraryMedia,type RenamePlan,type LibraryResult} from '../lib/types';
import {Modal} from './Modal';
import {JobRow} from './ProcessingQueuePanel';

const errorText=(code?:string)=>t(code?.startsWith('trash.')||code?.startsWith('library.')?code:`library.errors.${code??'storage'}`);

export function LibraryToolbar() {
  const {state,dispatch,refreshClips,refreshImages,refreshPlaylists,refreshGames,refreshTrash}=useStore();
  const [action,setAction]=useState('');const [mode,setMode]=useState('replace');
  const [options,setOptions]=useState<Record<string,string>>({find:'',replace:'',text:'',prefix:'',suffix:'',start:'1',width:'3',pattern:'{title}'});
  const [plans,setPlans]=useState<RenamePlan[]>([]);const [previewing,setPreviewing]=useState(false);
  const [playlist,setPlaylist]=useState('');const [sourcePlaylist,setSourcePlaylist]=useState('');const [game,setGame]=useState('');
  const [busy,setBusy]=useState(false);const [progress,setProgress]=useState(0);const stop=useRef(false);
  const [results,setResults]=useState<LibraryResult[]>([]);const [error,setError]=useState('');const [manualCopy,setManualCopy]=useState('');
  const all:LibraryMedia[]=[...state.clips.map(item=>({kind:'clip' as const,item})),...state.images.map(item=>({kind:'image' as const,item}))];
  const selected=all.filter(media=>state.selectedMedia.includes(libraryKey(media)));
  const ids=selected.map(libraryKey);const idKey=JSON.stringify(ids);
  useEffect(()=>{
    if(action!=='rename' || !ids.length)return;
    let cancelled=false;setPreviewing(true);setError('');setPlans([]);
    const timer=setTimeout(()=>void api.renamePreview(ids,mode,options).then(result=>{if(!cancelled)setPlans(result.items);})
      .catch(error=>{if(!cancelled)setError((error as Error).message);}).finally(()=>{if(!cancelled)setPreviewing(false);}),150);
    return ()=>{cancelled=true;clearTimeout(timer);};
  },[action,idKey,mode,options]);
  const name=(id:string)=>{const media=all.find(media=>libraryKey(media)===id);return media?(media.kind==='clip'?clipTitle(media.item):imageTitle(media.item)):id;};
  const open=(next:string)=>{setAction(next);setResults([]);setError('');setProgress(0);stop.current=false;setManualCopy('');};
  const run=async()=>{
    setBusy(true);setResults([]);setError('');setProgress(0);stop.current=false;
    const snapshot=[...ids];const completed:LibraryResult[]=[];
    try {
      for(let at=0;at<snapshot.length && !stop.current;at+=20){
        const result=await api.libraryActions(action,snapshot.slice(at,at+20),{confirm:true,plans:action==='rename'?plans:undefined,
          game_id:game||null,playlist_id:playlist,source_playlist_id:sourcePlaylist});
        completed.push(...result.results);setResults([...completed]);setProgress(Math.min(snapshot.length,at+20));
      }
      const text=completed.filter(result=>result.ok&&result.value).map(result=>result.value).join('\n');
      if(text && !await copyToClipboard(text))setManualCopy(text);
      await Promise.all([refreshClips(),refreshImages(),refreshPlaylists(),refreshGames(),refreshTrash()]);
      dispatch({type:'unselectMedia',ids:completed.filter(result=>result.ok).map(result=>result.id)});
    }catch(error){setError((error as Error).message);}
    finally{setBusy(false);}
  };
  const job=state.jobs.find(job=>job.id===state.queueJobId);
  const validRename=plans.length===ids.length && !previewing && plans.every(plan=>!plan.code);
  const canApply=Boolean(ids.length)&&(!action.startsWith('playlist-') || Boolean(playlist)&&(action!=='playlist-move'||Boolean(sourcePlaylist))) && (action!=='rename'||validRename);
  const resultsById=new Map(results.map(result=>[result.id,result]));
  return <>
    {state.selectionMode && ['home','clips','images'].includes(state.view)?<div className="library-toolbar" role="region" aria-label={t('library.bulkActions')}>
      <b>{t('library.selected',{count:selected.length})}</b>
      {['rename','playlist-add','playlist-remove','playlist-move','game','trash','paths','share-links','reveal'].map(value=><button key={value} type="button" className="btn btn-quiet btn-sm"
        disabled={!selected.length || value==='rename'&&selected.length>1000} title={value==='rename'&&selected.length>1000?t('library.renameLimit'):undefined} onClick={()=>open(value)}>{t(`library.action.${value}`)}</button>)}
      <button type="button" className="btn btn-quiet btn-sm" onClick={()=>dispatch({type:'clearSelection'})}>{t('library.clear')}</button>
      <small>{t('library.scope')}</small>
    </div>:null}
    <Modal open={Boolean(action)} title={t(`library.action.${action||'rename'}`)} onClose={()=>{if(!busy)setAction('');}}
      footer={<><button type="button" className="btn btn-quiet" disabled={busy} onClick={()=>setAction('')}>{t('common.close')}</button>
        {busy?<button type="button" className="btn btn-quiet" onClick={()=>{stop.current=true;}}>{t('library.stopAfterBatch')}</button>:
          <button type="button" className={action==='trash'?'btn btn-danger-solid':'btn'} disabled={!canApply || results.length>0} onClick={()=>void run()}>{t('library.apply',{count:ids.length})}</button>}</>}>
      <p>{t(action==='trash'?'library.trashConfirm':action.startsWith('playlist-')?'library.playlistHelp':action==='game'?'library.gameHelp':'library.review',{count:ids.length})}</p>
      {action==='rename'?<fieldset disabled={busy||results.length>0} className="library-rename-fields">
        <label>{t('library.mode')}<select className="select" aria-label={t('library.mode')} value={mode} onChange={event=>setMode(event.target.value)}>
          {['replace','prefix','suffix','number','pattern'].map(mode=><option key={mode} value={mode}>{t(`library.renameMode.${mode}`)}</option>)}
        </select></label>
        {(mode==='replace'?['find','replace']:mode==='prefix'||mode==='suffix'?['text']:mode==='number'?['prefix','start','width','suffix']:['pattern','start']).map(field=><label key={field}>{t(`library.field.${field}`)}
          <input className="text-input" aria-label={t(`library.field.${field}`)} value={options[field]??''} type={['start','width'].includes(field)?'number':'text'}
            onChange={event=>setOptions({...options,[field]:event.target.value})}/></label>)}
        {mode==='pattern'?<p>{t('library.patternHelp')}</p>:null}
      </fieldset>:null}
      {action==='game'?<label>{t('games.chooseGame')}<select className="select" aria-label={t('games.chooseGame')} value={game} disabled={busy} onChange={event=>setGame(event.target.value)}>
        <option value="">{t('library.removeGame')}</option>{state.games.filter(game=>['recognized','confirmed'].includes(game.status)).map(game=><option key={game.id} value={game.id}>{game.name}</option>)}
      </select></label>:null}
      {action.startsWith('playlist-')?<div className="library-rename-fields">
        {action==='playlist-move'?<label>{t('library.sourcePlaylist')}<select className="select" value={sourcePlaylist} aria-label={t('library.sourcePlaylist')} disabled={busy} onChange={event=>setSourcePlaylist(event.target.value)}>
          <option value="">{t('library.choosePlaylist')}</option>{state.playlists.filter(playlist=>playlist.kind==='custom').map(playlist=><option key={playlist.id} value={playlist.id}>{playlist.name}</option>)}</select></label>:null}
        <label>{t('library.playlist')}<select className="select" aria-label={t('library.playlist')} value={playlist} disabled={busy} onChange={event=>setPlaylist(event.target.value)}>
          <option value="">{t('library.choosePlaylist')}</option>{state.playlists.map(playlist=><option key={playlist.id} value={playlist.id}>{playlist.name}</option>)}
        </select></label></div>:null}
      {previewing?<p role="status">{t('library.previewing')}</p>:null}
      {action==='rename'?<div className="library-preview"><table><thead><tr><th>{t('library.before')}</th><th>{t('library.after')}</th><th>{t('library.file')}</th></tr></thead><tbody>
        {plans.map(plan=><tr key={plan.id}><td>{plan.previous_title??name(plan.id)}</td><td>{plan.code?errorText(plan.code):plan.title}</td><td>{plan.filename}
          {plan.metadata_only?<small>{t('library.metadataOnly')}</small>:null}</td></tr>)}
      </tbody></table></div>:null}
      {action!=='rename'&&!results.length?<div className="library-preview">{selected.map(media=><p key={libraryKey(media)}>{name(libraryKey(media))}</p>)}</div>:null}
      {busy?<progress max={ids.length||1} value={progress} aria-label={t('library.progress')}/>:null}
      {results.length?<><p role="status">{t('library.results',{success:results.filter(result=>result.ok).length,failed:results.filter(result=>!result.ok).length,total:results.length})}</p>
        <ul>{[...resultsById.values()].filter(result=>!result.ok).map(result=><li key={result.id}>{name(result.id)} · {errorText(result.code)}</li>)}</ul></>:null}
      {manualCopy?<label>{t('library.manualCopy')}<textarea readOnly value={manualCopy}/></label>:null}
      {error?<p role="alert">{error}</p>:null}
    </Modal>
    <Modal open={Boolean(job)} title={t('library.processingDetails')} onClose={()=>dispatch({type:'showQueue'})}>
      {job?<JobRow job={job}/>:null}
    </Modal>
  </>;
}
