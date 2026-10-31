import type {KeyboardEvent,MouseEvent} from 'react';
import {useStore} from '../state/store';
import {libraryKey,type LibraryMedia} from './types';
import {ownsKeyboardInput} from './playbackShortcuts';
export interface CardSelection {active:boolean;selected:boolean;onSelect:(event:MouseEvent)=>void}

export function useGallerySelection(media:LibraryMedia[],rename:(media:LibraryMedia)=>void) {
  const {state,dispatch}=useStore();const ids=media.map(libraryKey);const selected=new Set(state.selectedMedia);
  return {
    active:state.selectionMode,
    toggle:()=>dispatch({type:'selectionMode',active:!state.selectionMode}),
    all:()=>dispatch({type:'selectAllMedia',ids}),
    none:()=>dispatch({type:'unselectMedia',ids}),
    selection:(entry:LibraryMedia):CardSelection=>({active:state.selectionMode,selected:selected.has(libraryKey(entry)),onSelect:event=>{
      dispatch({type:'selectMedia',id:libraryKey(entry),visible:ids,range:event.shiftKey,toggle:!event.shiftKey});
    }}),
    onKeyDown:(event:KeyboardEvent)=>{
      if(ownsKeyboardInput(event.nativeEvent)||document.querySelector('[aria-modal=true]'))return;
      if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='a'){
        event.preventDefault();event.stopPropagation();dispatch({type:'selectAllMedia',ids});
      }else if(event.key==='Escape'&&state.selectionMode){event.preventDefault();event.stopPropagation();dispatch({type:'clearSelection'});}
      else if(event.key==='F2'&&state.selectedMedia.length===1){
        const entry=media.find(entry=>selected.has(libraryKey(entry)));
        if(entry){event.preventDefault();event.stopPropagation();rename(entry);}
      }
    },
  };
}
