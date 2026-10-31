import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from 'react';

import {api} from '../lib/api';
import {connectWs} from '../lib/ws';
import {formatDuration, hotkeyLabel} from '../lib/format';
import {H264_SUPPORTED} from '../lib/env';
import {ACCENT_NAMES, DEFAULT_ACCENT} from '../theme/accents';
import type {AccentChoice} from '../theme/viceTheme';
import {clipTitle, imageSlug, imageTitle, libraryKey, type KeyOverlayState} from '../lib/types';
import type {
  Clip,
  Config,
  Image,
  Playlist,
  Status,
  ProcessingJob,
  DetectedGame,
  TrashSnapshot,
  UpdateInfo,
  ViewName,
  WsMessage,
} from '../lib/types';
import {t} from '../lib/i18n';

/**
 * What the status island is showing. `ambient` is the standing state of the
 * recorder; `event` is a transient that takes over for a few seconds and then
 * hands back. Keeping them separate is what lets a clip-saved notice appear
 * without losing track of the fact that a session is still running.
 */
export type IslandTone = 'neutral' | 'accent' | 'live' | 'error';

export interface IslandEvent {
  id: number;
  kind: 'saving' | 'saved' | 'error' | 'info';
  title: string;
  detail?: string;
  tone: IslandTone;
  /** How long it holds the island before the ambient state returns. */
  holdMs: number;
}

export const CUSTOM_ACCENT_KEY = 'vice-custom-accent';

export type BannerId = 'recorder' | 'cpu' | 'codec-gpu' | 'codec-h264';

interface State {
  ready: boolean;
  jobs: ProcessingJob[];
  jobsLoaded: boolean;
  trash: TrashSnapshot | null;
  trashUnavailable: boolean;
  games: DetectedGame[];
  gamesLoaded: boolean;
  settingsSection: string | null;
  queueJobId: string | null;
  loadError: string | null;
  config: Config | null;
  clips: Clip[];
  images: Image[];
  playlists: Playlist[];
  status: Status;
  statusSynced: boolean;
  tunnelError: boolean;
  update: UpdateInfo | null;
  /** Slugs that arrived this session, for the "new" treatment in the grid. */
  recentNew: string[];
  selectionMode: boolean;
  selectedMedia: string[];
  selectionAnchor: string | null;
  view: ViewName;
  currentPlaylistId: string | null;
  searchQuery: string;
  accent: AccentChoice;
  /** The seed for a custom accent, as #rrggbb. Null when none is saved. */
  customAccent: string | null;
  event: IslandEvent | null;
  sessionStartedAt: number | null;
  dismissed: BannerId[];
  /** Bumped whenever the editor should reload its project from the daemon. */
  editorProjectRevision: number;
}

const INITIAL_STATUS: Status = {
  running: false,
  version: '',
  clips: 0,
  local_url: '',
  public_url: null,
  base_url: '',
  public_is_tunnel: false,
  recording: false,
  backend: 'auto',
  session_active: false,
  hotkeys_available: true,
  ready: true,
  recorder_error: null,
  cpu_fallback: false,
  codec_fallback: false,
};

const initialState: State = {
  ready: false,
  jobs: [],
  jobsLoaded: false,
  trash: null,
  trashUnavailable: false,
  games: [],
  gamesLoaded: false,
  settingsSection: null,
  queueJobId:null,
  loadError: null,
  config: null,
  clips: [],
  images: [],
  playlists: [],
  status: INITIAL_STATUS,
  statusSynced: false,
  tunnelError: false,
  update: null,
  recentNew: [],
  selectionMode:false,
  selectedMedia:[],
  selectionAnchor:null,
  view: 'home',
  currentPlaylistId: null,
  searchQuery: '',
  accent: DEFAULT_ACCENT,
  customAccent: null,
  event: null,
  sessionStartedAt: null,
  dismissed: [],
  editorProjectRevision: 0,
};

