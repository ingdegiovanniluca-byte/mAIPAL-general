import React, { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

// "Per te" suggestions above the mobile chat: just text, no box. Swipe sideways to move
// between them; they also advance by themselves every few seconds (paused while touched).
// A tap runs the suggestion's target through `onSelect`.
export default function SuggestionsTicker({ onSelect }) {
  const [items, setItems] = useState([]);
  const [idx, setIdx] = useState(0);
  const scrollerRef = useRef(null);
  const idxRef = useRef(0);
  const pausedUntil = useRef(0);

  useEffect(() => {
    let alive = true;
    api.get("/suggestions").then((r) => { if (alive) setItems(r.data?.items || []); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (items.length < 2) return undefined;
    const t = setInterval(() => {
      const el = scrollerRef.current;
      if (!el || Date.now() < pausedUntil.current) return;
      const next = (idxRef.current + 1) % items.length;
      el.scrollTo({ left: next * el.clientWidth, behavior: "smooth" });
    }, 6000);
    return () => clearInterval(t);
  }, [items]);

  const onScroll = () => {
    const el = scrollerRef.current;
    if (!el || !el.clientWidth) return;
    const i = Math.round(el.scrollLeft / el.clientWidth);
    if (i !== idxRef.current) { idxRef.current = i; setIdx(i); }
  };
  const pause = () => { pausedUntil.current = Date.now() + 10000; };

  if (!items.length) return null;
  return (
    // Centered like the agent's name below it, well apart from the header (-mt-4 cancels
    // the page's own top padding).
    <div className="-mx-4 -mt-4 pt-9 mb-2" data-testid="suggestions">
      <div
        ref={scrollerRef}
        onScroll={onScroll}
        onPointerDown={pause}
        onTouchStart={pause}
        className="flex overflow-x-auto snap-x snap-mandatory no-scrollbar"
      >
        {items.map((s) => (
          <button
            key={s.id}
            data-testid={`suggestion-${s.id}`}
            onClick={() => onSelect(s)}
            className="snap-start shrink-0 w-full px-5 text-center"
          >
            <span className="block text-[20px] leading-snug font-medium text-white line-clamp-2 min-h-[2.75em] [text-shadow:0_1px_8px_rgba(0,0,0,0.25)]">{s.text}</span>
          </button>
        ))}
      </div>
      {items.length > 1 && (
        <div className="flex items-center justify-center gap-1 px-4 mt-2" aria-hidden="true">
          {items.map((s, i) => (
            <span key={s.id} className={`h-1 rounded-full transition-all duration-300 ${i === idx ? "w-4 bg-white/80" : "w-1 bg-white/30"}`} />
          ))}
        </div>
      )}
    </div>
  );
}
