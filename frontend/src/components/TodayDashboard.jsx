import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { User, HardHat, AlertTriangle, Pause, Check } from "lucide-react";
import { api } from "@/lib/api";
import GlassBottomSheet from "@/components/GlassBottomSheet";

/* Diario · Oggi (artigiano, phone): one screen that doesn't scroll - the clock with today's tasks
   and activities around it, who is on site now, the commesse of today (one line each: a dot green /
   yellow / red for the people there against the planned ones, the people, the open problems) and
   the notes of the day. The last two boxes scroll inside themselves. A commessa opens its diary. */

const STATUS_DOT = { green: "#8ED973", yellow: "#F2C14E", red: "#FF6B5B" };
// the colours of the drops of the mAIPAL logo: activities orange, tasks teal, high-priority tasks magenta
const CHIP = { attivita: ["#FFAC33", "#4a2600"], task: ["#007E9A", "#ffffff"], main: ["#FF0061", "#ffffff"] };
const hhmm = (iso) => new Date(iso).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });

// the clock: a 12 h glass face with the timed items around it, each an arc that starts at its start time
// and lasts as long as it really lasts (an hour when not known). The ones that overlap go on a
// second ring further out; when they don't fit on two rings, the first keeps the main one (or the
// first to start) and the second shows "+N", the ones of that period not on screen. Done ones are a
// green tick, the past ones fainter; the bottom ones are drawn so they read upright.
const CX = 100, CY = 100, RINGS = [72, 91], SW = 16, CHAR = 4.5, HOUR = 60, TICK_SPAN = 14;
const polar = (deg, r) => { const t = (deg * Math.PI) / 180; return [CX + r * Math.sin(t), CY - r * Math.cos(t)]; };
const minOf = (t) => { const [h, m] = t.split(":").map(Number); return h * 60 + m; };
const capDeg = (r, w) => ((w / 2) / r) * (180 / Math.PI);   // how far a round end reaches, in degrees
// do two arcs [a, a + span] on the circle meet?
const meets = (p, q) => { const d = (((q.a - p.a) % 360) + 360) % 360; return d < p.span || 360 - d < q.span; };

export function layoutClock(items) {
  const timed = items.filter((x) => x.time).map((x) => {
    const m = minOf(x.time);
    const span = x.done ? TICK_SPAN : Math.min(330, ((x.minutes || HOUR) / 720) * 360);
    return { ...x, m, a: ((m % 720) / 720) * 360, span };
  });
  // the clusters of items that overlap, one way or another
  const root = timed.map((_, i) => i);
  const find = (i) => (root[i] === i ? i : (root[i] = find(root[i])));
  timed.forEach((p, i) => timed.forEach((q, j) => { if (j > i && meets(p, q)) root[find(i)] = find(j); }));
  const clusters = {};
  timed.forEach((x, i) => (clusters[find(i)] = clusters[find(i)] || []).push(x));
  const rings = [[], []], badges = [];
  for (const c of Object.values(clusters)) {
    const order = [...c].sort((x, y) => (y.main ? 1 : 0) - (x.main ? 1 : 0) || x.m - y.m);
    const fit = [[], []], out = [];
    for (const x of order) {
      const r = fit.findIndex((ring) => !ring.some((y) => meets(x, y)));
      if (r < 0) out.push(x); else fit[r].push(x);
    }
    rings[0].push(...fit[0]);
    if (!out.length) { rings[1].push(...fit[1]); continue; }
    const hidden = [...fit[1], ...out].sort((x, y) => x.m - y.m);
    badges.push({ id: `more-${hidden[0].id}`, a: hidden[0].a, n: hidden.length, m: Math.max(...hidden.map((x) => x.m + (x.minutes || HOUR))) });
  }
  return { rings, badges };
}

function chipLabel(x, room) {
  const fits = (t) => t.length <= room;
  const full = `${x.time} ${x.label || ""}`.trim();
  if (fits(full)) return full;
  const word = `${x.time} ${(x.label || "").split(/\s+/)[0] || ""}`.trim();
  if (fits(word)) return word;
  if (room > x.time.length + 2) return `${word.slice(0, room - 1)}…`;
  return room >= x.time.length ? x.time : "";   // too short even for its time: just the colour
}

