import {useStore} from '../state/store';
import {t} from '../lib/i18n';
import {useGallerySelection} from '../lib/gallerySelection';
import {type Clip,type Image,type LibraryMedia} from '../lib/types';
import {ClipCard,type ClipActions} from './ClipCard';
import {ImageCard,type ImageActionSet} from './ImageCard';
import {jobForMedia} from './MediaJobBadge';

/** One selection scope for grids, playlists, search results and home rows. */
export function MediaGallery({clips=[],images=[],clipActions={},imageActions={},layout='grid',label}: {
  clips?:Clip[];images?:Image[];clipActions?:ClipActions;imageActions?:ImageActionSet;layout?:'grid'|'row';label?:string;
}) {
  const {state,dispatch}=useStore();
  const media:LibraryMedia[]=[...clips.map(item=>({kind:'clip' as const,item})),...images.map(item=>({kind:'image' as const,item}))];
  const gallery=useGallerySelection(media,entry=>{if(entry.kind==='clip')clipActions.onBeginRename?.(entry.item);else imageActions.onBeginRename?.(entry.item);});
  const selection=gallery.selection;
  return <section className="media-gallery" aria-label={label ?? t('library.gallery')} tabIndex={0} onKeyDown={gallery.onKeyDown}>
    <div className="gallery-selection-controls">
      <button type="button" className="btn btn-quiet btn-sm" aria-pressed={state.selectionMode} onClick={gallery.toggle}>{t(state.selectionMode?'library.exitSelection':'library.select')}</button>
      {state.selectionMode?<><button type="button" className="btn btn-quiet btn-sm" onClick={gallery.all}>{t('library.selectVisible')}</button>
        <button type="button" className="btn btn-quiet btn-sm" onClick={gallery.none}>{t('library.deselectVisible')}</button></>:null}
    </div>
    {clips.length?<div className={layout==='row'?'clip-row':'clip-grid'}>{clips.map(clip=><ClipCard key={clip.library_id??clip.slug} clip={clip} draggable
      isNew={state.recentNew.includes(clip.slug)} actions={clipActions} selection={selection({kind:'clip',item:clip})}
      job={jobForMedia(state.jobs,clip.library_id)} onJob={()=>{const job=jobForMedia(state.jobs,clip.library_id);dispatch({type:'showQueue',jobId:job?.id});}}/>)}</div>:null}
    {images.length?<>{clips.length?<h2 className="clips-section">{t('clips.imagesHeading',{count:images.length})}</h2>:null}
      <div className={layout==='row'?'clip-row':'clip-grid'}>{images.map(image=><ImageCard key={image.library_id??image.slug} image={image} draggable actions={imageActions}
        selection={selection({kind:'image',item:image})} job={jobForMedia(state.jobs,image.library_id)}
        onJob={()=>{const job=jobForMedia(state.jobs,image.library_id);dispatch({type:'showQueue',jobId:job?.id});}}/>)}</div></>:null}
  </section>;
}
