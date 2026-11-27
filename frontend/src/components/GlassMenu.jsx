import React, { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/* Frosted-glass dropdown (the user menu): rows of icon + label split by thin inset lines.
   Portaled to <body> and placed under `anchorRef`, right-aligned: inside the header (itself
   frosted with backdrop-filter) the panel's blur could only see the header, not the page
   colours behind it. `panelRef` lets the caller treat clicks inside as "inside the menu". */
export default function GlassMenu({ anchorRef, panelRef, testid, width = 240, children }) {
  const [pos, setPos] = useState(null);
  const own = useRef(null);
  useLayoutEffect(() => {
    // under the anchor; above it when it wouldn't fit under (a row at the bottom of the screen)
    const place = () => {
      const r = anchorRef.current?.getBoundingClientRect();
      if (!r) return;
      const h = own.current?.offsetHeight || 0;
      const below = r.bottom + 10;
      const top = h && below + h > window.innerHeight - 12 && r.top - 10 - h > 12 ? r.top - 10 - h : below;
      setPos({ top, right: Math.max(12, window.innerWidth - r.right), up: top < r.top });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [anchorRef]);
  useLayoutEffect(() => {   // once it is drawn and its height known: placed again (maybe above)
    const r = anchorRef.current?.getBoundingClientRect();
    const h = own.current?.offsetHeight || 0;
    if (r && h && !pos?.up && r.bottom + 10 + h > window.innerHeight - 12 && r.top - 10 - h > 12) {
      setPos({ top: r.top - 10 - h, right: Math.max(12, window.innerWidth - r.right), up: true });
    }
  }, [pos, anchorRef]);
  if (!pos) return null;
  return createPortal(
    <div
      ref={(el) => { own.current = el; if (panelRef) panelRef.current = el; }}
      data-testid={testid}
      role="menu"
      className={`glass-panel fixed z-[60] py-1 animate-in fade-in zoom-in-95 duration-150 ${pos.up ? "origin-bottom-right" : "origin-top-right"}`}
      style={{ top: pos.top, right: pos.right, width }}
    >
      {children}
    </div>,
    document.body,
  );
}

export function GlassMenuItem({ icon: Icon, label, onClick, testid, danger = false, disabled = false }) {
  return (
    <button type="button" data-testid={testid} onClick={onClick} role="menuitem" disabled={disabled}
      className={`glass-row w-full flex items-center gap-3.5 px-5 py-3.5 text-left text-[15px] hover:bg-white/10 transition-colors disabled:opacity-50 ${danger ? "text-red-300" : "text-white"}`}>
      <Icon size={19} strokeWidth={1.7} className="shrink-0" />
      <span className="min-w-0">{label}</span>
    </button>
  );
}
