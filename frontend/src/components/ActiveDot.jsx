import React from "react";
import { Check } from "lucide-react";

/* The lists' selection dot (Liste, Spesa...), used to turn something on and off: lit with the check when it is on,
   a faint circle when it is off (Azioni: active / paused; QR: active / turned off). */
export default function ActiveDot({ on, busy, onToggle, testid, onTitle, offTitle, onLabel, offLabel }) {
  return (
    <button type="button" data-testid={testid} disabled={busy} aria-pressed={!!on}
      onClick={(e) => { e.stopPropagation(); onToggle(!on); }}
      title={on ? onTitle : offTitle} aria-label={on ? onLabel : offLabel}
      className="h-8 w-8 -m-1.5 shrink-0 flex items-center justify-center disabled:opacity-60">
      <span className={`h-5 w-5 rounded-full flex items-center justify-center backdrop-blur-md transition-colors ${on ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
        {on && <Check size={12} strokeWidth={2.8} />}
      </span>
    </button>
  );
}
