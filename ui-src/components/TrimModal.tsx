import {usePlaybackSpeed, mediaBoost} from './PlaybackSpeed';
import {useEffect, useMemo, useRef, useState} from 'react';

import {api} from '../lib/api';
import {useEscape} from '../lib/escape';
import {usePlaybackShortcuts} from '../lib/playbackShortcuts';
import {formatDuration, formatNumber} from '../lib/format';
import {
  useScrubSeek,
  playbackShortcut,
  playQuietly,
  playbackUrl,
  timecode,
  useVideoFailure,
  videoFailureMessage,
} from '../lib/playback';
import {clipTitle, type Clip, type Highlight} from '../lib/types';
import {IconClose} from './Icons';
import {InlineRename} from './InlineRename';
import {t} from '../lib/i18n';
import {VolumeControl, PlayPauseButton, PlaybackTime, VideoLoading, usePlaybackAudio} from './PlaybackControls';
import {
  MIN_SELECTION,
  boundaryAtPlayhead,
  lowerBound,
  moveBoundary,
  nearestBoundary,
  nearestKeyframe,
  snapSelection,
  visibleKeyframes,
  type Boundary,
  type KeyframeInfo,
} from '../lib/trimming';

/**
 * Trim a clip down to a selection.
 *
 * Playback goes through the H.264 proxy for codecs this window cannot decode,
 * so the selection can be scrubbed; the cut itself always runs on the original
 * file, so proxying never touches what lands on disk.
 */