type Action =
  | {type:'selectionMode'; active:boolean}
  | {type:'selectMedia'; id:string; visible:string[]; range?:boolean; toggle?:boolean}
  | {type:'selectAllMedia'; ids:string[]}
  | {type:'clearSelection'}
  | {type:'unselectMedia'; ids:string[]}
  | {type:'showQueue'; jobId?:string}

  | {
      type: 'loaded';
      config: Config;
      clips: Clip[];
      images: Image[];
      playlists: Playlist[];
    }
  | {type: 'statusSnapshot'; status: Status}
  | {type: 'statusStale'}
  | {type: 'jobsSnapshot'; jobs: ProcessingJob[]}
  | {type:'trashSnapshot'; trash:TrashSnapshot}
  | {type:'trashUnavailable'}
  | {type:'gamesSnapshot'; games:DetectedGame[]}
  | {type:'showGames'}
  | {type:'settingsSectionOpened'}
  | {type: 'loadFailed'; error: string}
  | {type: 'ws'; msg: WsMessage}
  | {type: 'setView'; view: ViewName; playlistId?: string | null}
  | {type: 'setSearch'; query: string}
  | {type: 'setAccent'; accent: AccentChoice; custom?: string | null}
  | {type: 'setConfig'; config: Config}
  | {type: 'mergeConfig'; patch: Record<string, Record<string, unknown>>}
  | {type: 'setClips'; clips: Clip[]}
  | {type: 'setImages'; images: Image[]}
  | {type: 'setPlaylists'; playlists: Playlist[]}
  | {type: 'event'; event: Omit<IslandEvent, 'id'>}
  | {type: 'clearEvent'; id: number}
  | {type: 'dismiss'; banner: BannerId}
  | {type: 'clearUpdate'};

let eventSeq = 0;

function withEvent(state: State, event: Omit<IslandEvent, 'id'>): State {
  return {...state, event: {...event, id: ++eventSeq}};
}

function withGames(state: State, games: DetectedGame[]): State {
  const update = <T extends {game?:string|null; game_id?:string|null}>(item:T):T => {
    const game = games.find(game => game.id === item.game_id);
    return game ? {...item, game:game.name, artwork_url:game.artwork_url} : item;
  };
  return {...state, games, gamesLoaded:true, clips:state.clips.map(update), images:state.images.map(update),
    trash:state.trash ? {...state.trash,items:state.trash.items.map(update)} : null,
    playlists:state.playlists.map(playlist => {
      const oldName=playlist.game;const next=update(playlist);
      return next.kind==='auto' && next.game!==oldName && (!playlist.edited || playlist.name===oldName) ? {...next,name:next.game ?? next.name} : next;
    })};
}

function withTrash(state: State, trash: TrashSnapshot | null): State {
  if (!trash) return state;
  const blocked=new Map(trash.items.filter(item=>item.media_id && item.source_slug).map(item=>[`${item.kind}:${item.source_slug}`,item.media_id]));
  const clips=state.clips.filter(clip=>blocked.get(`clip:${clip.slug}`)!==clip.media_id || !clip.media_id);
  const images=state.images.filter(image=>blocked.get(`image:${image.slug}`)!==image.media_id || !image.media_id);
  const active=new Set([...clips.map(clip=>clip.slug),...images.map(image=>`img:${image.slug}`)]);
  const removed=new Set(trash.items.filter(item=>item.source_slug).map(item=>item.kind==='image'?`img:${item.source_slug}`:item.source_slug!));
  return {...state,trash,trashUnavailable:false,clips,images,playlists:state.playlists.map(playlist=>({...playlist,
    clip_slugs:playlist.clip_slugs.filter(slug=>!removed.has(slug)||active.has(slug))}))};
}

