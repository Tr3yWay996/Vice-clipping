/**
 * Shapes the daemon actually sends. Verified against a running ShareServer
 * rather than inferred, because several of them are not what you would guess:
 * list endpoints are wrapped in an envelope, timestamps are ISO strings, and
 * `name` still carries the file extension.
 */

export interface Clip {
  slug: string;
  media_id?: string | null;
  /** The filename, extension included. Use clipTitle() for display. */
  name: string;
  size: number;
  created_at: string;
  game: string | null;
  game_id?: string | null;
  artwork_url?: string | null;
  views: number;
  /** Keys were kept beside this clip for the viewer's keyboard overlay. */
  keys?: boolean;
  duration: number | null;
  width: number | null;
  height: number | null;
  vcodec: string | null;
  audio_tracks?: Array<{index: number; title: string; language: string; channels: number}>;
  /** Set when ffprobe could not read the file. The clip is left on disk. */
  unreadable: boolean;
  unreadable_reason: string;
  share_url: string;
  share_is_public: boolean;
  /** Already carries a content revision, so it can be used as a cache key. */
  video_url: string;
  thumb_url: string;
}

/**
 * A screenshot. Deliberately not a Clip with the video fields nulled: an image
 * has no duration, no codec and no share link, and every one of those absences
 * would have to be special-cased at the point of use.
 */
export interface Image {
  slug: string;
  media_id?: string | null;
  /** The filename, extension included. Use imageTitle() for display. */
  name: string;
  size: number;
  created_at: string;
  game: string | null;
  game_id?: string | null;
  artwork_url?: string | null;
  width: number;
  height: number;
  /** Carries the file revision, so an annotation shows rather than the cache. */
  image_url: string;
  thumb_url: string | null;
}

/** A marked timestamp inside one clip. The id is a string of digits. */
export interface Highlight {
  id: string;
  time: number;
  label: string;
  color: string;
}

export interface Playlist {
  id: string;
  kind: 'auto' | 'custom' | string;
  name: string;
  game: string | null;
  game_id?: string | null;
  artwork_url?: string | null;
  emoji: string | null;
  color1: string | null;
  color2: string | null;
  clip_slugs: string[];
  created_at: string;
  edited: boolean;
}

export interface Status {
  running: boolean;
  version: string;
  /** A count, not the clips themselves. */
  clips: number;
  images?: number;
  local_url: string;
  public_url: string | null;
  base_url: string;
  public_is_tunnel: boolean;
  recording: boolean;
  backend: string;
  session_active: boolean;
  hotkeys_available: boolean;
  /** False while the recorder is down, paired with recorder_error (#156). */
  ready: boolean;
  recorder_error: string | null;
  cpu_fallback: boolean;
  /** Why the GPU encoder would not open, when Vice can tell (#247). */
  cpu_fallback_reason?: {
    kind: 'nvenc_api';
    driver: string;
    required: string;
    /** The Flatpak gpu-screen-recorder is installed, and which one ran. */
    flatpak?: boolean;
    source?: 'native' | 'flatpak' | null;
  } | null;
  gsr?: {source: 'native' | 'flatpak' | null; flatpak: boolean} | null;
  codec_fallback: boolean;
  /** Where clips land. Absent when the drive could not be measured. */
  disk?: {free: number; total: number} | null;
  update?: UpdateInfo | null;
  key_overlay?: KeyOverlayState | null;
}

/** The on-screen keyboard overlay's process, as the daemon sees it. */
export interface KeyOverlayState {
  running: boolean;
  error: 'no-layer-shell' | 'no-gtk' | 'no-display' | 'crashed' | null;
  moving: boolean;
}

export interface UpdateInfo {
  version: string;
  url?: string;
  /** Summarised release-note lines, one per bullet. */
  notes?: string[];
  /**
   * How this machine should update, worked out by the daemon: "aur",
   * "script" or "unknown". The command is empty for unknown.
   */
  install?: {method?: string; command?: string};
}

