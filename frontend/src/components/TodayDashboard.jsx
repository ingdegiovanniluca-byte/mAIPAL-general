import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronRight, User, HardHat, AlertTriangle, Pause, Check } from "lucide-react";
import { api } from "@/lib/api";
import GlassBottomSheet from "@/components/GlassBottomSheet";

/* Diario · Oggi (artigiano, phone): one screen that doesn't scroll - the clock with today's tasks
   and activities around it, who is on site now, the commesse of today (one line each: a dot green /
   yellow / red for the people there against the planned ones, the people, the open problems) and
   the notes of the day. The last two boxes scroll inside themselves. A commessa opens its diary. */

const STATUS_DOT = { green: "#8ED973", yellow: "#F2C14E", red: "#FF6B5B" };
const CHIP = { attivita: ["#F2C14E", "#3a2a2a"], task: ["#8FD3F4", "#1f3340"], main: ["#E7A3D8", "#3d2238"] };
const hhmm = (iso) => new Date(iso).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });

// the clock: a 12 h glass face; the timed items as arcs on their hour (the bottom ones drawn so they
// read upright), the ones too close merged ("+1"), the done ones a green tick, the past ones fainter
const CX = 110, CY = 108, R = 84, SPAN = 23;
const pt = (deg) => { const r = (deg * Math.PI) / 180; return [CX + R * Math.sin(r), CY - R * Math.cos(r)]; };
const angleOf = (t) => { const [h, m] = t.split(":").map(Number); return (((h % 12) * 60 + m) / 720) * 360; };
function Clock({ items, now }) {
  const timed = items.filter((x) => x.time).map((x) => ({ ...x, a: angleOf(x.time) })).sort((x, y) => x.a - y.a);
  const groups = [];
  for (const x of timed) {
    const g = groups.find((gg) => Math.min(Math.abs(gg.a - x.a), 360 - Math.abs(gg.a - x.a)) < SPAN * 2);
    if (g) g.more.push(x); else groups.push({ ...x, more: [] });
  }
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const hA = ((now.getHours() % 12) * 60 + now.getMinutes()) / 2, mA = now.getMinutes() * 6;
  const hand = (deg, len) => { const r = (deg * Math.PI) / 180; return [CX + len * Math.sin(r), CY - len * Math.cos(r)]; };
  const [hx, hy] = hand(hA, 26), [mx, my] = hand(mA, 40);
  return (
    <svg viewBox="0 0 220 206" className="w-full h-full block" data-testid="today-clock" aria-label="Orologio con i task di oggi">
      {groups.map((g, i) => {
        if (g.done && !g.more.length) {
          const [x, y] = pt(g.a);
          return (
            <g key={g.id}><circle cx={x} cy={y} r="9" fill="#8ED973" /><path d={`M ${x - 4} ${y} L ${x - 1} ${y + 3} L ${x + 4} ${y - 3}`} stroke="#1d3b16" strokeWidth="2" fill="none" strokeLinecap="round" /></g>
          );
        }
        const bottom = g.a > 90 && g.a < 270;
        const [s0, s1] = bottom ? [g.a + SPAN, g.a - SPAN] : [g.a - SPAN, g.a + SPAN];
        const [x0, y0] = pt(s0), [x1, y1] = pt(s1);
        const [bg, fg] = CHIP[g.kind === "task" && g.main ? "main" : g.kind] || CHIP.task;
        const [h, m] = g.time.split(":").map(Number);
        const past = h * 60 + m < nowMin - 30;
        const word = (g.label || "").split(/\s+/)[0] || "";
        const label = `${g.time} ${word.length > 9 ? `${word.slice(0, 8)}…` : word}` + (g.more.length ? ` +${g.more.length}` : "");
        return (
          <g key={g.id} opacity={past ? 0.5 : 1}>
            <path id={`chip-${i}`} d={`M ${x0} ${y0} A ${R} ${R} 0 0 ${bottom ? 0 : 1} ${x1} ${y1}`} stroke={bg} strokeWidth="18" fill="none" strokeLinecap="round" />
            <text fontSize="8.4" fontWeight="600" fill={fg} dominantBaseline="middle">
              <textPath href={`#chip-${i}`} startOffset="50%" textAnchor="middle">{label}</textPath>
            </text>
          </g>
        );
      })}
      <circle cx={CX} cy={CY} r="66" fill="rgba(255,255,255,0.16)" stroke="rgba(255,255,255,0.35)" strokeWidth="1" />
      {[0, 90, 180, 270].map((d) => { const [a, b] = hand(d, 63), [c, e] = hand(d, 58); return <line key={d} x1={a} y1={b} x2={c} y2={e} stroke="rgba(255,255,255,0.85)" strokeWidth="2" strokeLinecap="round" />; })}
      {Array.from({ length: 12 }, (_, i) => { const [x, y] = hand((i || 12) * 30, 48); return <text key={i} x={x} y={y + 4} fontSize="11.5" fontWeight="500" fill="rgba(255,255,255,0.92)" textAnchor="middle">{i || 12}</text>; })}
      <line x1={CX} y1={CY} x2={hx} y2={hy} stroke="#fff" strokeWidth="5" strokeLinecap="round" />
      <line x1={CX} y1={CY} x2={mx} y2={my} stroke="#fff" strokeWidth="3.5" strokeLinecap="round" />
      <circle cx={CX} cy={CY} r="4.5" fill="#fff" />
    </svg>
  );
}

