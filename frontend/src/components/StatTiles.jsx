import React from "react";

/* The indicators on top of a settings page (Organizzazione, Team): a row of numbers, each with its label and, when it
   has a limit, how much of it is used (the bar turns yellow when full). */
export function StatTiles({ children, testid }) {
  return <div className="grid grid-cols-3 gap-2 min-[380px]:gap-3" data-testid={testid}>{children}</div>;
}

export function StatTile({ label, value, max, testid }) {
  const limited = max != null;
  const full = limited && value >= max;
  return (
    <div className="min-w-0" data-testid={testid}>
      <div className="text-[10px] min-[380px]:text-[11px] text-white/60 leading-tight truncate">{label}</div>
      <div className="mt-1.5 text-xl font-semibold text-white leading-none">
        {value}{limited && <span className="text-white/45 text-sm font-normal"> / {max}</span>}
      </div>
      {limited && (
        <div className="mt-2 h-1 rounded-full bg-white/10 overflow-hidden">
          <div className="h-full rounded-full" style={{ width: `${Math.min(100, (value / Math.max(1, max)) * 100)}%`, background: full ? "#F2C14E" : "rgba(255,255,255,0.7)" }} />
        </div>
      )}
    </div>
  );
}