export interface Config {
  recording: Record<string, unknown> & {
    buffer_duration: number;
    clip_duration: number;
    fps: number;
  };
  hotkeys: Record<string, unknown> & {clip: string; clip_presets: unknown[]};
  output: Record<string, unknown> & {directory: string};
  sharing: Record<string, unknown> & {port: number; cloudflare_tunnel: boolean};
  discord: Record<string, unknown> & {enabled: boolean};
  updates: Record<string, unknown>;
  notifications: Record<string, unknown>;
  ui: Record<string, unknown>;
  overlay?: Record<string, unknown>;
}

/** Every message the daemon broadcasts. */
export type WsMessage =
  | ({type:'trash_changed'} & TrashSnapshot)
  | {type: 'games_changed'; games: DetectedGame[]; revision: number}
  | {type: 'jobs_changed'; jobs: ProcessingJob[]}
  | {type: 'clip_saved'; clip: Clip}
  | {type: 'clip_deleted'; slug: string}
  | {type: 'image_saved'; image: Image}
  | {type: 'image_deleted'; slug: string}
  | {type: 'image_error'; error?: string}
  | {type: 'image_copy_failed'; error?: string}
  | {type: 'playlists_changed'; playlists: Playlist[]}
  | {type: 'clip_saving'}
  | {type: 'clip_error'; error?: string}
  | ({type: 'status'} & Partial<Status>)
  | {type: 'tunnel_url'; url: string}
  | {type: 'tunnel_error'; error?: string}
  | {type: 'share_links_changed'; links: Record<string, string>; share_is_public: boolean}
  | {type: 'session_start'}
  | {type: 'session_stop'}
  | {type: 'session_highlight'; time?: number}
  | {type: 'export_progress'; [key: string]: unknown}
  | {type: 'export_done'; [key: string]: unknown}
  | {type: 'export_error'; [key: string]: unknown}
  | {type: 'editor_project_changed'}
  | {type: 'daemon_upgrading'; version?: string}
  | ({type: 'update_available'} & UpdateInfo)
  | ({type: 'key_overlay'} & KeyOverlayState)
  | {type: 'config_changed'};

export type ViewName = 'home' | 'clips' | 'images' | 'editor' | 'settings' | 'trash' | 'about';

/** The filename without its extension, which is what every screen shows. */
export function clipTitle(clip: Clip): string {
  return clip.name.replace(/\.(mp4|mkv|mov|webm)$/i, '');
}

export function imageTitle(image: Image): string {
  return image.name.replace(/\.(png|jpe?g)$/i, '');
}

/**
 * Clips and images share one playlist membership list, so an image is stored
 * under a prefix. Mirrors playlists.IMAGE_PREFIX on the daemon; if the two
 * ever disagree, membership silently stops matching.
 */
export const IMAGE_PREFIX = 'img:';

export const imageSlug = (slug: string) => `${IMAGE_PREFIX}${slug}`;

export interface ProcessingJob {
  id: string;
  operation: 'trim' | 'export' | 'prepare';
  name: string;
  source_revision: string | null;
  output_path: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration: number | null;
  progress: number | null;
  elapsed: number;
  remaining: number | null;
  speed: number | null;
  stage: string;
  status: 'queued' | 'processing' | 'paused' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
  error: string | null;
  result_path: string | null;
  can_pause: boolean;
}

export type GameRules = Record<'executables' | 'paths' | 'classes' | 'steam_ids' | 'titles', string[]>;
export interface DetectedGame {
  id: string;
  name: string;
  automatic_name: string;
  user_rules?: boolean;
  source: 'steam' | 'builtin' | 'custom' | 'process' | 'manual' | 'legacy';
  status: 'recognized' | 'confirmed' | 'pending' | 'deferred' | 'rejected';
  rules: GameRules;
  steam_app_id: string | null;
  artwork_override: string | null;
  automatic_artwork: string | null;
  artwork_url: string | null;
  last_detected: string | null;
  clip_count: number;
}

export interface TrashItem {
  id: string; name: string; source_slug?:string; media_id?:string|null; kind: 'clip'|'image'; size: number; original_dir: string;
  game: string|null; game_id?:string|null; created_at: string; deleted_at: string; remaining_seconds: number|null;
  available: boolean; state: string; thumbnail_url: string|null;
}
export interface TrashSnapshot {
  items: TrashItem[]; total_bytes: number; retention_days: number; error: string|null;
}
