import {useEffect, useLayoutEffect, useRef, type ReactNode} from 'react';

import {useEscape} from '../lib/escape';
import {useExitTransition} from '../lib/exit';
import {IconClose} from './Icons';

/**
 * A dialog with a scrim. Escape closes, focus moves in on open and returns to
 * whatever opened it on close.
 */
export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  wide,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const returnFocusTo = useRef<Element | null>(null);

  useEscape(open, onClose);
  // Held open for the length of the exit so it animates away rather than
  // disappearing between frames. Matches --duration-medium.
  const {mounted, closing} = useExitTransition(open, 320);

  useEffect(() => {
    if (!open) return;
    returnFocusTo.current = document.activeElement;
    // Preserve a child's autofocus (InlineRename commits on blur).
    if (!boxRef.current?.contains(document.activeElement)) boxRef.current?.focus();
    return () => {
      (returnFocusTo.current as HTMLElement | null)?.focus?.();
    };
  }, [open]);

  // A title that changes while the dialog is open fades in rather than
  // cutting. Only a paged dialog does that, and there the heading changing
  // under a still body is the part that reads as a glitch.
  const lastTitle = useRef(title);
  useLayoutEffect(() => {
    if (lastTitle.current === title) return;
    lastTitle.current = title;
    titleRef.current?.animate?.(
      [
        {opacity: 0, transform: 'translateY(-5px)'},
        {opacity: 1, transform: 'none'},
      ],
      {duration: 220, easing: 'cubic-bezier(0.2, 0, 0, 1)'},
    );
  }, [title]);

  if (!mounted) return null;

  return (
    <div
      className="scrim"
      data-closing={closing || undefined}
      onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div
        className="modal"
        data-closing={closing || undefined}
        data-wide={wide || undefined}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={boxRef}>
        <div className="modal-head">
          <h2 ref={titleRef}>{title}</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            <IconClose size={15} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-foot">{footer}</div> : null}
      </div>
    </div>
  );
}
