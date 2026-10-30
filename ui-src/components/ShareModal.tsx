import {useEffect, useRef, useState} from 'react';

import {attachVideoFile, prepareClipDrag} from '../lib/clipDrag';
import {useStore} from '../state/store';
import {api} from '../lib/api';
import {formatBytes, formatDuration} from '../lib/format';
import {clipTitle, type Clip} from '../lib/types';
import {Modal} from './Modal';
import {t} from '../lib/i18n';

interface DiscordCopy {
  path: string;
  filename: string;
  size: number;
}

/**
 * The share sheet, over the viewer.
 *
 * Two ways out of Vice, in the order people reach for them: the share link for
 * anywhere a URL goes, and the clip itself for Discord, which will not unfurl
 * a link to a machine it cannot reach.
 */
export function ShareModal({
  clip,
  onClose,
  onCopyLink,
}: {
  clip: Clip | null;
  onClose: () => void;
  onCopyLink: (clip: Clip) => void;
}) {
  const {state} = useStore();
  const [jobId, setJobId] = useState<string | null>(null);
  const [copy, setCopy] = useState<DiscordCopy | null>(null);
  const [failed, setFailed] = useState('');
  const slug = clip?.slug;

  // The file has to exist on disk before the drag starts: a dragstart handler
  // cannot wait for an encode, so it is built when the sheet opens.
  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    setJobId(null);
    setCopy(null);
    setFailed('');
    void api
      .prepareClip(slug)
      .then(result => {if (!cancelled) setJobId(result.job_id);})
      .catch((err: Error) => !cancelled && setFailed(err.message));
    return () => {
      cancelled = true;
    };
  }, [slug]);

  useEffect(() => {
    const job = state.jobs.find(job => job.id === jobId);
    if (job?.status === 'completed' && slug) {
      let current = true;
      void api.originalFile(slug, true).then(file => {if (current) setCopy(file);})
        .catch(error => {if (current) setFailed(error.message);});
      return () => {current = false;};
    } else if (job && ['failed', 'interrupted', 'cancelled'].includes(job.status)) setFailed(job.error || t('viewer.shareDragFailed'));
  }, [state.jobs, jobId, slug]);

  // Held through the closing animation, or the sheet would empty itself out
  // one frame before it fades.
  const last = useRef<Clip | null>(null);
  if (clip) last.current = clip;
  const shown = clip ?? last.current;
  if (!shown) return null;

  const link = shown.share_url;

  const onDragStart = (e: React.DragEvent) => {
    if (!copy) {
      e.preventDefault();
      return;
    }
    attachVideoFile(e, shown, copy.path);
  };

  return (
    <Modal open={clip !== null} title={t('viewer.shareTitle')} onClose={onClose}>
      <div className="share-sheet">
        <div className="share-link-row">
          <span className="share-label">{t('viewer.shareHighQuality')}</span>
          {link ? (
            <button
              type="button"
              className="share-link mono"
              title={t('viewer.shareCopyHint')}
              onClick={() => onCopyLink(shown)}>
              {link}
            </button>
          ) : (
            <p className="share-nolink">{t('viewer.shareNoLink')}</p>
          )}
        </div>

        <div
          className="share-drag"
          data-ready={copy ? true : undefined}
          draggable={Boolean(copy)}
          onPointerEnter={() => prepareClipDrag(shown)}
          onDragStart={onDragStart}>
          {shown.thumb_url ? (
            <img src={shown.thumb_url} alt={clipTitle(shown)} draggable={false} />
          ) : (
            <span className="share-drag-empty" aria-hidden="true" />
          )}
          {shown.duration ? (
            <span className="share-drag-time mono">{formatDuration(shown.duration)}</span>
          ) : null}
          {copy ? null : <span className="share-drag-veil">{t('viewer.sharePreparing')}</span>}
        </div>

        <div className="share-drag-copy">
          <b>{t('viewer.shareDragHeading')}</b>
          <span>
            {failed
              ? failed
              : copy
                ? `${t('viewer.shareDragHint')} · ${t('viewer.shareDiscordSize', {
                    size: formatBytes(copy.size),
                  })}`
                : t('viewer.sharePreparing')}
          </span>
        </div>
      </div>
    </Modal>
  );
}