function reduce(state: State, action: Action): State {
  switch (action.type) {
    case 'showQueue': return {...state,queueJobId:action.jobId ?? null};
    case 'selectionMode': return {...state,selectionMode:action.active,selectedMedia:action.active?state.selectedMedia:[],selectionAnchor:null};
    case 'clearSelection':return {...state,selectedMedia:[],selectionMode:false,selectionAnchor:null};
    case 'unselectMedia':return {...state,selectedMedia:state.selectedMedia.filter(id=>!action.ids.includes(id))};
    case 'selectAllMedia':return {...state,selectionMode:true,selectedMedia:[...new Set([...state.selectedMedia,...action.ids])]};
    case 'selectMedia': {
      const selected=new Set(state.selectedMedia);
      const anchor=state.selectionAnchor ? action.visible.indexOf(state.selectionAnchor) : -1;
      const at=action.visible.indexOf(action.id);
      if(action.range && anchor>=0 && at>=0) action.visible.slice(Math.min(at,anchor),Math.max(at,anchor)+1).forEach(id=>selected.add(id));
      else if(action.toggle && selected.has(action.id))selected.delete(action.id);
      else selected.add(action.id);
      return {...state,selectionMode:true,selectedMedia:[...selected],selectionAnchor:action.range?state.selectionAnchor:action.id};
    }
    case 'loaded': {
      const loaded: State = {
        ...state,
        ready: true,
        loadError: null,
        config: state.config ?? action.config,
        clips: action.clips,
        images: action.images,
        playlists: action.playlists,
      };
      return withTrash(state.gamesLoaded ? withGames(loaded, state.games) : loaded, state.trash);
    }

    case 'trashSnapshot':
      return withTrash(state,action.trash);
    case 'trashUnavailable':
      return {...state,trashUnavailable:true};
    case 'gamesSnapshot':
      return withGames(state, action.games);
    case 'showGames':
      return {...state,view:'settings',settingsSection:'detected-games'};
    case 'settingsSectionOpened':
      return {...state,settingsSection:null};
    case 'statusSnapshot':
      return {
        ...reduceWs(state, {type: 'status', ...action.status}),
        statusSynced: true,
        tunnelError: action.status.public_is_tunnel ? false : state.tunnelError,
      };

    case 'jobsSnapshot':
      return {...state, jobs: action.jobs, jobsLoaded: true};

    case 'statusStale':
      return {...state, statusSynced: false};

    case 'loadFailed':
      // Still mark ready: a window stuck on the boot cover cannot tell anyone
      // what went wrong, which is the failure mode #156 was about.
      return {...state, ready: true, loadError: action.error};

    case 'setView':
      return {
        ...state,
        view: action.view,
        currentPlaylistId:
          action.playlistId !== undefined ? action.playlistId : action.view === 'clips' ? state.currentPlaylistId : null,
      };

    case 'setSearch':
      return {...state, searchQuery: action.query};

    case 'setAccent':
      return {
        ...state,
        accent: action.accent,
        // A new seed only arrives with a custom pick; switching back to a
        // named swatch keeps the last custom colour so returning to it does
        // not mean picking it again.
        customAccent: action.custom !== undefined ? action.custom : state.customAccent,
      };

    case 'setConfig':
      return {...state, config: action.config};

    case 'mergeConfig': {
      if (!state.config) return state;
      const config = {...state.config} as unknown as Record<string, Record<string, unknown>>;
      for (const [section, values] of Object.entries(action.patch)) {
        config[section] = {...(config[section] ?? {}), ...values};
      }
      return {
        ...state,
        config: config as unknown as Config,
        ...(action.patch.sharing !== undefined ? {statusSynced: false, tunnelError: false} : {}),
      };
    }

    case 'setClips':
      return withTrash(state.gamesLoaded ? withGames({...state, clips:action.clips},state.games) : {...state,clips:action.clips},state.trash);

    case 'setImages':
      return withTrash({...state, images:action.images},state.trash);

    case 'setPlaylists':
      return withTrash({...state, playlists:action.playlists},state.trash);

    case 'event':
      return withEvent(state, action.event);

    case 'clearEvent':
      return state.event?.id === action.id ? {...state, event: null} : state;

    case 'dismiss':
      return state.dismissed.includes(action.banner)
        ? state
        : {...state, dismissed: [...state.dismissed, action.banner]};

    case 'clearUpdate':
      return {...state, update: null};

    case 'ws':
      return reduceWs(state, action.msg);

    default:
      return state;
  }
}