function Clock({ items, now }) {
  const { rings, badges } = layoutClock(items);
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const hA = ((now.getHours() % 12) * 60 + now.getMinutes()) / 2, mA = now.getMinutes() * 6;
  const [hx, hy] = polar(hA, 22), [mx, my] = polar(mA, 33);
  const chip = (x, r, ring) => {
    const past = x.m + (x.minutes || HOUR) < nowMin;
    if (x.done) {
      const [cx, cy] = polar(x.a + capDeg(r, 18), r);
      return (
        <g key={x.id} data-testid="clock-chip" data-ring={ring} data-start={x.a}><circle cx={cx} cy={cy} r="9" fill="#8ED973" />
          <path d={`M ${cx - 4} ${cy} L ${cx - 1} ${cy + 3} L ${cx + 4} ${cy - 3}`} stroke="#1d3b16" strokeWidth="2" fill="none" strokeLinecap="round" /></g>
      );
    }
    const cap = capDeg(r, SW);
    const mid = (((x.a + x.span / 2) % 360) + 360) % 360;
    const bottom = mid > 90 && mid < 270;
    const arc = (s, e) => {   // from s to e, the bottom ones backwards so their text reads upright
      const [p0, p1] = bottom ? [polar(e, r), polar(s, r)] : [polar(s, r), polar(e, r)];
      return `M ${p0[0]} ${p0[1]} A ${r} ${r} 0 ${e - s > 180 ? 1 : 0} ${bottom ? 0 : 1} ${p1[0]} ${p1[1]}`;
    };
    const [bg, fg] = CHIP[x.kind === "task" && x.main ? "main" : x.kind] || CHIP.task;
    const room = Math.floor((r * (x.span - 3) * Math.PI) / 180 / CHAR);   // the text may run into the round ends
    const round = x.span > 2 * cap + 1;   // a very short one is a square block, so it still lasts what it lasts
    const id = `chip-${ring}-${x.id}`;
    return (
      <g key={x.id} opacity={past ? 0.5 : 1} data-testid="clock-chip" data-ring={ring} data-start={x.a}>
        {/* the round ends start right at the start time */}
        <path d={round ? arc(x.a + cap, x.a + x.span - cap) : arc(x.a, x.a + x.span)} stroke={bg} strokeWidth={SW} fill="none" strokeLinecap={round ? "round" : "butt"} />
        {room >= x.time.length && <path id={id} d={arc(x.a + 1.5, x.a + x.span - 1.5)} fill="none" stroke="none" />}
        {room >= x.time.length && <text fontSize="8" fontWeight="600" fill={fg} dominantBaseline="middle">
          <textPath href={`#${id}`} startOffset="50%" textAnchor="middle">{chipLabel(x, room)}</textPath>
        </text>}
      </g>
    );
  };
  return (
    <svg viewBox="0 0 200 200" className="w-full h-full block" data-testid="today-clock" aria-label="Orologio con i task di oggi">
      {rings[1].map((x) => chip(x, RINGS[1], 1))}
      {rings[0].map((x) => chip(x, RINGS[0], 0))}
      {badges.map((b) => {
        const [x, y] = polar(b.a + capDeg(RINGS[1], 20), RINGS[1]);
        return (
          <g key={b.id} opacity={b.m < nowMin ? 0.5 : 1} data-testid="clock-more" data-start={b.a}>
            <circle cx={x} cy={y} r="10" fill="rgba(255,255,255,0.92)" />
            <text x={x} y={y + 0.5} fontSize="9" fontWeight="700" fill="#3d2238" textAnchor="middle" dominantBaseline="middle">+{b.n}</text>
          </g>
        );
      })}
      <circle cx={CX} cy={CY} r="56" fill="rgba(255,255,255,0.16)" stroke="rgba(255,255,255,0.35)" strokeWidth="1" />
      {[0, 90, 180, 270].map((d) => { const [a, b] = polar(d, 53), [c, e] = polar(d, 48); return <line key={d} x1={a} y1={b} x2={c} y2={e} stroke="rgba(255,255,255,0.85)" strokeWidth="2" strokeLinecap="round" />; })}
      {Array.from({ length: 12 }, (_, i) => { const [x, y] = polar((i || 12) * 30, 39); return <text key={i} x={x} y={y + 3.8} fontSize="10" fontWeight="500" fill="rgba(255,255,255,0.92)" textAnchor="middle">{i || 12}</text>; })}
      <line x1={CX} y1={CY} x2={hx} y2={hy} stroke="#fff" strokeWidth="5" strokeLinecap="round" />
      <line x1={CX} y1={CY} x2={mx} y2={my} stroke="#DD772F" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx={CX} cy={CY} r="4.5" fill="#fff" />
    </svg>
  );
}

