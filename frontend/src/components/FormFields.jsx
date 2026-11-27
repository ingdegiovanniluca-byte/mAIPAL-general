import React from "react";
import { ChevronDown } from "lucide-react";

/* The app's form pieces (QR, Profilo): the label above, the field with its icon on the left, the dropdowns (the
   phone's own picker) with their chevron, wide buttons. */
export const INPUT = "h-11 w-full min-w-0 rounded-xl bg-white/10 border border-white/15 text-sm text-white placeholder:text-white/40 outline-none focus:border-white/45 focus:bg-white/[0.14] transition-colors";

export function Field({ label, hint, children, testid, className = "" }) {
  return (
    <div className={`flex flex-col gap-1.5 min-w-0 ${className}`} data-testid={testid}>
      {label && <span className="text-[12px] font-medium text-white/85">{label}</span>}
      {children}
      {hint && <span className="text-[11px] text-white/55 leading-snug">{hint}</span>}
    </div>
  );
}

export function Input({ icon: Icon, className = "", ...p }) {
  // (a padding given in className replaces the default one: two of them would fight in the stylesheet)
  const own = (side) => new RegExp(`(^|\\s)(p${side}|px)-`).test(className);
  const pad = `${Icon ? "pl-10" : own("l") ? "" : "pl-3.5"} ${own("r") ? "" : "pr-3.5"}`;
  return (
    <div className="relative min-w-0">
      {Icon && <Icon size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-white/50 pointer-events-none" />}
      <input {...p} className={`${INPUT} ${pad} ${className}`} />
    </div>
  );
}

// a native dropdown (the phone's own picker): options [[value, label]], value given back with its own type
export function Select({ icon: Icon, value, onChange, options, testid, placeholder }) {
  return (
    <div className="relative min-w-0">
      {Icon && <Icon size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-white/50 pointer-events-none" />}
      <select value={String(value ?? "")} data-testid={testid}
        onChange={(e) => { const o = options.find(([k]) => String(k) === e.target.value); onChange(o ? o[0] : e.target.value); }}
        className={`${INPUT} appearance-none truncate ${Icon ? "pl-10" : "pl-3.5"} pr-10 cursor-pointer`}>
        {placeholder != null && <option value="" disabled hidden className="text-black">{placeholder}</option>}
        {options.map(([k, label]) => <option key={k} value={String(k)} className="text-black">{label}</option>)}
      </select>
      <ChevronDown size={16} className="absolute right-3.5 top-1/2 -translate-y-1/2 text-white/60 pointer-events-none" />
    </div>
  );
}

export const PRIMARY = "h-11 rounded-xl text-sm font-semibold bg-white/90 text-[#7A2A5C] disabled:opacity-60 inline-flex items-center justify-center gap-1.5";
export const SECONDARY = "h-11 rounded-xl text-sm font-medium bg-white/10 border border-white/15 text-white/90 disabled:opacity-60 inline-flex items-center justify-center gap-1.5";
// the same, for what removes or unlinks something (red text: never two text colors on one button)
export const DANGER = SECONDARY.replace("text-white/90", "text-red-300");
// a small square button (in a row of a list: remove, copy...) and a button inside a field, on its right
export const ICON_BTN = "h-9 w-9 shrink-0 rounded-lg bg-white/10 border border-white/15 flex items-center justify-center text-white/75 disabled:opacity-50";
export const INLINE_BTN = "absolute right-1.5 top-1/2 -translate-y-1/2 h-8 px-3 rounded-lg bg-white/85 text-[#7A2A5C] text-xs font-semibold disabled:opacity-50 inline-flex items-center gap-1";
// the small title above a card (the Profilo's sections)
export function GroupTitle({ children, testid }) {
  return <div className="text-[13px] font-semibold text-white mb-2 mt-1" data-testid={testid}>{children}</div>;
}
