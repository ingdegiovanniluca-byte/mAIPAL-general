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
    // One empty line (as tall as a suggestion line: 15px x 1.375) above, below the header
    // (-mt-4 cancels the page's own top padding), and one below, before the actions menu.
    <div className="-mx-4 -mt-4 pt-[21px] mb-[21px]" data-testid="suggestions">
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
            className="snap-start shrink-0 w-full px-4 text-left"
          >
            <span className="block text-[15px] leading-snug text-white/90 line-clamp-2 min-h-[2.6em]">{s.text}</span>
          </button>
        ))}
      </div>
      {items.length > 1 && (
        <div className="flex items-center gap-1 px-4 mt-2" aria-hidden="true">
          {items.map((s, i) => (
            <span key={s.id} className={`h-1 rounded-full transition-all duration-300 ${i === idx ? "w-4 bg-white/80" : "w-1 bg-white/30"}`} />
          ))}
        </div>
      )}
    </div>
  );
}