// a problem: the red triangle with a white mark, no outline
const Alert = ({ size = 15, label }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-label={label} role="img" data-testid="today-alert">
    <path d="M10.27 3.5a2 2 0 0 1 3.46 0l8.5 14.75A2 2 0 0 1 20.5 21.25h-17a2 2 0 0 1-1.73-3z" fill="#FF6B5B" />
    <rect x="10.9" y="8.4" width="2.2" height="6.6" rx="1.1" fill="#fff" /><circle cx="12" cy="17.7" r="1.25" fill="#fff" />
  </svg>
);

const Kicker = ({ children }) => (
  <div className="text-[11px] font-semibold tracking-[0.14em] uppercase text-white" style={{ textShadow: "0 1px 6px rgba(60,20,50,.35)" }}>{children}</div>
);
const box = "rounded-[26px] lg-glass";
const fade = { WebkitMaskImage: "linear-gradient(180deg,#000 85%,transparent)", maskImage: "linear-gradient(180deg,#000 85%,transparent)" };

export default function TodayDashboard({ onOpenCommessa }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(false);
  const [now, setNow] = useState(new Date());
  const [sheet, setSheet] = useState(null);   // "clock" | "people"
  const wrap = useRef(null);
  const [h, setH] = useState(null);
  const [at, setAt] = useState(null);           // when the day was last read
  const loaded = useRef(false);                 // a refresh that fails keeps the day already on screen
  const load = () => api.get("/jobs/today").then((r) => { loaded.current = true; setD(r.data); setErr(false); setAt(new Date()); })
    .catch(() => { if (!loaded.current) setErr(true); });
  // the day keeps itself up to date: every minute while it is on screen, and at once when the app comes back
  // to the front (a phone stops the timers of an app in the background: opened again, it would show the old notes)
  useEffect(() => {
    load();
    const t = setInterval(() => setNow(new Date()), 30000);
    const r = setInterval(() => { if (document.visibilityState === "visible") load(); }, 60000);
    const back = () => { if (document.visibilityState === "visible") { setNow(new Date()); load(); } };
    document.addEventListener("visibilitychange", back);
    window.addEventListener("focus", back);
    window.addEventListener("pageshow", back);
    return () => {
      clearInterval(t); clearInterval(r);
      document.removeEventListener("visibilitychange", back);
      window.removeEventListener("focus", back);
      window.removeEventListener("pageshow", back);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
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
  const empty = !n.urgent.length && !n.today.length && !n.materials.length && !n.news.length && !n.tips.length;
  // a task of today ticked from here (the activities tick themselves when done on the site)
  const tickTask = async (x) => {
    const flip = (dd, v) => ({ ...dd, clock: dd.clock.map((c) => (c.id === x.id ? { ...c, done: v } : c)),
      notes: { ...dd.notes, today: dd.notes.today.map((c) => (c.id === x.id ? { ...c, done: v } : c)) } });
    setD((dd) => flip(dd, !x.done));
    try { await api.post(`/tasks/${x.id}/complete`); } catch { setD((dd) => flip(dd, x.done)); }
  };
  return (
    <div ref={wrap} className="flex flex-col gap-2.5" style={{ height: h || undefined }} data-testid="today-dashboard">
      <div className="grid grid-cols-[1.7fr_1fr] gap-2.5 shrink-0">
        {/* the tasks around the clock */}
        <button type="button" onClick={() => setSheet("clock")} className={`${box} p-3 pb-2 text-left flex flex-col`} data-testid="today-tasks">
          <Kicker>task di oggi</Kicker>
          <div className="mt-0.5 flex-1 min-h-0"><Clock items={d.clock} now={now} /></div>
          <div className="flex justify-between text-[10px] text-white/75 mt-0.5">
            <span>{d.clock.length} oggi{done ? ` · ${done} ${done === 1 ? "fatto" : "fatti"}` : ""}</span>
            {d.clock.length - timed > 0 && <span>+{d.clock.length - timed} senza ora</span>}
          </div>
        </button>
        {/* who is on site now */}
        <button type="button" onClick={() => on.total && setSheet("people")} className={`${box} p-3 text-left flex flex-col`} data-testid="today-onsite">
          <Kicker>in cantiere</Kicker>
          <div className="flex items-center gap-1.5 mt-2" data-testid="today-onsite-total"><span className="text-[36px] font-medium leading-none text-white shrink-0">{on.total}</span>
            <span className="min-w-0 text-[11px] leading-tight text-white/80">{on.sites ? `su ${on.sites} ${on.sites === 1 ? "cantiere" : "cantieri"}` : "nessun cantiere"}</span></div>
          {[["employees", "dipendenti", User, "#8FD3F4", "#1f3340"], ["collaborators", "collaboratori", HardHat, "#F2C14E", "#3a2a2a"]].map(([k, label, Icon, bg, fg]) => (
            <div key={k} className="mt-2 flex items-center gap-2 rounded-2xl bg-white/[0.12] px-2 py-1.5" data-testid={`today-${k}`}>
              <span className="h-[26px] w-[26px] shrink-0 rounded-full flex items-center justify-center" style={{ background: bg, color: fg }}><Icon size={14} strokeWidth={2.2} /></span>
              <span className="min-w-0"><span className="block text-[17px] font-semibold leading-tight text-white">{on[k]}</span>
                <span className="block text-[10px] text-white/75 leading-tight truncate">{label}</span></span>
            </div>
          ))}
          {on.paused > 0 && <div className="mt-auto pt-2 text-[10px] text-[#FFE3A1] flex items-center gap-1"><Pause size={10} fill="currentColor" /> {on.paused} in pausa</div>}
        </button>
      </div>

      {/* the commesse of today */}
      <div className={`${box} px-3.5 pt-3 pb-1 shrink-0`} data-testid="today-commesse">
        <div className="grid grid-cols-[14px_1fr_40px_22px] gap-2 items-center pb-1.5 border-b border-white/[0.14]">
          <span />
          <span className="min-w-0"><Kicker>commesse oggi</Kicker></span>
          <span className="flex justify-center text-white"><HardHat size={15} /></span>
          <span className="flex justify-center text-white"><AlertTriangle size={14} /></span>
        </div>
        <div className="overflow-y-auto overscroll-contain pb-2" style={{ ...fade, maxHeight: h && h < 560 ? 96 : 132 }}>
          {d.commesse.length === 0 && <div className="py-3 text-[12px] text-white/70">Nessuna commessa prevista oggi e nessuno in cantiere.</div>}
          {d.commesse.map((c) => (
            <button key={c.id} type="button" onClick={() => onOpenCommessa(c.id)} data-testid="today-commessa"
              className="w-full grid grid-cols-[14px_1fr_40px_22px] gap-2 items-center py-[7px] border-b border-white/[0.14] last:border-0 text-left active:opacity-70">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: STATUS_DOT[c.status] }} data-status={c.status} />
              <span className="min-w-0 truncate text-[13px] text-white"><b className="font-semibold">{c.client}</b> · {c.title}</span>
              <span className="flex justify-center tabular-nums whitespace-nowrap" data-testid="today-present">
                {/* the people there centred under the icon, the planned ones beside them */}
                <span className="relative text-[16px] font-medium leading-none text-white">{c.present}
                  <span className="absolute left-full bottom-0 text-[10px] font-normal text-white/50">/{c.expected}</span></span></span>
              <span className="flex justify-center">{c.problems
                ? <Alert size={13} label={`${c.problems} problemi aperti`} />
                : <span className="text-white/25">–</span>}</span>
            </button>
          ))}
        </div>
      </div>

      {/* the notes of the day */}
      <div className={`${box} px-3.5 pt-3 flex-1 min-h-[96px] flex flex-col`} data-testid="today-notes">
        <div className="flex items-baseline justify-between gap-2"><Kicker>note di oggi</Kicker>
          {at && <span className="text-[11px] text-white/60 tabular-nums" data-testid="today-updated">agg. {at.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}</span>}</div>
        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain pb-4 mt-1" style={fade}>
          {empty && <div className="py-2 text-[11px] text-white/70">Niente di previsto oggi.</div>}
          {n.urgent.length > 0 && <Part title="Da guardare subito" dot="#FF6B5B" testid="notes-urgent">
            {n.urgent.map((u, i) => (
              <button key={i} type="button" onClick={() => u.commessa_id && onOpenCommessa(u.commessa_id)} className="block w-full text-left text-white">{u.text}</button>
            ))}
          </Part>}
          {n.today.length > 0 && <Part title="Da fare oggi" testid="notes-today">
            {n.today.map((x) => (
              <div key={x.id} className="flex items-start gap-2" data-testid="notes-today-row" data-done={x.done ? "1" : "0"}>
                <button type="button" disabled={x.kind !== "task"} onClick={() => tickTask(x)} aria-pressed={!!x.done}
                  aria-label={x.kind === "task" ? (x.done ? "Segna da fare" : "Segna fatto") : (x.done ? "Svolta" : "Da svolgere")}
                  className="mt-[2px] h-[13px] w-[13px] shrink-0 rounded-full flex items-center justify-center"
                  style={x.done ? { background: "#FFAC33" } : { border: "1px solid rgba(255,255,255,0.75)" }}>
                  {x.done && <Check size={9} strokeWidth={3} className="text-[#3b2400]" />}
                </button>
                <button type="button" onClick={() => x.commessa_id && onOpenCommessa(x.commessa_id)} className={`flex-1 min-w-0 text-left ${x.done ? "text-white/55" : "text-white"}`}>
                  {x.time ? `${x.time} ` : ""}{x.text}
                  {x.commessa && <span className={x.done ? "" : "text-white/65"}> — {x.commessa}{x.who.length > 0 ? ` (${x.who.join(", ")})` : ""}</span>}
                </button>
              </div>
            ))}
          </Part>}
          {n.materials.length > 0 && <Part title="Materiali da prendere">
            {n.materials.map((m, i) => <div key={i}>{m.text}<span className="text-white/65">{[m.who, m.commessa && `per ${m.commessa}`].filter(Boolean).length ? ` — ${[m.who, m.commessa && `per ${m.commessa}`].filter(Boolean).join(", ")}` : ""}</span></div>)}
          </Part>}
          {n.news.length > 0 && <Part title="News">
            {n.news.map((x, i) => <div key={i}>{x.url ? <a href={x.url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">{x.title}</a> : x.title}</div>)}
          </Part>}
          {n.tips.length > 0 && <Part title="Consigli">
            {n.tips.map((t, i) => (
              <button key={i} type="button" onClick={() => t.commessa_id && onOpenCommessa(t.commessa_id)} className="block w-full text-left text-white">{t.text}</button>
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
                {x.commessa && <span className="block text-[11px] text-white/60">{x.label} · {x.commessa}</span>}</span>
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
                <span className="block text-[11px] text-white/60 truncate">{p.client} · {p.commessa} · dalle {hhmm(p.since)}{p.paused_at ? ` · in pausa dalle ${hhmm(p.paused_at)}` : ""}</span></span>
            </button>
          ))}
        </GlassBottomSheet>
      )}
    </div>
  );
}

function Part({ title, dot, testid, children }) {
  return (
    <div className="mt-2.5" data-testid={testid}>
      <div className="flex items-center gap-2 text-[12px] font-semibold text-white">
        <span className="h-[7px] w-[7px] rounded-full shrink-0" style={{ background: dot || "rgba(255,255,255,0.8)" }} />{title}</div>
      <div className="pl-[15px] mt-1 space-y-1 text-[11px] leading-snug text-white/90">{children}</div>
    </div>
  );
}