function reduceWs(state: State, msg: WsMessage): State {
  switch (msg.type) {
    case 'trash_changed':
      return withTrash(state,msg);
    case 'games_changed':
      return withGames(state,msg.games);
    case 'jobs_changed':
      return {...state, jobs: msg.jobs, jobsLoaded: true};
    case 'clip_updated':
    case 'clip_renamed': {
      const old='old_slug' in msg?msg.old_slug:msg.clip.slug;
      const existing=state.clips.find(c=>c.slug===old || c.slug===msg.clip.slug || Boolean(c.library_id && c.library_id===msg.clip.library_id));
      const clips=existing ? state.clips.map(c=>c===existing?{...c,...msg.clip}:c).filter((c,i,all)=>all.findIndex(other=>other.slug===c.slug)===i)
        : [...state.clips,msg.clip].sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at));
      return {...state,clips,recentNew:msg.type==='clip_renamed'?state.recentNew.filter(slug=>slug!==old&&slug!==msg.clip.slug):state.recentNew,
        selectedMedia:state.selectedMedia.map(id=>id===`clip:${old}`?libraryKey({kind:'clip',item:msg.clip}):id)};
    }
    case 'image_updated':
    case 'image_renamed': {
      const old='old_slug' in msg?msg.old_slug:msg.image.slug;
      const existing=state.images.find(image=>image.slug===old || image.slug===msg.image.slug || Boolean(image.library_id && image.library_id===msg.image.library_id));
      const images=existing ? state.images.map(image=>image===existing?{...image,...msg.image}:image)
        : [...state.images,msg.image].sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at));
      return {...state,images,selectedMedia:state.selectedMedia.map(id=>id===`image:${old}`?libraryKey({kind:'image',item:msg.image}):id)};
    }
    case 'clip_saved': {
      const existing = state.clips.some(c => c.slug === msg.clip.slug && (!c.library_id || !msg.clip.library_id || c.library_id===msg.clip.library_id));
      const clips = existing
        ? state.clips.map(c => (c.slug === msg.clip.slug ? {...c, ...msg.clip} : c))
        : [msg.clip, ...state.clips.filter(c=>c.slug!==msg.clip.slug)].sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at));
      const next = {
        ...state,
        clips,
        recentNew: existing ? state.recentNew : [...state.recentNew, msg.clip.slug],
      };
      // An update to a clip already on screen is not news; a new one is.
      return existing
        ? next
        : withEvent(next, {
            kind: 'saved',
            title: t('events.clipSaved'),
            detail: [clipTitle(msg.clip), msg.clip.game].filter(Boolean).join(' · '),
            tone: 'accent',
            holdMs: 4000,
          });
    }

    case 'clip_deleted':
      return {
        ...state,
        clips: state.clips.filter(c => c.slug !== msg.slug),
        recentNew: state.recentNew.filter(s => s !== msg.slug),
        selectedMedia:state.selectedMedia.filter(id=>!state.clips.some(clip=>clip.slug===msg.slug && libraryKey({kind:'clip',item:clip})===id)),
      };

    case 'image_saved': {
      const existing = state.images.some(i => i.slug === msg.image.slug && (!i.library_id || !msg.image.library_id || i.library_id===msg.image.library_id));
      const images = existing
        ? state.images.map(i => (i.slug === msg.image.slug ? {...i, ...msg.image} : i))
        : [msg.image, ...state.images.filter(image=>image.slug!==msg.image.slug)].sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at));
      const next = {...state, images};
      // An annotation or a rename updates a picture already on screen. Only a
      // genuinely new one is worth taking the island over.
      return existing
        ? next
        : withEvent(next, {
            kind: 'saved',
            title: t('events.imageSaved'),
            detail: [imageTitle(msg.image), msg.image.game].filter(Boolean).join(' · '),
            tone: 'accent',
            holdMs: 4000,
          });
    }

    case 'image_deleted':
      return {...state, images: state.images.filter(i => i.slug !== msg.slug),selectedMedia:state.selectedMedia.filter(id=>!state.images.some(image=>image.slug===msg.slug&&libraryKey({kind:'image',item:image})===id))};

    case 'image_error':
      return withEvent(state, {
        kind: 'error',
        title: t('events.errScreenshot'),
        detail: msg.error || undefined,
        tone: 'error',
        holdMs: 9000,
      });

    case 'image_copy_failed':
      // The picture saved, so this is a warning rather than a failure. Worth
      // saying: the user is about to paste and would get whatever was there.
      return withEvent(state, {
        kind: 'info',
        title: t('events.screenshotNotCopied'),
        detail: msg.error || undefined,
        tone: 'neutral',
        holdMs: 6000,
      });

    case 'playlists_changed':
      return {...state, playlists: msg.playlists ?? []};

    case 'clip_saving':
      return withEvent(state, {
        kind: 'saving',
        title: t('events.savingClip'),
        tone: 'neutral',
        // Long buffers on slow disks take a while, and clip_saved supersedes
        // this anyway, so it is allowed to sit there.
        holdMs: 30000,
      });

    case 'clip_error':
      return withEvent(state, {
        kind: 'error',
        title: t('events.errSaveClip'),
        detail: msg.error || t('events.recorderSilent'),
        tone: 'error',
        holdMs: 9000,
      });

    case 'status': {
      const {type: _ignored, ...partial} = msg;
      // Merge first, then read. A status broadcast may carry only the fields
      // that changed, and deciding from the partial would stop the session
      // clock every time one arrived without session_active in it.
      const merged = {...state.status, ...partial};
      return {
        ...state,
        status: merged,
        statusSynced:
          partial.public_is_tunnel !== undefined && partial.public_url !== undefined
            ? true : state.statusSynced,
        tunnelError: partial.public_is_tunnel ? false : state.tunnelError,
        sessionStartedAt: merged.session_active ? state.sessionStartedAt ?? Date.now() : null,
        update: partial.update ?? state.update,
      };
    }

    case 'key_overlay': {
      const {type: _ignored, ...overlay} = msg;
      return {...state, status: {...state.status, key_overlay: overlay as KeyOverlayState}};
    }

    case 'tunnel_url':
      return withEvent(
        {...state, statusSynced: false, tunnelError: false},
        {kind: 'info', title: t('events.publicLinkReady'), detail: msg.url, tone: 'accent', holdMs: 6000},
      );

    case 'tunnel_error':
      return withEvent(
        {...state, statusSynced: false, tunnelError: true},
        {
          kind: 'error',
          title: t('events.noPublicLink'),
          detail: msg.error || t('events.tunnelUnavailable'),
          tone: 'error',
          holdMs: 9000,
        },
      );

    case 'share_links_changed':
      return {
        ...state,
        clips: state.clips.map(clip => {
          const shareUrl = msg.links[clip.slug];
          return shareUrl === undefined
            ? clip
            : {...clip, share_url: shareUrl, share_is_public: msg.share_is_public};
        }),
      };

    case 'session_start':
      return withEvent(
        {
          ...state,
          status: {...state.status, recording: true, session_active: true},
          sessionStartedAt: Date.now(),
        },
        {
          kind: 'info',
          title: t('events.sessionRecording'),
          detail: t('events.doubleTapToStop'),
          tone: 'live',
          holdMs: 5000,
        },
      );

    case 'session_stop':
      return withEvent(
        {...state, status: {...state.status, session_active: false}, sessionStartedAt: null},
        {kind: 'saved', title: t('events.sessionSaved'), tone: 'accent', holdMs: 4000},
      );

    case 'session_highlight':
      return withEvent(state, {
        kind: 'info',
        title: t('events.highlightMarked'),
        detail: typeof msg.time === 'number' ? formatDuration(msg.time) : undefined,
        tone: 'accent',
        holdMs: 3000,
      });

    case 'update_available': {
      const {type: _ignored, ...info} = msg;
      return {...state, update: info};
    }

    case 'editor_project_changed':
      return {...state, editorProjectRevision: state.editorProjectRevision + 1};

    case 'daemon_upgrading':
      // The socket drops a moment after this and retries every 3 seconds, so
      // the window comes back on its own. Saying so is what stops the gap
      // reading as a crash.
      return withEvent(state, {
        kind: 'info',
        title: t('events.updating', {version: msg.version ?? ''}),
        detail: t('events.updatingDetail'),
        tone: 'accent',
        holdMs: 12000,
      });

    // Export progress belongs to the editor, which subscribes separately.
    case 'export_progress':
    case 'export_done':
    case 'export_error':
      return state;

    default:
      return state;
  }
}

