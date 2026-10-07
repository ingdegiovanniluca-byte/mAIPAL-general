import React, { useEffect, useRef, useState } from "react";

/* A round glass button (the bottom menu's "+" glass, a bit smaller) floating on the right at
   3/4 of the screen's height, over the page that scrolls under it. It slides away while the
   page scrolls and comes back when it stops (one passive listener and a timer: the state
   changes only twice per scroll); with `hideWhileTyping` also while a text field has focus.
   `hidden` hides it from outside (e.g. text already written in the box). */
export default function FloatingGlassButton({ icon: Icon, label, onClick, testid, active = false, hidden = false, hideWhileTyping = false }) {
  const [scrolling, setScrolling] = useState(false);
  const [typing, setTyping] = useState(false);
  const scrollingRef = useRef(false);

  useEffect(() => {
    let timer = null;
    const onScroll = () => {
      if (!scrollingRef.current) { scrollingRef.current = true; setScrolling(true); }
      clearTimeout(timer);
      timer = setTimeout(() => { scrollingRef.current = false; setScrolling(false); }, 450);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => { window.removeEventListener("scroll", onScroll); clearTimeout(timer); };
  }, []);

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
    <button type="button" onClick={onClick} data-testid={testid} data-hidden={away ? "1" : "0"} aria-pressed={active}
      title={label} aria-label={label} tabIndex={away ? -1 : 0}
      className="fixed z-40 right-3.5 md:right-8 h-[52px] w-[52px] rounded-full flex items-center justify-center text-white active:scale-95"
      style={{
        top: "calc(75vh - 26px)",
        transform: away ? "translateX(calc(100% + 24px))" : "none",
        opacity: away ? 0 : 1,
        pointerEvents: away ? "none" : "auto",
        transition: "transform 260ms ease, opacity 200ms ease",
      }}>
      <span aria-hidden="true" className="lg-goo absolute inset-0 rounded-full" style={{ boxShadow: "0 10px 22px rgba(60, 10, 40, 0.16)" }} />
      {active && <span aria-hidden="true" className="lg-bubble absolute inset-[5px] rounded-full" />}
      <Icon size={21} strokeWidth={1.9} className="relative" />
    </button>
  );
}
