import React from "react";

/* One figure of a row of information that scrolls sideways (the commessa's diary, Documenti):
   a small icon, the label in small capitals, the value and an optional note; a button or a link
   when it does something. A wide one (who is on site) keeps its value whole and cuts the note. */
export default function InfoCard({ icon: Icon, label, value, note, onClick, href, testid, ariaLabel, external, wide = false }) {
  const cls = `snap-start shrink-0 min-w-[92px] ${wide ? "max-w-[290px]" : "max-w-[190px]"} py-1 flex items-start gap-1.5 text-left text-white`
    + (onClick || href ? " active:opacity-70" : "");
  const body = (
    <>
      <Icon size={14} className="text-white/55 shrink-0" />
      <span className="flex flex-col gap-1.5 min-w-0">
        <span className="text-[10px] leading-[14px] uppercase tracking-widest text-white/50 truncate" data-testid="info-label">{label}</span>
        <span className="flex items-baseline gap-1.5 min-w-0" data-testid="info-value">
          <span className={`text-[15px] font-medium text-white/90 ${wide ? "whitespace-nowrap" : "truncate"}`}>{value}</span>
          {note && <span className={`text-[11px] text-white/55 ${wide ? "truncate min-w-0" : "whitespace-nowrap"}`}>{note}</span>}
        </span>
      </span>
    </>
  );
  if (href) return <a href={href} target={external ? "_blank" : undefined} rel={external ? "noreferrer" : undefined} data-testid={testid} aria-label={ariaLabel} className={cls}>{body}</a>;
  if (onClick) return <button type="button" onClick={onClick} data-testid={testid} aria-label={ariaLabel} className={cls}>{body}</button>;
  return <div data-testid={testid} aria-label={ariaLabel} className={cls}>{body}</div>;
}