const Kicker = ({ children }) => (
  <div className="text-[11.5px] font-semibold tracking-[0.14em] uppercase text-white" style={{ textShadow: "0 1px 6px rgba(60,20,50,.35)" }}>{children}</div>
);
const box = "rounded-[26px] lg-glass";
const fade = { WebkitMaskImage: "linear-gradient(180deg,#000 85%,transparent)", maskImage: "linear-gradient(180deg,#000 85%,transparent)" };

export default function TodayDashboard({ onOpenCommessa, onAll }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(false);
  const [now, setNow] = useState(new Date());
  const [sheet, setSheet] = useState(null);   // "clock" | "people"
  const wrap = useRef(null);
  const [h, setH] = useState(null);
  const load = () => api.get("/jobs/today").then((r) => { setD(r.data); setErr(false); }).catch(() => setErr(true));
  useEffect(() => {
    load();
    const t = setInterval(() => setNow(new Date()), 30000);
    const r = setInterval(load, 120000);
    return () => { clearInterval(t); clearInterval(r); };
  }, []);
  // the page fits the screen: from where it starts to above the bar at the bottom
  useLayoutEffect(() => {
    const fit = () => {   // down to the bar at the bottom (measured: phones differ), with a little air
      const top = wrap.current?.getBoundingClientRect().top || 0;
      const bar = document.querySelector('[data-testid="mobile-bottom-nav"]')?.getBoundingClientRect().top;
      const bottom = bar && bar > top ? bar - 10 : window.innerHeight - 104;
      setH(Math.max(430, bottom - top));
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);

  if (err) return <div className="text-center py-10 text-[14px] text-white/80">Non riesco a caricare la giornata. <button onClick={load} className="underline">Riprova</button></div>;
  if (!d) return <div ref={wrap} className="kicker text-center py-10">caricamento…</div>;
  const on = d.on_site;
  const n = d.notes;
  const timed = d.clock.filter((x) => x.time).length;
  const done = d.clock.filter((x) => x.done).length;
  const empty = !n.activities.length && !n.materials.length && !n.news.length && !n.tips.length;
  return (
    <div ref={wrap} className="flex flex-col gap-2.5" style={{ height: h || undefined }} data-testid="today-dashboard">
      <div className="grid grid-cols-[1.7fr_1fr] gap-2.5 shrink-0">
        {/* the tasks around the clock */}
        <button type="button" onClick={() => setSheet("clock")} className={`${box} p-3 pb-2 text-left flex flex-col`} data-testid="today-tasks">
          <Kicker>task di oggi</Kicker>
          <div className="mt-0.5 flex-1 min-h-0"><Clock items={d.clock} now={now} /></div>
          <div className="flex justify-between text-[10.5px] text-white/75 mt-0.5">
            <span>{d.clock.length} oggi{done ? ` · ${done} ${done === 1 ? "fatto" : "fatti"}` : ""}</span>
            {d.clock.length - timed > 0 && <span>+{d.clock.length - timed} senza ora</span>}
          </div>
        </button>
        {/* who is on site now */}
        <button type="button" onClick={() => on.total && setSheet("people")} className={`${box} p-3 text-left flex flex-col`} data-testid="today-onsite">
          <Kicker>in cantiere</Kicker>
          <div className="flex items-baseline gap-1.5 mt-2"><span className="text-[40px] font-semibold leading-[0.95] text-white">{on.total}</span>
            <span className="text-[11px] text-white/75">{on.total === 1 ? "persona" : "persone"}</span></div>
          <div className="text-[10.5px] text-white/70 mt-0.5">{on.sites ? `su ${on.sites} ${on.sites === 1 ? "cantiere" : "cantieri"}` : "nessun cantiere"}</div>
          {[["employees", "dipendenti", User, "#8FD3F4", "#1f3340"], ["collaborators", "collaboratori", HardHat, "#F2C14E", "#3a2a2a"]].map(([k, label, Icon, bg, fg]) => (
            <div key={k} className="mt-2 flex items-center gap-2 rounded-2xl bg-white/[0.12] px-2 py-1.5" data-testid={`today-${k}`}>
              <span className="h-[26px] w-[26px] shrink-0 rounded-full flex items-center justify-center" style={{ background: bg, color: fg }}><Icon size={14} strokeWidth={2.2} /></span>
              <span className="min-w-0"><span className="block text-[17px] font-semibold leading-tight text-white">{on[k]}</span>
                <span className="block text-[10px] text-white/75 leading-tight truncate">{label}</span></span>
            </div>
          ))}
          {on.paused > 0 && <div className="mt-auto pt-2 text-[10.5px] text-[#FFE3A1] flex items-center gap-1"><Pause size={10} fill="currentColor" /> {on.paused} in pausa</div>}
        </button>
      </div>

      {/* the commesse of today */}
      <div className={`${box} px-3.5 pt-3 pb-1 shrink-0`} data-testid="today-commesse">
        <div className="grid grid-cols-[14px_1fr_40px_22px_10px] gap-2 items-center pb-1.5 border-b border-white/[0.14]">
          <span />
          <span className="flex items-center gap-2 min-w-0"><Kicker>commesse oggi</Kicker>
            <button type="button" onClick={onAll} className="text-[11.5px] text-white/65 shrink-0" data-testid="today-all">tutte ›</button></span>
          <span className="flex justify-center text-white/65"><HardHat size={15} /></span>
          <span className="flex justify-center text-white/65"><AlertTriangle size={14} /></span>
          <span />
        </div>
        <div className="overflow-y-auto overscroll-contain pb-2" style={{ ...fade, maxHeight: h && h < 560 ? 96 : 132 }}>
          {d.commesse.length === 0 && <div className="py-3 text-[12.5px] text-white/70">Nessuna commessa prevista oggi e nessuno in cantiere.</div>}
          {d.commesse.map((c) => (
            <button key={c.id} type="button" onClick={() => onOpenCommessa(c.id)} data-testid="today-commessa"
              className="w-full grid grid-cols-[14px_1fr_40px_22px_10px] gap-2 items-center py-[7px] border-b border-white/[0.14] last:border-0 text-left active:opacity-70">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: STATUS_DOT[c.status], boxShadow: `0 0 0 3px ${STATUS_DOT[c.status]}38` }} data-status={c.status} />
              <span className="min-w-0 truncate text-[13px] text-white"><b className="font-semibold">{c.client}</b> · {c.title}</span>
              <span className="text-center text-[13px] text-white tabular-nums">{c.present}<span className="text-[11px] text-white/55">/{c.expected}</span></span>
              <span className="flex justify-center">{c.problems
                ? <AlertTriangle size={15} className="text-[#FF6B5B]" fill="#FF6B5B" stroke="#fff" strokeWidth={1.6} aria-label={`${c.problems} problemi aperti`} />
                : <span className="text-white/25">–</span>}</span>
              <ChevronRight size={13} className="text-white/55" />
            </button>
          ))}
        </div>
      </div>

      {/* the notes of the day */}
      <div className={`${box} px-3.5 pt-3 flex-1 min-h-[96px] flex flex-col`} data-testid="today-notes">
        <Kicker>note di oggi</Kicker>
        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain pb-4 mt-1" style={fade}>
          {empty && <div className="py-2 text-[12.5px] text-white/70">Niente di previsto oggi.</div>}
          {n.activities.length > 0 && <Part k="A" title="Attività previste">
            {n.activities.map((a, i) => (
              <div key={i} className={a.done ? "opacity-60" : ""}><b className="font-semibold">{a.commessa}</b> — {a.time ? `${a.time} ` : ""}{a.text}
                {a.who.length > 0 && <span className="text-white/65"> ({a.who.join(", ")})</span>}{a.done && " ✓"}</div>
            ))}
          </Part>}
          {n.materials.length > 0 && <Part k="B" title="Materiali da prendere">
            {n.materials.map((m, i) => <div key={i}>{m.text}<span className="text-white/65">{[m.who, m.commessa && `per ${m.commessa}`].filter(Boolean).length ? ` — ${[m.who, m.commessa && `per ${m.commessa}`].filter(Boolean).join(", ")}` : ""}{m.late ? " · in ritardo" : ""}</span></div>)}
          </Part>}
          {n.news.length > 0 && <Part k="C" title="News principali">
            {n.news.map((x, i) => <div key={i}>{x.url ? <a href={x.url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">{x.title}</a> : x.title}</div>)}
          </Part>}
          {n.tips.length > 0 && <Part k="D" title="Consigli">
            {n.tips.map((t, i) => (
              <button key={i} type="button" onClick={() => t.commessa_id && onOpenCommessa(t.commessa_id)} className="block w-full text-left text-[#FFE3A1]">💡 {t.text}</button>
            ))}
          </Part>}
        </div>
      </div>

      {sheet === "clock" && (
        <GlassBottomSheet onClose={() => setSheet(null)} testid="today-clock-sheet" className="max-h-[80vh]">
          <div className="text-lg font-semibold text-white mb-2">Oggi</div>
          {d.clock.length === 0 && <div className="text-[13px] text-white/70">Nessun task o attività per oggi.</div>}
          {d.clock.map((x) => (
            <button key={x.id} type="button" onClick={() => x.commessa_id && onOpenCommessa(x.commessa_id)}
              className="w-full flex items-center gap-3 py-2.5 border-t border-white/[0.14] text-left">
              <span className="w-12 text-[13px] tabular-nums text-white/80">{x.time || "—"}</span>
              <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: (CHIP[x.kind === "task" && x.main ? "main" : x.kind] || CHIP.task)[0] }} />
              <span className={`flex-1 min-w-0 text-[14px] text-white ${x.done ? "line-through opacity-60" : ""}`}>{x.title}
                {x.commessa && <span className="block text-[11.5px] text-white/60">{x.label} · {x.commessa}</span>}</span>
              {x.done && <Check size={15} className="text-[#8ED973]" />}
            </button>
          ))}
        </GlassBottomSheet>
      )}
      {sheet === "people" && (
        <GlassBottomSheet onClose={() => setSheet(null)} testid="today-people-sheet" className="max-h-[80vh]">
          <div className="text-lg font-semibold text-white mb-2">In cantiere ora · {on.total}</div>
          {on.people.map((p, i) => (
            <button key={i} type="button" onClick={() => onOpenCommessa(p.commessa_id)} className="w-full flex items-center gap-3 py-2.5 border-t border-white/[0.14] text-left">
              <span className="h-[26px] w-[26px] shrink-0 rounded-full flex items-center justify-center" style={{ background: p.employee ? "#8FD3F4" : "#F2C14E", color: "#2b2430" }}>
                {p.employee ? <User size={13} /> : <HardHat size={13} />}</span>
              <span className="flex-1 min-w-0"><span className="block text-[14px] text-white truncate">{p.name}{p.company ? <span className="text-white/55"> · {p.company}</span> : ""}</span>
                <span className="block text-[11.5px] text-white/60 truncate">{p.client} · {p.commessa} · dalle {hhmm(p.since)}{p.paused_at ? ` · in pausa dalle ${hhmm(p.paused_at)}` : ""}</span></span>
            </button>
          ))}
        </GlassBottomSheet>
      )}
    </div>
  );
}

function Part({ k, title, children }) {
  return (
    <div className="mt-2.5">
      <div className="flex items-center gap-2 text-[12.5px] font-semibold text-white">
        <span className="h-[18px] w-[18px] rounded-md bg-white/[0.18] text-[10.5px] flex items-center justify-center">{k}</span>{title}</div>
      <div className="pl-[26px] mt-1 space-y-1 text-[12.5px] leading-snug text-white/90">{children}</div>
    </div>
  );
}
