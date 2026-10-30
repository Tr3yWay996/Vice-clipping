import {AssignGameModal} from '../AssignGameModal';
import {useState} from 'react';
import {api} from '../../lib/api';
import {t, currentLocale} from '../../lib/i18n';
import {formatNumber} from '../../lib/format';
import type {DetectedGame, GameRules} from '../../lib/types';
import {useStore} from '../../state/store';
import {Modal} from '../Modal';
import {Row, Select, TextArea, TextField, Toggle} from './Fields';

const RULES = ['executables','paths','classes','steam_ids','titles'] as const;
type Draft = {id:string; name:string; rules:Record<keyof GameRules,string>; artwork:string|null; resetName:boolean};
const draftFor = (game?:DetectedGame):Draft => ({id:game?.id ?? 'new', name:game?.name ?? '',
  rules:Object.fromEntries(RULES.map(field=>[field,game?.rules[field].join('\n') ?? ''])) as Draft['rules'],
  artwork:game?.artwork_override ?? null, resetName:false});

export function DetectedGamesSettings() {
  const {state, saveConfig, refreshGames} = useStore();
  const [assigning,setAssigning]=useState<string|null>(null);
  const [search,setSearch]=useState('');
  const [filter,setFilter]=useState('all');
  const [draft,setDraft]=useState<Draft|null>(null);
  const [editing,setEditing]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [query,setQuery]=useState('');
  const [matches,setMatches]=useState<Array<{name:string;application_id:string}>>([]);
  const [target,setTarget]=useState('');
  const [confirmation,setConfirmation]=useState<{id:string;action:string;target?:string}|null>(null);
  const games=state.games;
  const current=games.find(game=>game.id===draft?.id);
  const online=Boolean(state.config?.ui?.game_online_lookup);
  const selectedAsset=draft?.artwork ?? current?.automatic_artwork;
  const run = async (action:()=>Promise<unknown>, after?:()=>void) => {
    setBusy(true);setError('');
    try {await action();await refreshGames();after?.();}
    catch(error){setError((error as Error).message);}
    finally {setBusy(false);}
  };
  const open=(game?:DetectedGame)=>{setEditing(true);setDraft(draftFor(game));setError('');setQuery(game?.name ?? '');setMatches([]);setTarget('');};
  const save=()=>{
    if(!draft)return;
    const fields={name:draft.name, reset_name:draft.resetName, artwork_override:draft.artwork, confirm:current && ['pending','deferred'].includes(current.status),
      rules:Object.fromEntries(RULES.map(field=>[field,draft.rules[field].split('\n').map(v=>v.trim()).filter(Boolean)]))};
    void run(()=>draft.id==='new'?api.createGame(fields):api.editGame(draft.id,fields),()=>setEditing(false));
  };
  const action=(id:string, action:string, destination?:string)=>void run(()=>api.gameAction(id,action,destination),()=>{
    if(['merge','remove'].includes(action))setEditing(false);
    setConfirmation(null);
  });
  const found=games.filter(game=>(!search || `${game.name} ${game.steam_app_id ?? ''} ${Object.values(game.rules).flat().join(' ')}`.toLocaleLowerCase().includes(search.toLocaleLowerCase())) &&
    (filter==='all' || filter==='pending' && ['pending','deferred'].includes(game.status) || filter==='manual' && (game.user_rules || ['manual','custom'].includes(game.source)) ||
      filter==='recognized' && ['recognized','confirmed'].includes(game.status) || filter==='rejected' && game.status==='rejected'));
  const [limit,setLimit]=useState(30);
  return <div className="detected-games">
    <Row label={t('games.suggestions')} help={t('games.suggestionsHelp')}>
      <Toggle label={t('games.suggestions')} checked={state.config?.ui?.game_suggestions !== false}
        onChange={value=>void run(()=>saveConfig({ui:{game_suggestions:value}}))}/>
    </Row>
    <Row label={t('games.online')} help={t('games.onlineHelp')}>
      <Toggle label={t('games.online')} checked={online}
        onChange={value=>void run(()=>saveConfig({ui:{game_online_lookup:value}}))}/>
    </Row>
    <div className="game-library-tools">
      <TextField label={t('games.search')} placeholder={t('games.search')} value={search} onChange={value=>{setSearch(value);setLimit(30);}}/>
      <Select label={t('games.filterLabel')} value={filter} onChange={value=>{setFilter(value);setLimit(30);}}
        options={['all','recognized','manual','pending','rejected'].map(value=>[value,t(`games.filter.${value}`)] as [string,string])}/>
      <button type="button" className="btn btn-sm" onClick={()=>open()}>{t('games.add')}</button>
    </div>
    {!state.gamesLoaded ? <p>{t('games.loading')}</p> : !found.length ? <p>{t('games.empty')}</p> : null}
    <div className="game-library-list">
      {found.slice(0,limit).map(game=><article key={game.id} className="game-library-row" data-status={game.status}>
        <button type="button" className="game-library-open" onClick={()=>open(game)}>
          {game.artwork_url?<img src={game.artwork_url} alt=""/>:<span className="game-art-placeholder" aria-hidden="true">🎮</span>}
          <span><b>{game.name}</b><small>{t(`games.source.${game.source}`)} · {t(`games.status.${game.status}`)}</small>
            <small>{t('games.clipCount',{count:game.clip_count,formatted:formatNumber(game.clip_count)})}{game.steam_app_id?` · ${t('games.steamId',{id:game.steam_app_id})}`:''}</small>
            <small>{t('games.lastDetected',{date:game.last_detected?new Date(game.last_detected).toLocaleString(currentLocale()):t('games.never')})}</small>
            <small>{game.rules.executables.join(', ') || game.rules.classes.join(', ') || game.rules.paths.join(', ')}</small></span>
        </button>
        {game.status==='pending' || game.status==='deferred'?<div className="game-row-actions">
          <button type="button" className="btn btn-sm" disabled={busy} onClick={()=>action(game.id,'confirm')}>{t('games.confirmGame')}</button>
          <button type="button" className="btn btn-quiet btn-sm" onClick={()=>open(game)}>{t('games.correct')}</button>
          <button type="button" className="btn btn-quiet btn-sm" disabled={busy} onClick={()=>action(game.id,'reject')}>{t('games.notGame')}</button>
          <button type="button" className="btn btn-quiet btn-sm" disabled={busy} onClick={()=>action(game.id,'later')}>{t('games.later')}</button>
        </div>:null}
      </article>)}
    </div>
    {found.length>limit?<button type="button" className="btn btn-quiet btn-sm" onClick={()=>setLimit(v=>v+30)}>{t('games.more',{count:found.length-limit,formatted:formatNumber(found.length-limit)})}</button>:null}
    {!editing && error?<p role="status" className="game-error">{error}</p>:null}
    <Modal open={editing} title={draft?.id!=='new'?t('games.edit',{name:draft?.name ?? ''}):t('games.add')} onClose={()=>!busy&&setEditing(false)}
      footer={<><button type="button" className="btn btn-quiet" disabled={busy} onClick={()=>setEditing(false)}>{t('common.cancel')}</button>
        <button type="button" className="btn" disabled={busy || !draft?.name.trim()} onClick={save}>{t('games.save')}</button></>}>
      {draft?<div className="game-editor"><fieldset disabled={busy || !editing}>
        <label className="game-field"><span>{t('games.name')}</span><TextField label={t('games.name')} value={draft.name} onChange={name=>setDraft({...draft,name,resetName:false})}/></label>
        {current?<button type="button" className="btn btn-quiet btn-sm" onClick={()=>setDraft({...draft,name:current.automatic_name,resetName:true})}>{t('games.resetName')}</button>:null}
        <div className="game-art-preview">
          {selectedAsset?<img src={`/api/game-artwork/${selectedAsset}`} alt={t('games.artPreview')}/>:<span className="game-art-placeholder" aria-hidden="true">🎮</span>}
          <div><label>{t('games.importArtwork')}<input type="file" accept="image/png,image/jpeg,image/webp" aria-label={t('games.importArtwork')}
            onChange={event=>{const file=event.target.files?.[0];if(file)void run(async()=>{const result=await api.uploadGameArtwork(draft.id,file);setDraft({...draft,artwork:result.asset});});}}/></label>
            <p>{t('games.artHelp')}</p><button type="button" className="btn btn-quiet btn-sm" onClick={()=>setDraft({...draft,artwork:null})}>{t('games.resetArtwork')}</button></div>
        </div>
        <details><summary>{t('games.searchArtwork')}</summary>
          <p>{t('games.artSearchHelp')}</p>
          <label className="game-field"><span>{t('games.artQuery')}</span><TextField label={t('games.artQuery')} value={query} onChange={setQuery}/></label>
          <button type="button" className="btn btn-quiet btn-sm" disabled={!online || query.trim().length<3}
            onClick={()=>void run(async()=>setMatches((await api.searchGameArtwork(draft.id,query)).matches))}>{t('games.searchArtwork')}</button>
          {matches.map(match=><button type="button" className="btn btn-quiet btn-sm" key={match.application_id}
            onClick={()=>void run(async()=>{const result=await api.previewGameArtwork(draft.id,match.application_id);setDraft({...draft,artwork:result.asset});})}>
            {match.name} · {match.application_id} · {t('games.preview')}</button>)}
        </details>
        <h3>{t('games.rulesTitle')}</h3><p>{t('games.rulesHelp')}</p>
        {RULES.map(field=><label className="game-field" key={field}><span>{t(`games.rules.${field}`)}</span><TextArea label={t(`games.rules.${field}`)} value={draft.rules[field]}
          onChange={value=>setDraft({...draft,rules:{...draft.rules,[field]:value}})} rows={field==='titles'?2:3}/></label>)}
        {current?<><p>{t('games.currentStatus',{status:t(`games.status.${current.status}`)})}</p>
          <div className="game-row-actions">
            {['pending','deferred'].includes(current.status)?<button type="button" className="btn btn-sm" onClick={()=>action(current.id,'confirm')}>{t('games.confirmGame')}</button>:null}
            {current.status==='rejected'?<button type="button" className="btn btn-sm" onClick={()=>action(current.id,'enable')}>{t('games.enable')}</button>:
              <button type="button" className="btn btn-quiet btn-sm" onClick={()=>action(current.id,'reject')}>{t('games.notGame')}</button>}
            {['recognized','confirmed'].includes(current.status)?<button type="button" className="btn btn-sm" onClick={()=>setAssigning(current.id)}>{t('assign.open')}</button>:null}
            <button type="button" className="btn btn-quiet btn-sm" onClick={()=>setConfirmation({id:current.id,action:'reclassify'})}>{t('games.reclassify')}</button>
            <button type="button" className="btn btn-quiet btn-danger btn-sm" onClick={()=>setConfirmation({id:current.id,action:'remove'})}>{t('games.remove')}</button>
          </div>
          <label className="game-field"><span>{t('games.otherGame')}</span><Select label={t('games.otherGame')} value={target} onChange={setTarget}
            options={[["",t('games.chooseGame')],...games.filter(g=>g.id!==current.id&&['confirmed','recognized'].includes(g.status)).map(g=>[g.id,g.name] as [string,string])]}/></label>
          <button type="button" className="btn btn-quiet btn-sm" disabled={!target} onClick={()=>setConfirmation({id:current.id,action:'merge',target})}>{t('games.merge')}</button>
        </>:null}
      </fieldset>{error?<p role="status" className="game-error">{error}</p>:null}</div>:null}
    </Modal>
    {assigning?<AssignGameModal key={assigning} gameId={assigning} onClose={()=>setAssigning(null)}/>:null}
    <Modal open={confirmation!==null} title={t('games.confirmAction')} onClose={()=>!busy&&setConfirmation(null)}
      footer={<><button type="button" className="btn btn-quiet" disabled={busy} onClick={()=>setConfirmation(null)}>{t('common.cancel')}</button>
        <button type="button" className="btn" disabled={busy} onClick={()=>confirmation&&action(confirmation.id,confirmation.action,confirmation.target)}>{t('games.continue')}</button></>}>
      <p>{t(`games.confirm.${confirmation?.action ?? 'remove'}`)}</p>
      {confirmation?.action==='reclassify' && current?<p>{t('games.clipCount',{count:current.clip_count,formatted:formatNumber(current.clip_count)})}</p>:null}
      <p>{t('games.filesUntouched')}</p>
      {error?<p role="status" className="game-error">{error}</p>:null}
    </Modal>
  </div>;
}