export function TrimModal({
  clip,
  highlights,
  onClose,
  onSaved,
  notify,
  onRename,
  onReveal,
  onOpenExternally,
}: {
  clip: Clip | null;
  /** Shown on the timeline when they belong to this clip. */
  highlights: Highlight[];
  onClose: () => void;
  onSaved: () => Promise<void> | void;
  notify: (title: string, detail?: string, tone?: 'accent' | 'error') => void;
  onRename: (clip: Clip, name: string) => void;
  onReveal: (clip: Clip) => void;
  onOpenExternally: (clip: Clip) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const shortcutRoot = useRef<HTMLDivElement>(null);
  const timelineRef = useRef<HTMLDivElement>(null);
  const [paused, setPaused] = useState(true);
  const {volume, muted, setVolume, toggleMuted} = usePlaybackAudio(videoRef);
  const [keyframes, setKeyframes] = useState<KeyframeInfo | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [showKeyframes, setShowKeyframes] = useState(false);
  const [snapMessage, setSnapMessage] = useState<string | null>(null);
  const [timelineWidth, setTimelineWidth] = useState(0);
  const gesture = useRef<{
    pointer: number;
    x: number;
    y: number;
    handle?: Boundary;
    moved: boolean;
  } | null>(null);
  const [total, setTotal] = useState(0);
  const [selection, setSelection] = useState({start: 0, end: 0});
  const [playhead, setPlayhead] = useState(0);
  const {seek: scrubSeek} = useScrubSeek(videoRef, setPlayhead);
  const [previewing, setPreviewing] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [dragging, setDragging] = useState<'start' | 'end' | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [renamingTitle, setRenamingTitle] = useState(false);
  const speed = usePlaybackSpeed();
  // Held until the dialog closes. Renaming the file straight away swapped the
  // clip under the dialog, which threw the selection away and, for an H.265
  // clip, made the preview transcode all over again (#226).
  const [pendingName, setPendingName] = useState<string | null>(null);
  // Replacing the original asks twice, because it throws away everything
  // outside the selection (#255).
  const [confirmReplace, setConfirmReplace] = useState(false);
  const failed = useVideoFailure(videoRef, clip !== null);

  // Preview state is read inside a media event handler, so it needs a ref as
  // well: the listener would otherwise close over whatever it was at mount.
  const previewingRef = useRef(false);
  previewingRef.current = previewing;
  const selectionRef = useRef(selection);
  selectionRef.current = selection;

  const close = () => {
    if (clip && pendingName && pendingName !== clipTitle(clip)) onRename(clip, pendingName);
    setPendingName(null);
    onClose();
  };

  useEscape(clip !== null, close);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !clip) return;
    setTotal(0);
    setPaused(true);
    setDragging(null);
    gesture.current = null;
    setShowKeyframes(false);
    setSnapMessage(null);
    setSelection({start: 0, end: 0});
    setPlayhead(0);
    setPreviewing(false);
    setSaving(false);
    setError(null);
    setPreparing(true);
    setPendingName(null);
    setConfirmReplace(false);
    video.src = playbackUrl(clip);
    video.load();
    return () => {
      video.pause();
      video.removeAttribute('src');
      video.load();
    };
  }, [clip?.library_id ?? clip?.slug, clip?.content_revision ?? clip?.video_url]);


  useEffect(() => {
    setKeyframes(null);
    setAnalysisError(null);
    if (!clip) return;
    const controller = new AbortController();
    setAnalyzing(true);
    api
      .keyframes(clip.slug, controller.signal)
      .then((info) => {
        if (!controller.signal.aborted) setKeyframes(info);
      })
      .catch(() => {
        if (!controller.signal.aborted) setAnalysisError(t('trim.keyframesUnavailable'));
      })
      .finally(() => {
        if (!controller.signal.aborted) setAnalyzing(false);
      });
    return () => controller.abort();
  }, [clip?.library_id ?? clip?.slug, clip?.content_revision ?? clip?.video_url]);

  useEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) return;
    const measure = () => setTimelineWidth(timeline.getBoundingClientRect().width);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(timeline);
    return () => observer.disconnect();
  }, [clip?.library_id ?? clip?.slug, clip?.content_revision ?? clip?.video_url]);

  // Media timeupdate is deliberately infrequent. Paint a smooth playhead while
  // playing and keep paused/seeked updates on the media events below.
  useEffect(() => {
    if (paused || !clip) return;
    let frame: number;
    const tick = () => {
      if (videoRef.current) setPlayhead(videoRef.current.currentTime);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [paused, clip]);

  const markers = useMemo(
    () =>
      showKeyframes ? visibleKeyframes(keyframes?.timestamps ?? [], total, timelineWidth) : [],
    [showKeyframes, keyframes, total, timelineWidth],
  );

  const stopPreview = () => {
    setPreviewing(false);
    previewingRef.current = false;
    videoRef.current?.pause();
  };
  const leavePreview = () => {
    previewingRef.current = false;
    setPreviewing(false);
  };

  const togglePreview = () => {
    const video = videoRef.current;
    if (!total || !video) return;
    if (previewing) {
      stopPreview();
      return;
    }
    setPreviewing(true);
    previewingRef.current = true;
    video.currentTime = selection.start;
    playQuietly(video);
  };

  const onTimeUpdate = () => {
    const video = videoRef.current;
    if (!video) return;
    setPlayhead(video.currentTime);
    if (!previewingRef.current || !total) return;
    const {start, end} = selectionRef.current;
    // Loop the selection. The tolerance on the lower bound is deliberate: a
    // scrub lands a little before the in point, and a tight comparison would
    // read every ordinary frame near the start as a scrub and stutter.
    if (video.currentTime >= end - 0.05 || video.currentTime < start - 0.3) {
      video.currentTime = start;
      setPlayhead(start);
      if (video.paused) playQuietly(video);
    }
  };

  const seek = (at: number, immediate = true) => {
    leavePreview();
    const next = Math.max(0, Math.min(total, at));
    scrubSeek(next, immediate);
  };

  const togglePlayback = () => {
    const video = videoRef.current;
    if (!video || !total) return;
    if (video.paused) playQuietly(video);
    else video.pause();
  };

  const updateBoundary = (handle: Boundary, at: number) => {
    const next = moveBoundary(
      selectionRef.current,
      handle,
      at,
      total,
      showKeyframes ? keyframes?.timestamps : undefined,
    );
    selectionRef.current = next;
    setSelection(next);
    setSnapMessage(null);
    leavePreview();
  };

  const setBoundary = (handle: Boundary) => {
    const next = boundaryAtPlayhead(selectionRef.current, handle, videoRef.current?.currentTime ?? 0,
      total, showKeyframes ? keyframes?.timestamps : undefined);
    if (!next) {setSnapMessage(t('trim.invalidBoundary', {duration:formatDuration(Math.min(MIN_SELECTION, total), true)})); return;}
    leavePreview();
    selectionRef.current = next;
    setSelection(next);
    setSnapMessage(null);
  };

  const timeAt = (clientX: number) => {
    const rect = timelineRef.current?.getBoundingClientRect();
    return rect?.width ? Math.max(0, Math.min(1, (clientX - rect.left) / rect.width)) * total : 0;
  };

  const beginGesture = (event: React.PointerEvent<HTMLElement>, handle?: Boundary) => {
    if (event.button !== 0 || !total || saving) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.focus({preventScroll:true});
    leavePreview();
    gesture.current = {
      pointer: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      handle,
      moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(handle ?? null);
  };

  const moveGesture = (event: React.PointerEvent) => {
    const current = gesture.current;
    if (!current || current.pointer !== event.pointerId) return;
    current.moved ||= Math.hypot(event.clientX - current.x, event.clientY - current.y) >= 4;
    if (current.handle) updateBoundary(current.handle, timeAt(event.clientX));
    else if (current.moved) seek(timeAt(event.clientX), false);
  };

  const endGesture = (event: React.PointerEvent<HTMLElement>) => {
    const current = gesture.current;
    if (!current || current.pointer !== event.pointerId) return;
    // Some engines coalesce all motion before pointerup.
    current.moved ||= Math.hypot(event.clientX - current.x, event.clientY - current.y) >= 4;
    if (event.type !== 'pointercancel' && event.type !== 'lostpointercapture') {
      const at = timeAt(event.clientX);
      if (current.handle) updateBoundary(current.handle, at);
      else if (current.moved) seek(at);
      else if (event.shiftKey) updateBoundary(nearestBoundary(selectionRef.current, at), at);
      else seek(at);
    }
    gesture.current = null;
    setDragging(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const boundaryKey = (event: React.KeyboardEvent, handle: Boundary) => {
    if (saving) return;
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
    leavePreview();
    const current = selectionRef.current[handle];
    const direction = event.key === 'ArrowLeft' ? -1 : 1;
    let at =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? total
          : current + direction * (event.shiftKey ? 0.1 : 1);
    if (showKeyframes && keyframes && event.key.startsWith('Arrow')) {
      const keys = keyframes.timestamps;
      const index = lowerBound(keys, current);
      at =
        direction < 0
          ? (keys[index - 1] ?? current)
          : (keys[keys[index] === current ? index + 1 : index] ?? current);
    }
    updateBoundary(handle, at);
  };

  const manualSnap = () => {
    if (!keyframes) return;
    const next = snapSelection(selectionRef.current, keyframes.timestamps, total);
    if (!next) {
      setSnapMessage(t('trim.noKeyframePair'));
      return;
    }
    leavePreview();
    selectionRef.current = next;
    setSelection(next);
    setSnapMessage(null);
  };

  const save = async (copy: boolean) => {
    if (!clip) return;
    if (previewing) stopPreview();
    setSaving(true);
    setError(null);
    setConfirmReplace(false);
    try {
      const result = await api.trimClip(clip.slug, selection.start, selection.end, copy, pendingName ?? undefined);
      if (result.job_id) {
        setPendingName(null);
        notify(t('queue.submitted'), clipTitle(clip), 'accent');
        onClose();
        return;
      }
      const name = pendingName && pendingName !== clipTitle(clip) ? pendingName : null;
      setPendingName(null);
      // A name typed while saving a copy belongs to the copy: the original is
      // the clip being kept as it was.
      if (name) onRename(copy && result.slug ? {...clip, slug: result.slug} : clip, name);
      notify(copy ? t('trim.savedCopy') : t('trim.saved'), name ?? clipTitle(clip), 'accent');
      onClose();
      await onSaved();
    } catch (err) {
      const message = (err as Error).message || t('trim.failed');
      setError(message);
      notify(t('trim.errTrim'), message, 'error');
      setSaving(false);
    }
  };

  usePlaybackShortcuts(clip !== null && !saving, shortcutRoot, 30, event => playbackShortcut(event, {
    toggle: togglePlayback, rename:() => setRenamingTitle(true), mute: toggleMuted, time: () => videoRef.current?.currentTime ?? 0,
    duration: () => total, seek, volume: () => volume, setVolume, boundary: setBoundary,
  }), () => mediaBoost(videoRef, speed.actions), clip?.slug);

  if (!clip) return null;

  const pct = (seconds: number) => (total ? (seconds / total) * 100 : 0);
  const startPct = pct(selection.start);
  const endPct = pct(selection.end);

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div
        className="modal trim-modal"
        ref={shortcutRoot}
        role="dialog"
        aria-modal="true"
        aria-label={t('trim.trimAria', {name: clipTitle(clip)})}>
        <div className="modal-head">
          {/* The name is its own element rather than part of a templated
              sentence, so it can be renamed from here without the field
              swallowing the word "Trim" as well (#170). */}
          <h2 className="trim-head">
            <span className="trim-head-label">{t('trim.heading')}</span>
            {renamingTitle ? (
              <InlineRename
                className="trim-rename" stopPropagation
                label={t('card.nameLabel')}
                initial={pendingName ?? clipTitle(clip)}
                onCancel={() => setRenamingTitle(false)}
                onSubmit={(name) => {
                  setRenamingTitle(false);
                  setPendingName(name);
                }}
              />
            ) : (
              <span
                className="trim-head-name"
                title={t('viewer.clickRename')}
                role="button" tabIndex={0}
                onClick={e => {e.stopPropagation();setRenamingTitle(true);}}
                onKeyDown={e => {if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();setRenamingTitle(true);}}}>
                {pendingName ?? clipTitle(clip)}
              </span>
            )}
          </h2>
          <button
            type="button"
            className="modal-close"
            onClick={close}
            aria-label={t('common.close')}>
            <IconClose size={15} />
          </button>
        </div>

        <div className="modal-body">
          <div className="trim-stage" onClick={togglePlayback}>
            <video
              ref={videoRef}
              className="trim-video"
              playsInline
              onLoadedMetadata={(e) => {
                const seconds = Number.isFinite(e.currentTarget.duration)
                  ? e.currentTarget.duration
                  : 0;
                setTotal(seconds);
                const next = {start: 0, end: seconds};
                setSelection(next);
                selectionRef.current = next;
              }}
              onTimeUpdate={onTimeUpdate}
              onSeeked={e=>{setPreparing(e.currentTarget.readyState<2);onTimeUpdate();}}
              onSeeking={() => setPreparing(true)}
              onWaiting={() => setPreparing(true)}
              onLoadedData={() => setPreparing(false)}
              onPlay={() => setPaused(false)}
              onPause={() => setPaused(true)}
              onEnded={() => {
                const video = videoRef.current;
                if (!previewingRef.current || !video) return;
                video.currentTime = selectionRef.current.start;
                playQuietly(video);
              }}
              onCanPlay={() => setPreparing(false)}
              onError={() => setPreparing(false)}
            />
            <VideoLoading preparing={preparing}/>
            {failed ? (
              <div className="video-overlay">
                <p>{videoFailureMessage()}</p>
                <div className="video-overlay-actions">
                  <button type="button" className="btn" onClick={() => onOpenExternally(clip)}>
                    {t('trim.openInPlayer')}
                  </button>
                  <button type="button" className="btn btn-quiet" onClick={() => onReveal(clip)}>
                    {t('trim.showInFolder')}
                  </button>
                </div>
              </div>
            ) : null}
          </div>

          <div className="trim-playback">
            <PlayPauseButton paused={paused} onToggle={togglePlayback} disabled={!total}/>
            <PlaybackTime current={playhead} duration={total}/>{speed.control}
            <VolumeControl
              volume={volume}
              muted={muted}
              onChange={setVolume}
              onToggleMute={toggleMuted}
            />
          </div>

          <div className="trim-readout">
            <span>
              {t('trim.in')} <b className="mono">{formatDuration(selection.start, true)}</b>
            </span>
            <span>
              {t('trim.duration')}{' '}
              <b className="mono trim-readout-dur">
                {formatDuration(Math.max(0, selection.end - selection.start), true)}
              </b>
            </span>
            <span>
              {t('trim.out')} <b className="mono">{formatDuration(selection.end, true)}</b>
            </span>
          </div>

          <div
            className="trim-timeline"
            tabIndex={0}
            ref={timelineRef}
            role="group"
            aria-label={t('trim.seekTimeline')}
            onPointerDown={(event) => beginGesture(event)}
            onPointerMove={moveGesture}
            onPointerUp={endGesture}
            onPointerCancel={endGesture}
            onLostPointerCapture={endGesture}>
            <div
              className="trim-seek"
              role="slider"
              tabIndex={0}
              aria-label={t('trim.seekTimeline')}
              aria-valuemin={0}
              aria-valuemax={total}
              aria-valuenow={playhead}
              aria-valuetext={timecode(playhead)}
              aria-disabled={!total || saving}
              onKeyDown={(event) => {
                if (event.target !== event.currentTarget || saving) return;
                if (event.key === 'Enter') {
                  event.preventDefault();
                  togglePlayback();
                }
              }}
            />
            <div className="trim-track" />
            <div
              className="trim-selection"
              style={{left: `${startPct}%`, width: `${endPct - startPct}%`}}
            />
            <div className="trim-progress" style={{width: `${pct(playhead)}%`}} />
            {markers.map((at) => (
              <div key={at} className="trim-keyframe" style={{left: `${pct(at)}%`}} />
            ))}
            {highlights.map((h) => (
              <div
                key={h.id}
                className="trim-hl"
                style={{left: `${pct(h.time)}%`, background: h.color || '#f59e0b'}}
                title={h.label}
              />
            ))}
            <div className="trim-playhead" style={{left: `${pct(playhead)}%`}} />
            <button
              type="button"
              className="trim-handle"
              data-dragging={dragging === 'start' || undefined}
              style={{left: `${startPct}%`}}
              aria-label={t('trim.startOfSelection')}
              role="slider"
              aria-valuemin={0}
              aria-valuemax={Math.max(0, selection.end - Math.min(MIN_SELECTION, total))}
              aria-valuenow={selection.start}
              aria-valuetext={timecode(selection.start)}
              disabled={saving || !total}
              onKeyDown={(event) => boundaryKey(event, 'start')}
              onPointerDown={(event) => beginGesture(event, 'start')}
            />
            <button
              type="button"
              className="trim-handle"
              data-dragging={dragging === 'end' || undefined}
              style={{left: `${endPct}%`}}
              aria-label={t('trim.endOfSelection')}
              role="slider"
              aria-valuemin={Math.min(total, selection.start + Math.min(MIN_SELECTION, total))}
              aria-valuemax={total}
              aria-valuenow={selection.end}
              aria-valuetext={timecode(selection.end)}
              disabled={saving || !total}
              onKeyDown={(event) => boundaryKey(event, 'end')}
              onPointerDown={(event) => beginGesture(event, 'end')}
            />
          </div>

          <p className="trim-timeline-hint">{t('trim.timelineHint')}</p>
          <details className="trim-keyframe-info playback-shortcuts">
            <summary>{t('playback.shortcuts')}</summary>
            <p>{t('playback.shortcutHelp')}</p><p>{t('trim.shortcutHelp')}</p>
          </details>
          <div className="trim-tc mono">
            <span>{t('trim.in')} {timecode(selection.start)}</span>
            <span>{t('trim.out')} {timecode(selection.end)}</span>
          </div>
          <div className="trim-keyframe-actions">
            <label className="trim-keyframe-toggle">
              <input
                type="checkbox"
                checked={showKeyframes}
                disabled={!keyframes?.timestamps.length || saving}
                onChange={(event) => setShowKeyframes(event.target.checked)}
              />
              {t('trim.showKeyframes')}
            </label>
            <button
              type="button"
              className="btn btn-quiet btn-sm"
              onClick={manualSnap}
              disabled={!keyframes || !total || saving}>
              {t('trim.snapKeyframes')}
            </button>
            {keyframes && total ? (
              <span className="trim-alignment">
                {[selection.start, selection.end].every((at) => {
                  const key = nearestKeyframe(keyframes.timestamps, at);
                  return key !== null && Math.abs(key - at) < 0.001;
                })
                  ? t('trim.keyframeAligned')
                  : t('trim.notKeyframeAligned')}
              </span>
            ) : null}
          </div>
          <div className="trim-keyframe-message" role="status">
            {analyzing ? t('trim.analyzingKeyframes') : (analysisError ?? snapMessage)}
          </div>
          <details className="trim-keyframe-info" key={clip.video_url}>
            <summary>{t('trim.keyframeInformation')}</summary>
            {keyframes ? (
              <dl>
                <div>
                  <dt>{t('trim.totalKeyframes')}</dt>
                  <dd>{formatNumber(keyframes.total_keyframes)}</dd>
                </div>
                <div>
                  <dt>{t('trim.totalFrames')}</dt>
                  <dd>
                    {keyframes.total_frames === null
                      ? t('trim.unknown')
                      : `${formatNumber(keyframes.total_frames)}${keyframes.frames_estimated ? ` (${t('trim.estimated')})` : ''}`}
                  </dd>
                </div>
                <div>
                  <dt>{t('trim.keyframeRatio')}</dt>
                  <dd>
                    {keyframes.total_frames && keyframes.total_keyframes
                      ? t('trim.ratioValue', {
                          frames: formatNumber(keyframes.total_frames / keyframes.total_keyframes, 1),
                          percent: formatNumber(keyframes.total_keyframes / keyframes.total_frames * 100, 2),
                        }) + (keyframes.frames_estimated ? ` (${t('trim.estimated')})` : '')
                      : t('trim.unknown')}
                  </dd>
                </div>
                <div>
                  <dt>{t('trim.averageInterval')}</dt>
                  <dd>
                    {keyframes.average_interval === null
                      ? t('trim.unknown')
                      : t('trim.intervalSeconds', {seconds: formatNumber(keyframes.average_interval, 3)})}
                  </dd>
                </div>
                <div>
                  <dt>{t('trim.intervalRange')}</dt>
                  <dd>
                    {keyframes.min_interval === null || keyframes.max_interval === null
                      ? t('trim.unknown')
                      : `${formatNumber(keyframes.min_interval, 3)}–${formatNumber(keyframes.max_interval, 3)} s`}
                  </dd>
                </div>
                <div>
                  <dt>{t('trim.frameRate')}</dt>
                  <dd>
                    {t('trim.fpsValue', {
                      average: keyframes.average_fps === null ? t('trim.unknown') : formatNumber(keyframes.average_fps, 3),
                      nominal: keyframes.nominal_fps === null ? t('trim.unknown') : formatNumber(keyframes.nominal_fps, 3),
                    })}
                  </dd>
                </div>
              </dl>
            ) : (
              <p>{analyzing ? t('trim.analyzingKeyframes') : analysisError}</p>
            )}
            <p>{t('trim.keyframeHelp')}</p>
          </details>
        </div>

        <div className="modal-foot trim-foot">
          <button
            type="button"
            className={previewing ? 'btn btn-sm' : 'btn btn-quiet btn-sm'}
            onClick={togglePreview}
            disabled={!total}>
            {previewing ? t('trim.stop') : t('trim.preview')}
          </button>
          <span className="trim-status" data-warning={(!error && confirmReplace) || undefined}>
            {error ?? (confirmReplace ? t('trim.replaceWarning') : t('trim.loopHelp'))}
          </span>
          <button type="button" className="btn btn-quiet btn-sm" onClick={close}>
            {t('common.cancel')}
          </button>
          <button
            type="button"
            className={confirmReplace ? 'btn btn-danger-solid btn-sm' : 'btn btn-quiet btn-sm'}
            onClick={() => (confirmReplace ? void save(false) : setConfirmReplace(true))}
            onBlur={() => setConfirmReplace(false)}
            disabled={saving || !total}>
            {confirmReplace ? t('trim.replaceConfirm') : t('trim.replaceOriginal')}
          </button>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void save(true)}
            disabled={saving || !total}>
            {saving ? t('trim.saving') : t('trim.saveCopy')}
          </button>
        </div>
      </div>
    </div>
  );
}
