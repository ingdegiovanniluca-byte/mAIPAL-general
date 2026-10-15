import React, { useCallback, useEffect, useRef } from "react";
import { createPortal } from "react-dom";

/* The app's frosted sheet from the bottom (the "+" menu of the chat, the Help guide, the
   collaborators...). The bar on top closes it: pull it down (or, when the content is scrolled
   to the top, pull the sheet itself) and let go past a short distance or with a flick; a tap
   on the bar, the shade behind or Esc close it too. */
const CLOSE_AT = 110;       // px pulled down that close it on release
const FLICK = 0.6;          // px/ms: a fast flick closes it even when short

export default function GlassBottomSheet({ onClose, testid, className = "max-h-[84vh]", children }) {
  const panel = useRef(null);
  const bar = useRef(null);
  const drag = useRef(null);
  const closing = useRef(false);
  const moved = useRef(false);

  const setY = (y, animate) => {
    const el = panel.current;
    if (!el) return;
    el.style.transition = animate ? "translate 220ms cubic-bezier(.2,.8,.2,1)" : "none";
    el.style.translate = y ? `0 ${y}px` : "";
  };
  const dismiss = useCallback(() => {
    if (closing.current) return;
    closing.current = true;
    setY((panel.current?.offsetHeight || 400) + 40, true);
    setTimeout(onClose, 200);
  }, [onClose]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // start: from the bar always; from the content only when it is scrolled to the top
  const begin = (x, y, target) => {
    const el = panel.current;
    const fromBar = !!bar.current?.contains(target);
    if (!fromBar && (target.closest?.("textarea, input[type=range], [data-sheet-nodrag]") || el.scrollTop > 0)) return;
    drag.current = { x0: x, y0: y, t0: Date.now(), fromBar, active: false, dy: 0 };
    moved.current = false;
  };
  const move = (x, y) => {
    const d = drag.current;
    if (!d) return false;
    const dx = x - d.x0, dy = y - d.y0;
    if (!d.active) {
      if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return false;
      if (dy <= 0 || Math.abs(dx) > Math.abs(dy) || (!d.fromBar && panel.current.scrollTop > 0)) { drag.current = null; return false; }
      d.active = true;
      moved.current = true;
    }
    d.dy = Math.max(0, dy);
    setY(d.dy, false);
    return true;
  };
  const end = () => {
    const d = drag.current;
    drag.current = null;
    if (!d?.active) return;
    const speed = d.dy / Math.max(1, Date.now() - d.t0);
    if (d.dy > CLOSE_AT || (d.dy > 40 && speed > FLICK)) dismiss(); else setY(0, true);
  };

  // touch: native listeners, so the pull can stop the page from scrolling / refreshing
  useEffect(() => {
    const el = panel.current;
    const ts = (e) => { if (e.touches.length === 1) begin(e.touches[0].clientX, e.touches[0].clientY, e.target); };
    const tm = (e) => { if (drag.current && move(e.touches[0].clientX, e.touches[0].clientY) && e.cancelable) e.preventDefault(); };
    el.addEventListener("touchstart", ts, { passive: true });
    el.addEventListener("touchmove", tm, { passive: false });
    el.addEventListener("touchend", end);
    el.addEventListener("touchcancel", end);
    return () => {
      el.removeEventListener("touchstart", ts);
      el.removeEventListener("touchmove", tm);
      el.removeEventListener("touchend", end);
      el.removeEventListener("touchcancel", end);
    };
  }); // eslint-disable-line react-hooks/exhaustive-deps

  // mouse: drag the bar
  const onPointerDown = (e) => {
    if (e.pointerType !== "mouse") return;
    e.currentTarget.setPointerCapture(e.pointerId);
    begin(e.clientX, e.clientY, e.target);
  };
  const onPointerMove = (e) => { if (e.pointerType === "mouse") move(e.clientX, e.clientY); };
  const onPointerUp = (e) => { if (e.pointerType === "mouse") end(); };

  return createPortal(
    <div className="fixed inset-0 z-[70]" data-testid={testid}>
      <div className="absolute inset-0 bg-[#1A0820]/25 animate-in fade-in duration-200" onClick={onClose} />
      {/* a floating card of frosted glass, the page's colours melting through it */}
      <div ref={panel} className={`glass-panel glass-sheet absolute left-3 right-3 bottom-[calc(env(safe-area-inset-bottom,0px)+12px)] overflow-y-auto overflow-x-hidden overscroll-contain no-scrollbar px-5 pt-0 pb-6 animate-in slide-in-from-bottom duration-300 ${className}`}>
        <button ref={bar} type="button" aria-label="Chiudi" data-testid="sheet-handle"
          onClick={() => { if (!moved.current) dismiss(); moved.current = false; }}
          onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
          className="block w-[calc(100%+2.5rem)] -mx-5 pt-3 pb-4 cursor-grab active:cursor-grabbing touch-none">
          <span className="block w-10 h-1 rounded-full bg-white/35 mx-auto" />
        </button>
        {children}
      </div>
    </div>,
    document.body,
  );
}
