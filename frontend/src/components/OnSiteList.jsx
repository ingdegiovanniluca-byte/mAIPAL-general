import React from "react";
import { groupOnSite } from "@/lib/onSite";

/* Everyone on site now, under their role (Elettricisti, Idraulici…): name, since when, the
   company. The diary's "In cantiere ora" and the map's card show it. */

const hhmm = (iso) => { try { return new Date(iso).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" }); } catch { return ""; } };

export default function OnSiteList({ people = [], compact = false }) {
  const groups = groupOnSite(people);
  const heads = !(groups.length === 1 && groups[0].key === "~other");   // nobody with a role: just the names
  return (
    <div className={compact ? "space-y-1.5" : "space-y-3"} data-testid="on-site-list">
      {groups.map((g) => (
        <div key={g.key} data-testid="on-site-group">
          {heads && (
            <div className={`${compact ? "text-[9.5px]" : "text-[10px]"} uppercase tracking-widest text-white/50`} data-testid="on-site-role">
              {g.label} · {g.people.length}
            </div>
          )}
          {g.people.map((p, i) => (
            <div key={`${p.name}-${i}`} className={`flex flex-wrap items-baseline gap-x-1.5 min-w-0 ${compact ? "text-[11.5px] leading-snug" : "text-[14px] leading-6"} text-white`} data-testid="on-site-person">
              <span className="min-w-0 break-words font-medium">{p.name}</span>
              <span className={`${compact ? "text-[10.5px]" : "text-[12px]"} text-white/60`}>
                dalle {hhmm(p.since)}{p.company ? ` · ${p.company}` : ""}{p.far ? " · ⚠️ lontano" : ""}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
