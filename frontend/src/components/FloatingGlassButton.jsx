import React, { useEffect, useRef, useState } from "react";

/* A round glass button (the bottom menu's "+" glass, a bit smaller) floating on the right at
   3/4 of the screen's height, over the page that scrolls under it. It slides away while the
   page scrolls and comes back when it stops (one passive listener and a timer: the state
   changes only twice per scroll); with `hideWhileTyping` also while a text field has focus.
   `hidden` hides it from outside (e.g. text already written in the box). */
/* `dock`: down where the bottom menu's round "+" is on the other pages (same size, same place), standing still. */
const PLUS = 64, GAP = 12;
const plusRight = () => {   // the "+" sits right of the menu's pill (4 sections), the two centred together
  const el = typeof document !== "undefined" && document.querySelector('[data-testid="tab-more"]');
  const r = el && el.getBoundingClientRect();
  if (r && r.width) return Math.round(window.innerWidth - r.right);
  const w = window.innerWidth;
  const pill = 4 * (w >= 380 ? 66 : 58) + 10;
  return Math.max(8, Math.round((w - (pill + GAP + PLUS)) / 2));
};

export default function FloatingGlassButton({ icon: Icon, label, onClick, testid, active = false, hidden = false, hideWhileTyping = false, dock = false }) {
  const [scrolling, setScrolling] = useState(false);
  const [right, setRight] = useState(() => (dock && typeof window !== "undefined" ? plusRight() : null));
  useEffect(() => {
    if (!dock) return undefined;
    const on = () => setRight(plusRight());
    on();
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, [dock]);
  const [typing, setTyping] = useState(false);
  const scrollingRef = useRef(false);
  const btnRef = useRef(null);

  useEffect(() => {
    let timer = null;
    // the page scrolling, or (desktop split) the column it is in - not the other column
    const onScroll = (e) => {
      const t = e.target;
      if (t && t !== document && t.nodeType === 1 && !t.contains(btnRef.current)) return;
      if (!scrollingRef.current) { scrollingRef.current = true; setScrolling(true); }
      clearTimeout(timer);
      timer = setTimeout(() => { scrollingRef.current = false; setScrolling(false); }, 450);
    };
    if (dock) return undefined;   // (down in the menu's place it stays put)
    document.addEventListener("scroll", onScroll, { passive: true, capture: true });
    return () => { document.removeEventListener("scroll", onScroll, { capture: true }); clearTimeout(timer); };
  }, [dock]);

  useEffect(() => {
    if (!hideWhileTyping) return undefined;
    const isField = (el) => el && (el.tagName === "TEXTAREA" || el.isContentEditable
      || (el.tagName === "INPUT" && !["checkbox", "radio", "button", "submit", "range", "file"].includes(el.type)));
    const onIn = (e) => { if (isField(e.target)) setTyping(true); };
    const onOut = (e) => { if (isField(e.target)) setTyping(false); };
    document.addEventListener("focusin", onIn);
    document.addEventListener("focusout", onOut);
    return () => { document.removeEventListener("focusin", onIn); document.removeEventListener("focusout", onOut); };
  }, [hideWhileTyping]);

  const away = hidden || scrolling || typing;
  return (
    <button ref={btnRef} type="button" onClick={onClick} data-testid={testid} data-hidden={away ? "1" : "0"} aria-pressed={active}
      title={label} aria-label={label} tabIndex={away ? -1 : 0}
      className={dock ? "fixed z-[45] h-16 w-16 rounded-full flex items-center justify-center text-white active:scale-95"
        : "fixed z-40 right-3.5 md:right-8 h-[52px] w-[52px] rounded-full flex items-center justify-center text-white active:scale-95"}
      style={{
        ...(dock ? { bottom: "calc(env(safe-area-inset-bottom, 0px) + 14px)", right: `${right ?? 20}px` } : { top: "calc(75vh - 26px)" }),
        transform: away ? "translateX(calc(100% + 24px))" : "none",
        opacity: away ? 0 : 1,
        pointerEvents: away ? "none" : "auto",
        transition: "transform 260ms ease, opacity 200ms ease",
      }}>
      <span aria-hidden="true" className="lg-goo absolute inset-0 rounded-full" style={{ boxShadow: "0 10px 22px rgba(60, 10, 40, 0.16)" }} />
      {active && <span aria-hidden="true" className="lg-bubble absolute inset-[5px] rounded-full" />}
      <Icon size={dock ? 23 : 21} strokeWidth={1.9} className="relative" />
    </button>
  );
}
