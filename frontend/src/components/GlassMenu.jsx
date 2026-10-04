import React, { useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";

/* Frosted-glass dropdown (the user menu): rows of icon + label split by thin inset lines.
   Portaled to <body> and placed under `anchorRef`, right-aligned: inside the header (itself
   frosted with backdrop-filter) the panel's blur could only see the header, not the page
   colours behind it. `panelRef` lets the caller treat clicks inside as "inside the menu". */
export default function GlassMenu({ anchorRef, panelRef, testid, width = 240, children }) {
  const [pos, setPos] = useState(null);
  useLayoutEffect(() => {
    const place = () => {
      const r = anchorRef.current?.getBoundingClientRect();
      if (r) setPos({ top: r.bottom + 10, right: Math.max(12, window.innerWidth - r.right) });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [anchorRef]);
  if (!pos) return null;
  return createPortal(
    <div
      ref={panelRef}
      data-testid={testid}
      className="glass-panel fixed z-[60] py-1 animate-in fade-in zoom-in-95 duration-150 origin-top-right"
      style={{ top: pos.top, right: pos.right, width }}
    >
      {children}
    </div>,
    document.body,
  );
}

export function GlassMenuItem({ icon: Icon, label, onClick, testid }) {
  return (
    <button type="button" data-testid={testid} onClick={onClick}
      className="glass-row w-full flex items-center gap-3.5 px-5 py-3.5 text-left text-[15px] text-white hover:bg-white/10 transition-colors">
      <Icon size={19} strokeWidth={1.7} className="shrink-0" />
      <span className="min-w-0">{label}</span>
    </button>
  );
}