interface Store {
  state: State;
  dispatch: React.Dispatch<Action>;
  /** Clips filtered by the sidebar search and the open playlist. */
  visibleClips: Clip[];
  visibleImages: Image[];
  hotkey: string;
  refreshClips: () => Promise<void>;
  refreshImages: () => Promise<void>;
  refreshPlaylists: () => Promise<void>;
  refreshGames: () => Promise<void>;
  refreshTrash: () => Promise<void>;
  notify: (event: Omit<IslandEvent, 'id'>) => void;
  saveConfig: (
    patch: Record<string, Record<string, unknown>>,
  ) => Promise<{applied?: boolean; warning?: string; restart_required?: boolean}>;
}

const StoreContext = createContext<Store | null>(null);

export function StoreProvider({children}: {children: ReactNode}) {
  const [state, dispatch] = useReducer(reduce, initialState);

  const libraryEvents = useRef(0);

  // First load. Everything the shell needs before it can show a screen.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const config = await api.getConfig();
        let clips:Clip[], images:Image[], playlists:Playlist[], seen:number;
        do {
          seen = libraryEvents.current;
          [clips,images,playlists] = await Promise.all([api.clips(),api.images(),api.playlists()]);
        } while (!cancelled && seen !== libraryEvents.current);
        if (!cancelled) dispatch({type: 'loaded', config, clips, images, playlists});
      } catch (err) {
        if (!cancelled) dispatch({type: 'loadFailed', error: (err as Error).message});
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // The accent is a per-install preference, not a synced setting.
  useEffect(() => {
    let custom: string | null = null;
    try {
      const raw = localStorage.getItem(CUSTOM_ACCENT_KEY);
      custom = raw && /^#[0-9a-f]{6}$/i.test(raw) ? raw.toLowerCase() : null;
    } catch (err) {
      console.debug('Reading the custom accent failed', err);
    }
    const saved = localStorage.getItem('vice-theme');
    const named = saved && (ACCENT_NAMES as string[]).includes(saved);
    // A saved 'custom' with no seed behind it is not a usable accent, so it
    // falls back rather than opening the window in a half-applied theme.
    if (named || (saved === 'custom' && custom)) {
      dispatch({type: 'setAccent', accent: saved as AccentChoice, custom});
    } else if (custom) {
      dispatch({type: 'setAccent', accent: DEFAULT_ACCENT, custom});
    }
  }, []);

  // Bumped by every picture event, so a list fetched before one can tell it is
  // out of date. Listing probes every file and takes about a second on a real
  // library, long enough to delete a picture while a stale copy is in flight.
  const imageEvents = useRef(0);
  const refreshTrashRef = useRef<() => Promise<void>>(async () => {});
  const refreshTrash = useCallback(() => refreshTrashRef.current(), []);
  const refreshGamesRef = useRef<() => Promise<void>>(async () => {});
  const refreshGames = useCallback(() => refreshGamesRef.current(), []);
  const refreshStatus = useRef<() => Promise<void>>(async () => {});
  useEffect(() => {
    let cancelled = false;
    let request = 0;
    let statusEvents = 0;
    let trashRequest = 0;
    const syncTrash = async () => {
      const current = ++trashRequest;
      try {
        const trash = await api.trash();
        if(!cancelled && current===trashRequest) dispatch({type:'trashSnapshot',trash});
      } catch {
        if(!cancelled && current===trashRequest) dispatch({type:'trashUnavailable'});
      }
    };
    let gamesRequest = 0;
    const syncGames = async () => {
      const current = ++gamesRequest;
      try {
        const games = await api.games();
        if (!cancelled && current === gamesRequest) dispatch({type:'gamesSnapshot',games});
      } catch (error) {console.debug('Refreshing game library failed',error);}
    };
    let jobsRequest = 0;
    const syncJobs = async () => {
      const current = ++jobsRequest;
      try {
        const jobs = await api.jobs();
        if (!cancelled && current === jobsRequest) dispatch({type: 'jobsSnapshot', jobs});
      } catch (err) {console.debug('Refreshing processing queue failed', err);}
    };
    const syncStatus = async () => {
      const current = ++request;
      const seen = statusEvents;
      try {
        const status = await api.status();
        if (cancelled || current !== request) return;
        // A newer event may describe a change after the server took this
        // snapshot. Reconcile once more rather than overwriting that event.
        if (seen !== statusEvents) {
          void syncStatus();
          return;
        }
        dispatch({type: 'statusSnapshot', status});
      } catch (err) {
        if (!cancelled && current === request) {
          dispatch({type: 'statusStale'});
          console.debug('Refreshing backend status failed', err);
        }
      }
    };
    refreshStatus.current = syncStatus;
    refreshGamesRef.current = syncGames;
    refreshTrashRef.current = syncTrash;
    const disconnect = connectWs(msg => {
      if (cancelled) return;
      if (['clip_saved','clip_updated','clip_renamed','clip_deleted','image_saved','image_updated','image_renamed','image_deleted','playlists_changed'].includes(msg.type)) libraryEvents.current += 1;
      if (msg.type === 'trash_changed') trashRequest += 1;
      if (msg.type === 'games_changed') gamesRequest += 1;
      if (msg.type === 'jobs_changed') jobsRequest += 1;
      if (['image_saved','image_updated','image_renamed','image_deleted'].includes(msg.type)) imageEvents.current += 1;
      if (['status', 'tunnel_url', 'tunnel_error', 'session_start', 'session_stop'].includes(msg.type)) {
        statusEvents += 1;
      }
      if (msg.type === 'config_changed') {
        void api.getConfig().then(config => {
          if (!cancelled) {
            dispatch({type: 'setConfig', config});
            void syncStatus();
          }
        }).catch(err => console.debug('Reloading the config failed', err));
      }
      dispatch({type: 'ws', msg});
      if (msg.type === 'tunnel_url' || msg.type === 'tunnel_error' || msg.type === 'share_links_changed') {
        void syncStatus();
      }
    }, {
      // The socket is subscribed before this snapshot, closing the gap where
      // a tunnel event could have been missed between HTTP load and WS open.
      onOpen: () => {
        void syncStatus(); void syncJobs(); void syncGames(); void syncTrash();
        void Promise.all([refreshClips(),refreshImages(),refreshPlaylists()]).catch(error=>console.debug('Library recovery failed',error));
      },
      onClose: () => {
        request += 1;
        jobsRequest += 1;
        gamesRequest += 1;
        trashRequest += 1;
        dispatch({type: 'statusStale'});
      },
    });
    // Also load when the WebSocket cannot connect. Slow clip enumeration must
    // never hold this snapshot, or overwrite subsequent live status updates.
    void syncStatus();
    void syncJobs();
    void syncGames();
    void syncTrash();
    const resume = () => {void syncStatus(); void syncJobs(); void syncGames(); void syncTrash();};
    const visible = () => {if (document.visibilityState === 'visible') resume();};
    window.addEventListener('focus', resume);
    window.addEventListener('online', resume);
    document.addEventListener('visibilitychange', visible);
    return () => {
      cancelled = true;
      request += 1;
      jobsRequest += 1;
      gamesRequest += 1;
      trashRequest += 1;
      refreshTrashRef.current = async () => {};
      refreshStatus.current = async () => {};
      refreshGamesRef.current = async () => {};
      disconnect();
      window.removeEventListener('focus', resume);
      window.removeEventListener('online', resume);
      document.removeEventListener('visibilitychange', visible);
    };
  }, []);

  useEffect(() => {
    const unavailable = () => dispatch({type: 'event', event: {kind: 'error',
      title: t('drag.unavailable'), detail: t('drag.fallback'), tone: 'error', holdMs: 8000}});
    window.addEventListener('vice-drag-unavailable', unavailable);
    return () => window.removeEventListener('vice-drag-unavailable', unavailable);
  }, []);

  // Transient island events expire on their own.
  useEffect(() => {
    if (!state.event) return;
    const {id, holdMs} = state.event;
    const timer = window.setTimeout(() => dispatch({type: 'clearEvent', id}), holdMs);
    return () => window.clearTimeout(timer);
  }, [state.event]);

  // Say it once, on the machines where it is true: clips will never play here.
  useEffect(() => {
    if (state.ready && !H264_SUPPORTED) {
      dispatch({
        type: 'event',
        event: {
          kind: 'error',
          title: t('events.cannotPlay'),
          detail: t('events.noH264'),
          tone: 'error',
          holdMs: 10000,
        },
      });
    }
  }, [state.ready]);

  const refreshClips = useCallback(async () => {
    let clips:Clip[], seen:number;
    do {seen=libraryEvents.current;clips=await api.clips();} while(seen!==libraryEvents.current);
    dispatch({type:'setClips',clips});
  }, []);

  const refreshImages = useCallback(async () => {
    const seen = imageEvents.current;
    const images = await api.images();
    // The events that arrived meanwhile are newer than this list and already applied.
    if (imageEvents.current === seen) dispatch({type: 'setImages', images});
  }, []);

  const refreshPlaylists = useCallback(async () => {
    dispatch({type: 'setPlaylists', playlists: await api.playlists()});
  }, []);

  const notify = useCallback((event: Omit<IslandEvent, 'id'>) => {
    dispatch({type: 'event', event});
  }, []);

  /**
   * Persist a partial config and merge it locally.
   *
   * The daemon answers with a result rather than the new config, so the patch
   * we sent is what gets merged, matching what the old UI did. Throws on
   * failure so callers can revert their own control.
   */
  const saveConfig = useCallback(
    async (patch: Record<string, Record<string, unknown>>) => {
      const result = await api.saveConfig(patch);
      if (result.ok === false) throw new Error(result.error || t('events.notSaved'));
      dispatch({type: 'mergeConfig', patch});
      if (patch.sharing) await refreshStatus.current();
      return result;
    },
    [],
  );

  const visibleClips = useMemo(() => {
    const query = state.searchQuery.trim().toLowerCase();
    const playlist = state.currentPlaylistId
      ? state.playlists.find(p => p.id === state.currentPlaylistId)
      : null;
    let list = state.clips;
    if (playlist) {
      const members = new Set(playlist.clip_slugs ?? []);
      list = list.filter(c => members.has(c.slug));
    }
    if (query) {
      list = list.filter(
        c => clipTitle(c).toLowerCase().includes(query) || c.name.toLowerCase().includes(query) || (c.game ?? '').toLowerCase().includes(query),
      );
    }
    return list;
  }, [state.clips, state.playlists, state.currentPlaylistId, state.searchQuery]);

  // Same rules as visibleClips, against the prefixed membership key. Kept
  // separate rather than folded into one list: the two grids are shown on
  // different screens and only meet inside an open playlist.
  const visibleImages = useMemo(() => {
    const query = state.searchQuery.trim().toLowerCase();
    const playlist = state.currentPlaylistId
      ? state.playlists.find(p => p.id === state.currentPlaylistId)
      : null;
    let list = state.images;
    if (playlist) {
      const members = new Set(playlist.clip_slugs ?? []);
      list = list.filter(i => members.has(imageSlug(i.slug)));
    }
    if (query) {
      list = list.filter(
        i => imageTitle(i).toLowerCase().includes(query) || i.name.toLowerCase().includes(query) || (i.game ?? '').toLowerCase().includes(query),
      );
    }
    return list;
  }, [state.images, state.playlists, state.currentPlaylistId, state.searchQuery]);

  const hotkey = useMemo(
    () => hotkeyLabel(state.config?.hotkeys?.clip as string | undefined),
    [state.config],
  );

  const value = useMemo<Store>(
    () => ({
      state,
      dispatch,
      visibleClips,
      visibleImages,
      hotkey,
      refreshClips,
      refreshImages,
      refreshPlaylists,
      refreshGames,
      refreshTrash,
      notify,
      saveConfig,
    }),
    [
      state,
      visibleClips,
      visibleImages,
      hotkey,
      refreshClips,
      refreshImages,
      refreshPlaylists,
      refreshGames,
      refreshTrash,
      notify,
      saveConfig,
    ],
  );

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): Store {
  const store = useContext(StoreContext);
  if (!store) throw new Error('useStore was called outside the provider');
  return store;
}
