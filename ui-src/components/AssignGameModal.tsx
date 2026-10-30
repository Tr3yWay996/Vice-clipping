import {useState} from 'react';
import {useStore} from '../state/store';
import {api} from '../lib/api';
import {t} from '../lib/i18n';
import {clipTitle} from '../lib/types';
import {Modal} from './Modal';

/** Explicit review; never guess a game from the pixels or all untagged files. */
export function AssignGameModal({gameId, onClose}: {gameId:string; onClose:() => void}) {
  const {state, refreshClips, refreshImages, refreshGames, refreshPlaylists} = useStore();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState('');
  const [untagged, setUntagged] = useState(true);
  const [review, setReview] = useState(false);
  const [limit, setLimit] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const game = state.games.find(game => game.id === gameId);
  const media = [...state.clips.map(clip => ({id:clip.slug, name:clipTitle(clip), game:clip.game})),
    ...state.images.map(image => ({id:`img:${image.slug}`, name:image.name, game:image.game}))];
  const shown = media.filter(item => review ? selected.has(item.id) :
    (!untagged || !item.game) && (!query || item.name.toLocaleLowerCase().includes(query.toLocaleLowerCase())));
  const submit = async () => {
    setBusy(true); setError('');
    try {
      await api.assignGame(gameId, [...selected]);
      await Promise.all([refreshClips(), refreshImages(), refreshGames(), refreshPlaylists()]);
      onClose();
    } catch (error) {setError((error as Error).message);}
    finally {setBusy(false);}
  };
  return <Modal open title={t('assign.title', {name:game?.name ?? ''})} onClose={() => !busy && onClose()}
    footer={<><button type="button" className="btn btn-quiet" disabled={busy} onClick={() => review ? setReview(false) : onClose()}>
      {t(review ? 'assign.back' : 'common.cancel')}</button>
      <button type="button" className="btn" disabled={busy || !selected.size || selected.size > 1000}
        onClick={() => review ? void submit() : (setReview(true), setLimit(30))}>
        {t(review ? 'assign.confirm' : 'assign.review', {count:selected.size})}</button></>}>
    <p>{t('assign.help')}</p>
    {!review ? <div className="game-assign-tools">
      <input type="search" aria-label={t('games.search')} placeholder={t('games.search')} value={query}
        onChange={event => {setQuery(event.target.value); setLimit(30);}}/>
      <label><input type="checkbox" checked={untagged} onChange={event => {setUntagged(event.target.checked); setLimit(30);}}/>{t('assign.untagged')}</label>
    </div> : <p>{t('assign.reviewHelp', {count:selected.size, name:game?.name ?? ''})}</p>}
    <div className="game-assign-list">
      {shown.slice(0,limit).map(item => <label key={item.id}>
        <input type="checkbox" disabled={busy || review} checked={selected.has(item.id)} onChange={event => setSelected(previous => {
          const next = new Set(previous); if (event.target.checked) next.add(item.id); else next.delete(item.id); return next;
        })}/><span>{item.name}<small>{item.game || t('common.untagged')}</small></span>
      </label>)}
    </div>
    {!shown.length ? <p>{t('assign.empty')}</p> : null}
    {shown.length > limit ? <button type="button" className="btn btn-quiet btn-sm" onClick={() => setLimit(limit + 30)}>{t('games.more', {count:shown.length-limit, formatted:shown.length-limit})}</button> : null}
    {error ? <p role="alert" className="game-error">{error}</p> : null}
  </Modal>;
}
