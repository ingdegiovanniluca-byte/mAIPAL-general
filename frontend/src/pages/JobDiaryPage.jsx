import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Search, Mic, Square, Camera, Loader2, Clock, Package, AlertTriangle, Trash2, Pencil, X, Plus, MapPin, Phone, Mail,
  NotebookPen, MessageCircle, Send, ChevronRight, ChevronDown, RefreshCw, CalendarDays, CircleDot, FileText, Check, Briefcase, Activity,
  UserRound, HardHat, Euro, Flag, Contact, ListChecks } from "lucide-react";
import { api, API } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import GlassBottomSheet from "@/components/GlassBottomSheet";
import CommessaContacts from "@/components/CommessaContacts";
import { LiquidGlass, liquidPath, useMeasure, LIQUID_GAP } from "@/components/LiquidDock";
import { usePref } from "@/lib/prefs";
import FloatingGlassButton from "@/components/FloatingGlassButton";
import { useAuth } from "@/auth/AuthContext";

// Diario di commessa (verticale artigiano):
//   1. one card per client with its commesse and their state
//   2. a commessa opens its diary: its name, a row of cards that scrolls sideways (state,
//      hours, reports, documents, site, dates, phone, e-mail), the sections in a carousel,
//      the period, the entries by day. Every state change is written in the diary.
// The commessa's chat (ask about it, or write in its diary) opens from the round chat button
// floating on the side and sits at the bottom, like the one in the Chat section.

const STATO_COLOR = { "in corso": "#8ED973", preventivo: "#F2C14E", sospesa: "#E8A03F", chiusa: "rgba(255,255,255,0.35)" };
const IT_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
const IT_WEEKDAYS = ["domenica", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato"];
const dayLabel = (iso) => {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return `${IT_WEEKDAYS[dt.getDay()]} ${d} ${IT_MONTHS[m - 1]}${y !== new Date().getFullYear() ? ` ${y}` : ""}`;
};
const shortDay = (iso) => {
  if (!iso) return "";
  const [, m, d] = iso.split("-").map(Number);
  return `${d} ${IT_MONTHS[m - 1].slice(0, 3)}`;
};
// presence on site (collaborators, Telegram): how far from the site the start / end were
const ON_SITE_M = 300;
const distText = (m) => (m === null || m === undefined ? "" : m < 50 ? "in cantiere" : m < 1000 ? `a ${m} m` : `a ${(m / 1000).toFixed(1).replace(".", ",")} km`);
const mapsAt = (loc) => (loc ? `https://maps.google.com/?q=${loc.lat},${loc.lon}` : null);
const hhmmOf = (iso) => new Date(iso).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
const fmtNum = (x) => (x === null || x === undefined || x === "" ? "" : Number.isInteger(+x) ? String(+x) : String(+(+x).toFixed(2)).replace(".", ","));
const matLabel = (m) => [fmtNum(m.qty), m.unit, m.name].filter(Boolean).join(" ");
const photoUrl = (id) => `${API}/jobs/photos/${id}`;

// same compression as the chat's diary photos (max 1600px JPEG)
const fileToDataUri = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onerror = () => reject(new Error("Lettura file fallita"));
  reader.onload = () => {
    const img = new Image();
    img.onerror = () => reject(new Error("Immagine non valida"));
    img.onload = () => {
      const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * scale);
      c.height = Math.round(img.height * scale);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      resolve(c.toDataURL("image/jpeg", 0.82));
    };
    img.src = reader.result;
  };
  reader.readAsDataURL(file);
});

function StatoPill({ stato }) {
  return (
    <span className="inline-flex items-center gap-1 text-[10.5px] px-2 py-0.5 rounded-full bg-white/10 text-white/85 whitespace-nowrap">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: STATO_COLOR[stato] || "rgba(255,255,255,0.4)" }} />
      {stato || "senza stato"}
    </span>
  );
}

const STATO_ORDER = { "in corso": 0, preventivo: 1, sospesa: 2, "": 3, chiusa: 4 };

const IT_MON_SHORT = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const todayIso = () => isoDay(new Date());
const daysAgoIso = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return isoDay(d); };
// the week starts on Monday
const weekStartIso = () => { const d = new Date(); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return isoDay(d); };
const monthStartIso = () => { const d = new Date(); return isoDay(new Date(d.getFullYear(), d.getMonth(), 1)); };
const rangeDay = (iso, withYear) => {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return `${String(d).padStart(2, "0")} ${IT_MON_SHORT[m - 1]}${withYear ? ` ${y}` : ""}`;
};
const capFirst = (x) => (x ? x.charAt(0).toUpperCase() + x.slice(1) : x);
// the diary's sections, one word each (the carousel goes round)
const SECTIONS = [
  { key: "diario", label: "Diario" },
  { key: "ore", label: "Ore" },
  { key: "problemi", label: "Problemi" },
  { key: "materiali", label: "Materiali" },
  { key: "costi", label: "Costi" },
  { key: "milestone", label: "Milestone" },
  { key: "todo", label: "To Do" },
];
const PERIODS = [
  { key: "week", label: "Questa settimana" },
  { key: "30", label: "Ultimi 30 giorni" },
  { key: "month", label: "Questo mese" },
  { key: "all", label: "Tutta la commessa" },
];
const periodRange = (p) => (p.key === "30" ? { from: daysAgoIso(29), to: todayIso() }
  : p.key === "week" ? { from: weekStartIso(), to: todayIso() }
  : p.key === "month" ? { from: monthStartIso(), to: todayIso() }
  : p.key === "custom" ? { from: p.from || null, to: p.to || null }
  : { from: null, to: null });

// an item of the row on top of the diary: the icon on the left, at the height of the small
// caps label; the label and the value under it start on the same vertical (with a short grey
// note beside the value when useful); no box behind
function InfoCard({ icon: Icon, label, value, note, onClick, href, testid, ariaLabel, external }) {
  const cls = "snap-start shrink-0 min-w-[92px] max-w-[190px] py-1 flex items-start gap-1.5 text-left text-white"
    + (onClick || href ? " active:opacity-70" : "");
  const body = (
    <>
      <Icon size={14} className="text-white/55 shrink-0" />
      <span className="flex flex-col gap-1.5 min-w-0">
        <span className="text-[10px] leading-[14px] uppercase tracking-widest text-white/50 truncate" data-testid="info-label">{label}</span>
        <span className="flex items-baseline gap-1.5 min-w-0" data-testid="info-value">
          <span className="text-[15px] font-medium text-white/90 truncate">{value}</span>
          {note && <span className="text-[11px] text-white/55 whitespace-nowrap">{note}</span>}
        </span>
      </span>
    </>
  );
  if (href) return <a href={href} target={external ? "_blank" : undefined} rel={external ? "noreferrer" : undefined} data-testid={testid} aria-label={ariaLabel} className={cls}>{body}</a>;
  if (onClick) return <button type="button" onClick={onClick} data-testid={testid} aria-label={ariaLabel} className={cls}>{body}</button>;
  return <div data-testid={testid} aria-label={ariaLabel} className={cls}>{body}</div>;
}

// The site: its address on the map and its position for the collaborators' presences (found
// from the address, or set from the phone when on site).
function SiteSheet({ commessa, geo, onClose, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [g, setG] = useState(geo || null);
  const known = g && g.lat !== null && g.lat !== undefined;
  const save = async (body) => {
    setBusy(true);
    try { const r = await api.put(`/jobs/commesse/${commessa.id}/geo`, body); setG(r.data); toast.success("Posizione del cantiere salvata"); onChanged(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); } finally { setBusy(false); }
  };
  const here = () => {
    if (!navigator.geolocation) { toast.error("Questo dispositivo non dà la posizione"); return; }
    setBusy(true);
    navigator.geolocation.getCurrentPosition((p) => save({ lat: p.coords.latitude, lon: p.coords.longitude }),
      () => { setBusy(false); toast.error("Posizione non disponibile: consenti la posizione a mAIPAL"); }, { enableHighAccuracy: true, timeout: 15000 });
  };
  return (
    <GlassBottomSheet onClose={onClose} testid="site-sheet" className="max-h-[80vh] md:left-1/2 md:right-auto md:w-[480px] md:-translate-x-1/2 md:bottom-8">
      <div className="text-lg font-semibold text-white mb-1">Cantiere</div>
      <div className="text-sm text-white/85 break-words">{commessa.address || "Indirizzo non indicato"}</div>
      {commessa.address && (
        <a href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(commessa.address)}`} target="_blank" rel="noreferrer"
          className="mt-1 inline-flex items-center gap-1 text-[12.5px] text-white/75 underline-offset-2 hover:underline"><MapPin size={12} /> Apri sulla mappa</a>
      )}
      <div className="mt-4 rounded-2xl bg-white/[0.06] px-3.5 py-3">
        <div className="text-[10px] uppercase tracking-widest text-white/50 mb-1">posizione per le presenze</div>
        <div className="text-[13px] text-white/85" data-testid="site-geo-state">
          {known ? (g.source === "manual" ? "Impostata da te" : "Trovata dall'indirizzo") : "Non trovata: le presenze dei collaboratori non mostrano la distanza dal cantiere"}
          {known && <a href={mapsAt(g)} target="_blank" rel="noreferrer" className="ml-2 underline-offset-2 hover:underline text-white/65">vedi</a>}
        </div>
        <div className="text-[11.5px] text-white/50 mt-1">Quando un collaboratore tocca 📍 su Telegram all'arrivo e alla fine, vedi a che distanza dal cantiere era.</div>
        <div className="flex flex-wrap gap-2 mt-3">
          <button onClick={here} disabled={busy} data-testid="site-geo-here" className="px-3.5 py-1.5 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50 inline-flex items-center gap-1.5">
            {busy ? <Loader2 size={13} className="animate-spin" /> : <MapPin size={13} />} Sono in cantiere: usa questa posizione
          </button>
          {commessa.address && (
            <button onClick={() => save({})} disabled={busy} data-testid="site-geo-address" className="px-3.5 py-1.5 rounded-full text-sm bg-white/10 text-white disabled:opacity-50">Ritrova dall'indirizzo</button>
          )}
        </div>
      </div>
    </GlassBottomSheet>
  );
}

// a line of the diary: who (grey) with a small icon when it carries hours / problems /
// materials, the text, the photos; tap to change or delete it
// A report made for the commessa is an event too: its type and summary, and (for who made it)
// the link to download it.
function DiaryLine({ log, section, onOpen, onPhoto, me }) {
  const isEvent = !!log.kind;
  const isReport = log.kind === "report";
  const full = section === "diario";
  const [head, ...rest] = isReport ? (log.text || "").split("\n") : [];
  const detail = section === "ore" ? hoursLineOf(log) : section === "problemi" ? (log.problems || []).join("; ")
    : section === "materiali" ? (log.materials || []).map(matLabel).join(" · ") : "";
  return (
    <div data-testid={isReport ? "job-report-event" : isEvent ? "job-stato-event" : "job-entry"}>
      <button type="button" onClick={() => onOpen(log)} className="w-full text-left">
        <span className="flex items-center gap-[5px] text-white/50">
          {isEvent && (isReport ? <FileText size={11} strokeWidth={2} /> : log.kind === "milestone" ? <Flag size={11} strokeWidth={2} /> : log.kind === "todo" ? <ListChecks size={11} strokeWidth={2} /> : <RefreshCw size={11} strokeWidth={2} />)}
          {full && !isEvent && log.hours?.length > 0 && <Clock size={11} strokeWidth={2} />}
          {full && !isEvent && log.problems?.length > 0 && <AlertTriangle size={11} strokeWidth={2} />}
          {full && !isEvent && log.materials?.length > 0 && <Package size={11} strokeWidth={2} />}
          <span className="text-[11.5px] font-medium">{log.author_name}</span>
          {log.author_company && <span className="text-[10.5px] text-white/40">· {log.author_company}</span>}
          {log.channel === "telegram" && <span className="text-[10.5px] text-white/40">· Telegram</span>}
        </span>
        {detail && <span className="block mt-[3px] text-[14.5px] font-medium leading-snug text-white">{detail}</span>}
        <span className={`block mt-[3px] leading-[1.45] whitespace-pre-wrap ${isEvent ? "text-[13px] text-white/70"
          : full ? "text-[14px] text-white/90" : "text-[12.5px] text-white/55"}`}>
          {isReport ? (
            <>
              <span className="block text-white/85" data-testid="job-report-head">{head}</span>
              {rest.join("\n").trim() && <span className="block mt-[2px] text-white/65" data-testid="job-report-summary">{rest.join("\n").trim()}</span>}
            </>
          ) : isEvent && log.stato_to ? `Stato: ${log.stato_from || "—"} → ${log.stato_to}` : log.text}
        </span>
      </button>
      {isReport && log.report_id && me && log.user_id === me && (
        <a href={`${API}/work/reports/${log.report_id}/download`} data-testid="job-report-download"
          className="mt-1.5 inline-flex items-center gap-1 text-[12px] text-white/75 underline-offset-2 hover:underline">
          <FileText size={12} /> Scarica il report
        </a>
      )}
      {full && log.presence && (log.presence.start_loc || log.presence.end_loc) && (
        <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px] text-white/60" data-testid="job-presence">
          <MapPin size={12} className="shrink-0" />
          {[["inizio", log.presence.start_loc, log.presence.start_m], ["fine", log.presence.end_loc, log.presence.end_m]].map(([k, loc, m]) => (loc ? (
            <a key={k} href={mapsAt(loc)} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline"
              style={m > ON_SITE_M ? { color: "#FFB199" } : undefined}>
              {k} {m === null || m === undefined ? "(cantiere senza posizione)" : distText(m)}
            </a>
          ) : <span key={k}>{k} senza posizione</span>))}
        </span>
      )}
      {full && log.photos?.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {log.photos.map((p) => (
            <button key={p.id} type="button" onClick={() => onPhoto(log, p)} className="h-11 w-11 rounded-[10px] overflow-hidden bg-white/15" aria-label="Apri la foto">
              <img src={photoUrl(p.id)} alt="" loading="lazy" className="h-full w-full object-cover" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
const hoursLineOf = (log) => (log.hours || []).map((h) => `${h.who} ${fmtNum(h.hours)} h`).join(" · ");

function EditDialog({ log, onClose, onSaved, onDelete }) {
  const toTake = async (i) => {
    try {
      const r = await api.post(`/jobs/logs/${log.id}/plan-material`, { index: i });
      toast.success(`Spostato in «Da prendere» per ${shortDay(r.data.todo.due_date)}`);
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const [text, setText] = useState(log.text || "");
  const [date, setDate] = useState(log.date || "");
  const [hours, setHours] = useState((log.hours || []).map((h) => ({ ...h, hours: fmtNum(h.hours) })));
  const [materials, setMaterials] = useState((log.materials || []).map((m, i) => ({ ...m, qty: fmtNum(m.qty), orig: i })));
  const [problems, setProblems] = useState((log.problems || []).join("\n"));
  const [saving, setSaving] = useState(false);
  const num = (v) => (String(v).trim() === "" ? null : Number(String(v).replace(",", ".")));
  const save = async () => {
    setSaving(true);
    try {
      const r = await api.patch(`/jobs/logs/${log.id}`, {
        text, date,
        hours: hours.filter((h) => h.who && num(h.hours)).map((h) => ({ who: h.who, hours: num(h.hours) })),
        materials: materials.filter((m) => m.name).map((m) => ({ name: m.name, qty: num(m.qty), unit: m.unit || "" })),
        problems: problems.split("\n").map((p) => p.trim()).filter(Boolean),
      });
      onSaved(r.data);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore nel salvataggio"); }
    finally { setSaving(false); }
  };
  const field = "h-9 rounded-lg bg-white/10 px-2.5 text-sm text-white placeholder:text-white/40 outline-none";
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-lg bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="job-edit-dialog">
        <DialogHeader><DialogTitle>Modifica la voce</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <div>
            <div className="kicker mb-1">giorno</div>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={`${field} w-full`} />
          </div>
          <div>
            <div className="kicker mb-1">cosa è stato fatto</div>
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} className="w-full rounded-lg bg-white/10 p-2.5 text-sm text-white outline-none" />
          </div>
          <div>
            <div className="kicker mb-1">ore</div>
            {hours.map((h, i) => (
              <div key={i} className="flex gap-2 mb-1.5">
                <input value={h.who} onChange={(e) => setHours((xs) => xs.map((x, j) => (j === i ? { ...x, who: e.target.value } : x)))} placeholder="Chi" className={`${field} flex-1`} />
                <input value={h.hours} onChange={(e) => setHours((xs) => xs.map((x, j) => (j === i ? { ...x, hours: e.target.value } : x)))} placeholder="Ore" inputMode="decimal" className={`${field} w-20`} />
                <button onClick={() => setHours((xs) => xs.filter((_, j) => j !== i))} className="p-2 text-white/60 hover:text-white"><X size={14} /></button>
              </div>
            ))}
            <button onClick={() => setHours((xs) => [...xs, { who: "", hours: "" }])} className="text-xs text-white/75 inline-flex items-center gap-1"><Plus size={12} /> aggiungi</button>
          </div>
          <div>
            <div className="kicker mb-1">materiali</div>
            {materials.map((m, i) => (
              <div key={i} className="flex gap-2 mb-1.5">
                <input value={m.qty} onChange={(e) => setMaterials((xs) => xs.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} placeholder="Q.tà" inputMode="decimal" className={`${field} w-16`} />
                <input value={m.unit} onChange={(e) => setMaterials((xs) => xs.map((x, j) => (j === i ? { ...x, unit: e.target.value } : x)))} placeholder="u.m." className={`${field} w-16`} />
                <input value={m.name} onChange={(e) => setMaterials((xs) => xs.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} placeholder="Materiale" className={`${field} flex-1`} />
                {m.orig !== undefined && (
                  <button onClick={() => toTake(m.orig)} title="Non usato: da prendere" aria-label={`${m.name}: non usato, da prendere`} data-testid="material-to-take"
                    className="p-2 text-white/60 hover:text-white"><CalendarDays size={14} /></button>
                )}
                <button onClick={() => setMaterials((xs) => xs.filter((_, j) => j !== i))} className="p-2 text-white/60 hover:text-white"><X size={14} /></button>
              </div>
            ))}
            <button onClick={() => setMaterials((xs) => [...xs, { qty: "", unit: "", name: "" }])} className="text-xs text-white/75 inline-flex items-center gap-1"><Plus size={12} /> aggiungi</button>
          </div>
          <div>
            <div className="kicker mb-1">problemi (uno per riga)</div>
            <textarea value={problems} onChange={(e) => setProblems(e.target.value)} rows={3} className="w-full rounded-lg bg-white/10 p-2.5 text-sm text-white outline-none" />
          </div>
          <div className="flex justify-end gap-2">
            {onDelete && (
              <button onClick={() => onDelete(log)} data-testid="job-edit-delete" className="mr-auto px-3 py-2 rounded-full text-sm text-white/75 hover:bg-white/10 inline-flex items-center gap-1.5">
                <Trash2 size={14} /> Elimina
              </button>
            )}
            <button onClick={onClose} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Annulla</button>
            <button onClick={save} disabled={saving} data-testid="job-edit-save" className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50">
              {saving ? "Salvo…" : "Salva"}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ===== Costi: what the commessa has cost so far against its quote =====
const eur = (x) => (x === null || x === undefined ? "—"
  : new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR", minimumFractionDigits: x % 1 ? 2 : 0, maximumFractionDigits: 2 }).format(x));
const parseMoney = (v) => {
  const t = String(v ?? "").replace(/[€\s]/g, "").replace(/\.(?=\d{3}(\D|$))/g, "").replace(",", ".");
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) && n >= 0 ? n : NaN;
};

// A small amount field: saved when it loses focus (or Enter), only if it changed.
function MoneyInput({ value, onSave, placeholder, testid, wide = false }) {
  const shown = value === null || value === undefined ? "" : String(value).replace(".", ",");
  const [v, setV] = useState(shown);
  useEffect(() => { setV(shown); }, [shown]);
  const commit = () => {
    const n = parseMoney(v);
    if (Number.isNaN(n)) { toast.error("Importo non valido"); setV(shown); return; }
    if ((n ?? null) !== (value ?? null)) onSave(n);
  };
  return (
    <input value={v} onChange={(e) => setV(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
      inputMode="decimal" placeholder={placeholder} data-testid={testid}
      className={`h-8 ${wide ? "w-28" : "w-[72px]"} rounded-lg bg-white/10 px-2 text-right text-[13px] text-white placeholder:text-white/35 outline-none`} />
  );
}

function CostsView({ commessaId, onChanged }) {
  const [e, setE] = useState(null);
  const [label, setLabel] = useState("");
  const [amount, setAmount] = useState("");
  useEffect(() => {
    api.get(`/jobs/commesse/${commessaId}/economics`).then((r) => setE(r.data)).catch(() => toast.error("Errore nel caricamento dei costi"));
  }, [commessaId]);
  const done = (r) => { setE(r.data); onChanged(); };
  const fail = (err) => toast.error(err.response?.data?.detail || "Errore nel salvataggio");
  const setBudget = (n) => api.patch(`/jobs/commesse/${commessaId}/economics`, n === null ? { clear_budget: true } : { budget: n }).then(done).catch(fail);
  const costs = (body) => api.patch(`/jobs/costs`, body, { params: { commessa_id: commessaId } }).then(done).catch(fail);
  const addExtra = () => {
    const n = parseMoney(amount);
    if (!label.trim() || n === null || Number.isNaN(n)) { toast.error("Scrivi la voce e l'importo"); return; }
    api.post(`/jobs/commesse/${commessaId}/extras`, { label, amount: n }).then((r) => { setLabel(""); setAmount(""); done(r); }).catch(fail);
  };
  const delExtra = (x) => api.delete(`/jobs/commesse/${commessaId}/extras/${x.id}`).then(done).catch(fail);
  if (!e) return <div className="kicker text-center py-8">caricamento…</div>;
  const pct = e.used_pct;
  const barColor = pct >= 100 ? "#E8663F" : pct >= 80 ? "#E8A03F" : "rgba(255,255,255,0.75)";
  const head = "text-[11px] font-medium tracking-[0.18em] uppercase text-white/60 pt-5 pb-1.5";
  const row = "flex items-center gap-3 py-2.5 border-t border-white/[0.16]";
  return (
    <div className="mt-2" data-testid="costs-view">
      {/* the quote, the costs, the margin */}
      <div className={row}>
        <span className="flex-1 text-[14px] text-white/90">Preventivo</span>
        <MoneyInput value={e.budget} onSave={setBudget} placeholder="€" testid="costs-budget" wide />
      </div>
      <div className={row}>
        <span className="flex-1 text-[14px] text-white/90">Costi</span>
        <span className="text-[15px] font-medium text-white" data-testid="costs-total">{eur(e.cost_total)}</span>
      </div>
      <div className={row}>
        <span className="flex-1 text-[14px] text-white/90">Margine</span>
        <span className="text-[15px] font-medium text-white" data-testid="costs-margin">{e.budget ? eur(e.margin) : "—"}</span>
      </div>
      {e.budget ? (
        <div className="pt-1 pb-1">
          <div className="h-1.5 rounded-full bg-white/15 overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${Math.min(100, pct || 0)}%`, background: barColor }} />
          </div>
          <div className="mt-1.5 text-[12px] text-white/70" data-testid="costs-pct">
            {pct >= 100 ? `Preventivo superato: speso il ${Math.round(pct)}%` : `Speso il ${Math.round(pct || 0)}% del preventivo`}
          </div>
        </div>
      ) : <div className="text-[12px] text-white/55 pb-1">Inserisci il preventivo per vedere il margine.</div>}
      {!e.complete && (
        <div className="text-[12px] text-white/60" data-testid="costs-missing">
          Non conteggiati: {[e.unpriced_hours ? `${fmtNum(e.unpriced_hours)} h senza tariffa` : "", e.unpriced_materials.length ? `${e.unpriced_materials.length} material${e.unpriced_materials.length === 1 ? "e" : "i"} senza prezzo` : ""].filter(Boolean).join(", ")}: inseriscili qui sotto.
        </div>
      )}

      <div className={head}>manodopera · {eur(e.labor_total)}</div>
      <div className={row}>
        <span className="flex-1 min-w-0">
          <span className="block text-[14px] text-white/90">Tariffa standard</span>
          <span className="block text-[11.5px] text-white/50">per chi non ha una tariffa sua</span>
        </span>
        <MoneyInput value={e.default_rate} onSave={(n) => costs(n === null ? { clear_default_rate: true } : { default_rate: n })} placeholder="€/h" testid="costs-default-rate" />
      </div>
      {e.labor.map((x) => (
        <div key={x.who} className={row} data-testid="costs-labor-row">
          <span className="flex-1 min-w-0">
            <span className="block text-[14px] text-white/90 truncate">{x.who}</span>
            <span className="block text-[11.5px] text-white/50">{fmtNum(x.hours)} h{x.cost !== null ? ` · ${eur(x.cost)}` : " · senza tariffa"}</span>
          </span>
          <MoneyInput value={x.own_rate ? x.rate : null} placeholder={e.default_rate ? `${fmtNum(e.default_rate)} €/h` : "€/h"}
            onSave={(n) => costs({ rates: { [x.who]: n } })} testid={`costs-rate-${x.who}`} />
        </div>
      ))}
      {e.labor.length === 0 && <div className="py-2.5 border-t border-white/[0.16] text-[13px] text-white/55">Nessuna ora registrata.</div>}

      <div className={head}>materiali · {eur(e.materials_total)}</div>
      {e.materials.map((m) => (
        <div key={m.key} className={row} data-testid="costs-material-row">
          <span className="flex-1 min-w-0">
            <span className="block text-[14px] text-white/90 truncate">{m.name}</span>
            <span className="block text-[11.5px] text-white/50">
              {m.qty !== null ? `${fmtNum(m.qty)} ${m.unit || ""}` : "quantità non indicata"}{m.cost !== null ? ` · ${eur(m.cost)}` : ""}
            </span>
          </span>
          <MoneyInput value={m.price} placeholder={`€/${m.unit || "pz"}`} onSave={(n) => costs({ prices: [{ name: m.name, unit: m.unit || "", price: n }] })}
            testid={`costs-price-${m.key}`} />
        </div>
      ))}
      {e.materials.length === 0 && <div className="py-2.5 border-t border-white/[0.16] text-[13px] text-white/55">Nessun materiale registrato.</div>}

      <div className={head}>altre spese · {eur(e.extras_total)}</div>
      {e.extras.map((x) => (
        <div key={x.id} className={row} data-testid="costs-extra-row">
          <span className="flex-1 min-w-0">
            <span className="block text-[14px] text-white/90 truncate">{x.label}</span>
            <span className="block text-[11.5px] text-white/50">{shortDay(x.date)}{x.by ? ` · ${x.by}` : ""}</span>
          </span>
          <span className="text-[14px] text-white">{eur(x.amount)}</span>
          <button type="button" onClick={() => delExtra(x)} aria-label="Elimina la spesa" className="p-1.5 text-white/55 hover:text-white"><Trash2 size={14} /></button>
        </div>
      ))}
      <div className="flex items-center gap-2 py-2.5 border-t border-white/[0.16]">
        <input value={label} onChange={(ev) => setLabel(ev.target.value)} placeholder="Es. noleggio ponteggio" data-testid="costs-extra-label"
          className="h-8 flex-1 min-w-0 rounded-lg bg-white/10 px-2 text-[13px] text-white placeholder:text-white/35 outline-none" />
        <input value={amount} onChange={(ev) => setAmount(ev.target.value)} placeholder="€" inputMode="decimal" data-testid="costs-extra-amount"
          onKeyDown={(ev) => { if (ev.key === "Enter") addExtra(); }}
          className="h-8 w-[72px] rounded-lg bg-white/10 px-2 text-right text-[13px] text-white placeholder:text-white/35 outline-none" />
        {/* keeps the field focused: a blur would bring the tab bar back under the finger */}
        <button type="button" onMouseDown={(ev) => ev.preventDefault()} onClick={addExtra} data-testid="costs-extra-add" aria-label="Aggiungi la spesa" className="h-8 w-8 shrink-0 rounded-full bg-white/15 flex items-center justify-center text-white"><Plus size={15} /></button>
      </div>
      <div className="pt-3 text-[11.5px] text-white/50">Tariffe orarie e prezzi dei materiali valgono per tutte le commesse. All'80% e al 100% del preventivo ti avviso su Telegram.</div>
    </div>
  );
}

// To Do: an activity planned for the commessa - who takes care of it and by when (if said)
// stand out on top, like the author of a diary line; the dot ticks it done.
function TodoRow({ todo, onToggle, onOpen }) {
  const overdue = !todo.done && todo.due_date && todo.due_date < todayIso();
  return (
    <div className="grid grid-cols-[34px_minmax(0,1fr)] gap-x-3 py-3 border-t border-white/[0.16]" data-testid="job-todo" data-done={todo.done ? "1" : "0"}>
      <button type="button" onClick={() => onToggle(todo)} aria-pressed={!!todo.done} data-testid="job-todo-done"
        aria-label={todo.done ? "Segna come da fare" : "Segna come fatta"}
        className={`mt-[1px] h-5 w-5 rounded-full flex items-center justify-center backdrop-blur-md ${todo.done ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
        {todo.done && <Check size={12} strokeWidth={2.8} />}
      </button>
      <button type="button" onClick={() => onOpen(todo)} className="min-w-0 text-left">
        <span className={`flex items-center gap-x-3.5 gap-y-0.5 flex-wrap text-[12.5px] font-medium ${todo.done ? "text-white/50" : "text-white"}`}>
          {todo.kind === "materiale" && <Package size={12} strokeWidth={2} aria-label="materiale da prendere" />}
          <span className="inline-flex items-center gap-1" data-testid="job-todo-who"><UserRound size={12} strokeWidth={2} /> {todo.who}
            {todo.collaborator_id && <Send size={10} strokeWidth={2} className="text-white/55" aria-label="collaboratore, avvisato su Telegram" />}</span>
          {todo.due_date && (
            <span className="inline-flex items-center gap-1" data-testid="job-todo-due">
              <CalendarDays size={12} strokeWidth={2} /> entro {shortDay(todo.due_date)}{overdue && <span className="text-white/55 font-normal">· scaduta</span>}
            </span>
          )}
        </span>
        <span className={`block mt-[3px] text-[14px] leading-[1.45] whitespace-pre-wrap ${todo.done ? "text-white/45 line-through" : "text-white/90"}`}>{todo.text}</span>
      </button>
    </div>
  );
}

// Who does it: a team mate or a collaborator enabled on the commessa (chips, or the name
// typed). A collaborator's To Do / milestone reaches them on Telegram, with the reminders.
function AssigneePicker({ who, setWho, collabId, setCollabId, team, collaborators, testid }) {
  const byName = (v) => collaborators.find((c) => c.name.toLowerCase() === v.trim().toLowerCase());
  const pick = (name, id) => { setWho(name); setCollabId(id || ""); };
  const chosen = collaborators.find((c) => c.id === collabId);
  const chip = (on) => `shrink-0 whitespace-nowrap inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs ${on ? "lg-bubble text-white font-medium" : "bg-white/10 text-white/75 hover:bg-white/15"}`;
  return (
    <div data-testid={testid}>
      <input value={who} onChange={(e) => { setWho(e.target.value); setCollabId(byName(e.target.value)?.id || ""); }} placeholder="Nome"
        data-testid={`${testid}-input`} className="h-9 rounded-lg bg-white/10 px-2.5 text-sm text-white placeholder:text-white/40 outline-none w-full" />
      <div className="flex gap-1.5 overflow-x-auto mt-2 pb-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {team.map((n) => <button key={`t-${n}`} type="button" onClick={() => pick(n, "")} className={chip(!collabId && who === n)}>{n}</button>)}
        {collaborators.map((c) => (
          <button key={c.id} type="button" onClick={() => pick(c.name, c.id)} data-testid={`${testid}-collab-${c.id}`} className={chip(collabId === c.id)}>
            {c.telegram && <Send size={10} strokeWidth={2} />} {c.name}{c.company ? ` · ${c.company}` : ""}
          </button>
        ))}
      </div>
      {chosen && (
        <div className="text-[11.5px] text-white/60 mt-1.5" data-testid={`${testid}-hint`}>
          {chosen.telegram ? `${chosen.first_name || chosen.name} lo riceve su Telegram, con i promemoria e il pulsante ✅ Fatto.`
            : `${chosen.first_name || chosen.name} non ha ancora collegato Telegram: non riceverà avvisi.`}
        </div>
      )}
    </div>
  );
}

function TodoDialog({ todo, commessaId, team, collaborators = [], onClose, onSaved }) {
  const isNew = !todo.id;
  const [text, setText] = useState(todo.text || "");
  const [who, setWho] = useState(todo.who || team[0] || "");
  const [collabId, setCollabId] = useState(todo.collaborator_id || "");
  const [due, setDue] = useState(todo.due_date || "");
  const [saving, setSaving] = useState(false);
  const save = async () => {
    if (!text.trim()) { toast.error("Scrivi l'attività da fare"); return; }
    setSaving(true);
    try {
      const r = isNew ? await api.post(`/jobs/commesse/${commessaId}/todos`, { text, who, collaborator_id: collabId, due_date: due || null })
        : await api.patch(`/jobs/todos/${todo.id}`, { text, who, collaborator_id: collabId, due_date: due || "" });
      if (r.data?.notified) toast.success(`Mandata a ${r.data.who} su Telegram`);
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore nel salvataggio"); }
    finally { setSaving(false); }
  };
  const del = async () => {
    try { await api.delete(`/jobs/todos/${todo.id}`); onSaved(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const field = "h-9 rounded-lg bg-white/10 px-2.5 text-sm text-white placeholder:text-white/40 outline-none";
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-lg bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="job-todo-dialog">
        <DialogHeader><DialogTitle>{isNew ? "Nuova attività" : "Modifica l'attività"}</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <div>
            <div className="kicker mb-1">cosa c'è da fare</div>
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} autoFocus data-testid="job-todo-text"
              placeholder="Es. Montare i sanitari" className="w-full rounded-lg bg-white/10 p-2.5 text-sm text-white placeholder:text-white/40 outline-none" />
          </div>
          <div>
            <div className="kicker mb-1">chi se ne occupa</div>
            <AssigneePicker who={who} setWho={setWho} collabId={collabId} setCollabId={setCollabId} team={team} collaborators={collaborators} testid="job-todo-assignee" />
          </div>
          <div>
            <div className="kicker mb-1">entro quando (facoltativo)</div>
            <div className="flex items-center gap-2">
              <input type="date" value={due} onChange={(e) => setDue(e.target.value)} data-testid="job-todo-due-input" className={`${field} flex-1`} />
              {due && <button type="button" onClick={() => setDue("")} className="p-2 text-white/60 hover:text-white" aria-label="Togli la data"><X size={14} /></button>}
            </div>
          </div>
          <div className="flex justify-end gap-2">
            {!isNew && (
              <button onClick={del} data-testid="job-todo-delete" className="mr-auto px-3 py-2 rounded-full text-sm text-white/75 hover:bg-white/10 inline-flex items-center gap-1.5">
                <Trash2 size={14} /> Elimina
              </button>
            )}
            <button onClick={onClose} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Annulla</button>
            <button onClick={save} disabled={saving} data-testid="job-todo-save" className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50">
              {saving ? "Salvo…" : "Salva"}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ===== Milestone: the project's steps - who, by when; done (on which day), late, moved =====
const LATE = "#FF9C85";
const daysLabel = (n) => `${n} ${n === 1 ? "giorno" : "giorni"}`;
function milestoneState(m) {
  if (m.status === "done") return { text: m.delay_days ? `fatta il ${shortDay(m.done_date)} · ${daysLabel(m.delay_days)} di ritardo` : `fatta il ${shortDay(m.done_date)} · in tempo`, late: !!m.delay_days };
  if (m.status === "late") return { text: `in ritardo di ${daysLabel(m.late_days)}`, late: true };
  return { text: m.status === "soon" ? "in scadenza" : "", late: false };
}

function MilestoneRow({ m, onToggle, onOpen }) {
  const st = milestoneState(m);
  const done = m.status === "done";
  const acts = (m.corrective_actions || []).length;
  return (
    <div className="grid grid-cols-[34px_minmax(0,1fr)] gap-x-3 py-3 border-t border-white/[0.16]" data-testid="job-milestone" data-status={m.status}>
      <button type="button" onClick={() => onToggle(m)} aria-pressed={done} data-testid="job-milestone-done"
        aria-label={done ? "Segna come da fare" : "Segna come fatta"}
        className={`mt-[1px] h-5 w-5 rounded-full flex items-center justify-center backdrop-blur-md ${done ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
        {done && <Check size={12} strokeWidth={2.8} />}
      </button>
      <button type="button" onClick={() => onOpen(m)} className="min-w-0 text-left">
        <span className={`flex items-center gap-x-3.5 gap-y-0.5 flex-wrap text-[12.5px] font-medium ${done ? "text-white/50" : "text-white"}`}>
          <span className="inline-flex items-center gap-1"><UserRound size={12} strokeWidth={2} /> {m.who}
            {m.collaborator_id && <Send size={10} strokeWidth={2} className="text-white/55" aria-label="collaboratore, avvisato su Telegram" />}</span>
          <span className="inline-flex items-center gap-1" data-testid="job-milestone-due"><Flag size={12} strokeWidth={2} /> {shortDay(m.due_date)}</span>
        </span>
        <span className={`block mt-[3px] text-[14px] leading-[1.45] ${done ? "text-white/45" : "text-white/90"}`}>{m.title}</span>
        {(st.text || m.slip_days > 0 || acts > 0) && (
          <span className="block mt-[2px] text-[11.5px] text-white/55" data-testid="job-milestone-state">
            {st.text && <span style={st.late ? { color: LATE } : undefined}>{st.text}</span>}
            {m.slip_days > 0 && `${st.text ? " · " : ""}spostata di ${daysLabel(m.slip_days)}`}
            {acts > 0 && ` · ${acts} ${acts === 1 ? "azione correttiva" : "azioni correttive"}`}
          </span>
        )}
      </button>
    </div>
  );
}

function MilestoneSheet({ m, commessaId, team, collaborators = [], onClose, onSaved }) {
  const isNew = !m.id;
  const [title, setTitle] = useState(m.title || "");
  const [who, setWho] = useState(m.who || team[0] || "");
  const [collabId, setCollabId] = useState(m.collaborator_id || "");
  const [due, setDue] = useState(m.due_date || "");
  const [doneDate, setDoneDate] = useState(m.done_date || "");
  const [action, setAction] = useState("");
  const [newDue, setNewDue] = useState("");
  const [busy, setBusy] = useState(false);
  const fail = (e) => toast.error(e.response?.data?.detail || "Errore nel salvataggio");
  const save = async () => {
    if (!title.trim()) { toast.error("Scrivi la milestone"); return; }
    if (!due) { toast.error("Indica la scadenza"); return; }
    setBusy(true);
    try {
      const r = isNew ? await api.post(`/jobs/commesse/${commessaId}/milestones`, { title, who, collaborator_id: collabId, due_date: due })
        : await api.patch(`/jobs/milestones/${m.id}`, { title, who, collaborator_id: collabId, ...(due !== m.due_date ? { due_date: due } : {}),
          ...(m.status === "done" && doneDate && doneDate !== m.done_date ? { done_date: doneDate } : {}) });
      if (r.data?.notified) toast.success(`Mandata a ${r.data.who} su Telegram`);
      onSaved();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const addAction = async () => {
    if (!action.trim()) { toast.error("Scrivi l'azione correttiva"); return; }
    setBusy(true);
    try { await api.post(`/jobs/milestones/${m.id}/actions`, { text: action, new_due_date: newDue || null }); onSaved(); }
    catch (e) { fail(e); } finally { setBusy(false); }
  };
  const del = async () => {
    try { await api.delete(`/jobs/milestones/${m.id}`); onSaved(); } catch (e) { fail(e); }
  };
  const field = "h-9 rounded-lg bg-white/10 px-2.5 text-sm text-white placeholder:text-white/40 outline-none";
  const st = isNew ? null : milestoneState(m);
  return (
    <GlassBottomSheet onClose={onClose} testid="job-milestone-sheet" className="max-h-[88vh] md:left-1/2 md:right-auto md:w-[520px] md:-translate-x-1/2 md:bottom-8">
      <div className="text-lg font-semibold text-white mb-1">{isNew ? "Nuova milestone" : "Milestone"}</div>
      {st?.text && <div className="text-[12.5px] mb-3" style={st.late ? { color: LATE } : { color: "rgba(255,255,255,0.6)" }} data-testid="job-milestone-sheet-state">{st.text}</div>}
      <div className="space-y-4 mt-3">
        <div>
          <div className="kicker mb-1">cosa va completato</div>
          <input value={title} onChange={(e) => setTitle(e.target.value)} autoFocus={isNew} data-testid="job-milestone-title"
            placeholder="Es. Impianto elettrico completato" className={`${field} w-full`} />
        </div>
        <div className="min-w-0">
          <div className="kicker mb-1">chi la esegue</div>
          <AssigneePicker who={who} setWho={setWho} collabId={collabId} setCollabId={setCollabId} team={team} collaborators={collaborators} testid="job-ms-assignee" />
        </div>
        <div className="min-w-0">
          <div className="kicker mb-1">scadenza</div>
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} data-testid="job-milestone-due-input" className={`${field} w-full`} />
        </div>
        {!isNew && m.original_due_date && m.original_due_date !== m.due_date && (
          <div className="text-[12px] text-white/55">Prima scadenza: {shortDay(m.original_due_date)}</div>
        )}
        {m.status === "done" && (
          <div>
            <div className="kicker mb-1">fatta il</div>
            <input type="date" value={doneDate} onChange={(e) => setDoneDate(e.target.value)} data-testid="job-milestone-done-date" className={`${field} w-full`} />
          </div>
        )}
        <div className="flex justify-end gap-2">
          {!isNew && (
            <button onClick={del} data-testid="job-milestone-delete" className="mr-auto px-3 py-2 rounded-full text-sm text-white/75 hover:bg-white/10 inline-flex items-center gap-1.5">
              <Trash2 size={14} /> Elimina
            </button>
          )}
          <button onClick={onClose} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Annulla</button>
          <button onClick={save} disabled={busy} data-testid="job-milestone-save" className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50">
            {busy ? "Salvo…" : "Salva"}
          </button>
        </div>
        {!isNew && (
          <div className="pt-4 border-t border-white/[0.16]" data-testid="job-milestone-actions">
            <div className="kicker mb-2">azioni correttive</div>
            {(m.corrective_actions || []).map((a) => (
              <div key={a.id} className="py-2 border-b border-white/[0.08] text-[13px] text-white/85">
                {a.text}
                <span className="block text-[11px] text-white/50">
                  {a.by} · {shortDay(a.at.slice(0, 10))}{a.new_due_date ? ` · scadenza ${shortDay(a.old_due_date)} → ${shortDay(a.new_due_date)}` : ""}
                </span>
              </div>
            ))}
            {m.status !== "done" && (
              <div className="mt-2 space-y-2">
                <textarea value={action} onChange={(e) => setAction(e.target.value)} rows={2} data-testid="job-milestone-action-text"
                  placeholder={m.status === "late" ? "Cosa fai per recuperare il ritardo?" : "Es. squadra in più da lunedì"}
                  className="w-full rounded-lg bg-white/10 p-2.5 text-sm text-white placeholder:text-white/40 outline-none" />
                <div className="flex items-center gap-2">
                  <span className="text-[12px] text-white/60 shrink-0">Nuova scadenza</span>
                  <input type="date" value={newDue} onChange={(e) => setNewDue(e.target.value)} data-testid="job-milestone-action-due" className={`${field} flex-1 min-w-0`} />
                  <button onClick={addAction} disabled={busy} data-testid="job-milestone-action-add"
                    className="h-9 px-3 rounded-full text-sm bg-white/15 text-white shrink-0 disabled:opacity-50">Aggiungi</button>
                </div>
              </div>
            )}
            {m.status === "done" && !(m.corrective_actions || []).length && <div className="text-[12px] text-white/50">Nessuna.</div>}
          </div>
        )}
      </div>
    </GlassBottomSheet>
  );
}

// A client: closed it shows only name, address and how many commesse it has (all / active =
// all but the closed ones); the arrow opens it on its commesse.
function ClientCard({ client, commesse, total, active, open, onToggle, onOpen }) {
  return (
    <div data-testid="client-group" data-open={open ? "1" : "0"} className="card-soft p-4 relative">
      <button type="button" onClick={onToggle} className="block w-full text-left pr-8" aria-expanded={open}>
        <span className="flex items-baseline gap-x-3 gap-y-0.5 flex-wrap">
          <span className="font-semibold text-white text-base leading-snug">{client.name || "Cliente senza nome"}</span>
          <span className="inline-flex items-center gap-2.5 text-[12px] text-white/70 whitespace-nowrap" data-testid="client-counts">
            <span className="inline-flex items-center gap-1" title="Commesse totali" data-testid="client-count-total"><Briefcase size={12} /> {total} {total === 1 ? "totale" : "totali"}</span>
            <span className="inline-flex items-center gap-1" title="Commesse attive (tutte tranne le chiuse)" data-testid="client-count-active"><Activity size={12} /> {active} {active === 1 ? "attiva" : "attive"}</span>
          </span>
        </span>
        {client.address && <span className="flex items-center gap-1 text-xs text-white/60 mt-0.5"><MapPin size={11} />{client.address}</span>}
      </button>
      <button type="button" onClick={onToggle} data-testid="expand-client-group" aria-expanded={open}
        aria-label={open ? "Nascondi le commesse" : "Mostra le commesse"}
        className="absolute top-3 right-3 p-1 rounded-full text-white/80 hover:bg-white/10">
        <ChevronDown size={15} className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <div className="mt-3 flex flex-col gap-1.5">
        {commesse.map((c) => (
          <button key={c.id} data-testid="commessa-row" onClick={() => onOpen(c)}
            className="w-full flex items-center gap-2 text-left px-3 py-2.5 rounded-xl bg-white/[0.07] hover:bg-white/[0.12] transition-colors">
            <span className="flex-1 min-w-0">
              <span className="block text-sm text-white truncate">{c.title}</span>
              <span className="block text-[11px] text-white/50">
                {c.entries ? `${c.entries} voc${c.entries === 1 ? "e" : "i"} · ${fmtNum(c.hours_total)} h · ultima ${shortDay(c.last_day)}` : "nessuna voce"}
              </span>
            </span>
            <StatoPill stato={c.stato} />
            <ChevronRight size={14} className="text-white/45 shrink-0" />
          </button>
        ))}
      </div>}
    </div>
  );
}

// The commessa's chat, at the bottom like the Chat section's composer (same liquid glass,
// voice button on the side chosen in Impostazioni). "Chiedi" answers from the commessa's card,
// diary and reports; "Scrivi nel diario" saves what was done (with photos).
function CommessaChat({ commessa, onClose, onSaved }) {
  const [mode, setMode] = useState("ask");
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [photos, setPhotos] = useState([]);
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [composerRef, size] = useMeasure();
  const [micSide] = usePref("micSide");
  const micRight = micSide !== "left";
  const recRef = useRef(null);
  const fileRef = useRef(null);
  const taRef = useRef(null);
  const listRef = useRef(null);

  useEffect(() => { setMessages([]); setText(""); setPhotos([]); }, [commessa.id]);
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" }); }, [messages]);
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [text]);

  const startRec = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported?.("audio/webm") ? "audio/webm" : "";
      const mr = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      const chunks = [];
      mr.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setTranscribing(true);
        try {
          const fd = new FormData();
          fd.append("file", new Blob(chunks, { type: mr.mimeType || "audio/webm" }), "voice.webm");
          fd.append("action", mode === "ask" ? "info_request" : "journal");
          const res = await fetch(`${API}/voice/transcribe`, { method: "POST", body: fd, credentials: "include" });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const t = ((await res.json()).text || "").trim();
          if (t) setText((x) => (x ? `${x} ${t}` : t)); else toast.error("Non ho capito l'audio");
        } catch (e) { toast.error("Trascrizione fallita: " + e.message); }
        finally { setTranscribing(false); }
      };
      mr.start();
      recRef.current = mr;
      setRecording(true);
    } catch { toast.error("Microfono non disponibile"); }
  };
  const stopRec = () => { recRef.current?.stop(); setRecording(false); };

  const pickPhotos = async (files) => {
    for (const f of Array.from(files || [])) {
      if (!f.type.startsWith("image/")) { toast.error(`${f.name}: solo foto`); continue; }
      try { const uri = await fileToDataUri(f); setPhotos((p) => (p.length >= 10 ? p : [...p, uri])); }
      catch (e) { toast.error(`${f.name}: ${e.message}`); }
    }
  };

  // a question or an unclear entry is not saved; materials to take make a reminder ("planned");
  // "usati o da prendere?" is asked with two buttons
  const saveEntry = async (body, images, fromIdx = null, materialChoice = null) => {
    const r = await api.post("/jobs/logs", { text: body, images, commessa_id: commessa.id, ...(materialChoice ? { material_choice: materialChoice } : {}) });
    const ok = r.data.status === "ok" || r.data.status === "planned";
    const ask = r.data.status === "material_doubt" ? { body, images } : null;
    setMessages((ms) => [...ms.map((m, i) => (i === fromIdx ? { ...m, offerSave: false, matAsk: null } : m)),
      { role: "assistant", content: r.data.message, saved: ok, matAsk: ask }]);
    if (ok) onSaved();
  };
  const answerMat = (i, ask, choice) => {
    setBusy(true);
    saveEntry(ask.body, ask.images, i, choice).catch((e) => toast.error(e.response?.data?.detail || "Errore")).finally(() => setBusy(false));
  };

  const send = async () => {
    const body = text.trim() || (mode === "diary" && photos.length ? "Foto dal cantiere" : "");
    if (!body || busy) return;
    const images = mode === "diary" ? photos : [];
    setMessages((ms) => [...ms, { role: "user", content: images.length ? `${body}\n📷 ${images.length} foto` : body, mode }]);
    setText(""); setPhotos([]);
    setBusy(true);
    try {
      if (mode === "diary") {
        await saveEntry(body, images);
      } else {
        const history = messages.filter((m) => m.mode !== "diary" && !m.saved).slice(-8).map((m) => ({ role: m.role, content: m.content }));
        const r = await api.post(`/jobs/commesse/${commessa.id}/ask`, { question: body, history });
        setMessages((ms) => [...ms, { role: "assistant", content: r.data.answer, offerSave: r.data.is_entry ? body : null }]);
      }
    } catch (e) {
      setMessages((ms) => [...ms, { role: "assistant", content: "⚠️ " + (e.response?.data?.detail || "Qualcosa è andato storto") }]);
    } finally { setBusy(false); }
  };

  const modeBtn = (key, Icon, label) => (
    <button onClick={() => setMode(key)} data-testid={`chat-mode-${key}`}
      className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full transition-colors ${mode === key ? "bg-white text-[#403A3C] font-medium" : "bg-white/15 text-white/85 hover:bg-white/20"}`}>
      <Icon size={13} /> {label}
    </button>
  );

  return (
    <div data-testid="commessa-chat"
      className="fixed z-40 left-0 right-0 px-4 md:px-0 md:right-auto md:left-1/2 md:-translate-x-1/2 md:w-[min(720px,calc(100vw-7rem))] bottom-[calc(env(safe-area-inset-bottom,0px)+92px)] md:bottom-6">
      {messages.length > 0 && (
        <div ref={listRef} data-testid="commessa-chat-messages" className="rounded-[22px] p-4 mb-3 max-h-[40vh] overflow-y-auto flex flex-col gap-3 border border-white/15 shadow-xl"
          style={{ background: "color-mix(in srgb, var(--app-bg, #5b2a4c) 88%, transparent)", backdropFilter: "blur(24px)", WebkitBackdropFilter: "blur(24px)" }}>
          {messages.map((m, i) => (
            <div key={i} className={m.role === "user" ? "self-end max-w-[85%]" : "self-start max-w-[92%]"}>
              <div className={`text-sm whitespace-pre-wrap ${m.role === "user" ? "px-3.5 py-2 rounded-2xl bg-white/20 text-white" : "text-white/95"}`}>{m.content}</div>
              {m.matAsk && (
                <div className="mt-1.5 flex flex-wrap gap-2" data-testid="chat-mat-choices">
                  <button onClick={() => answerMat(i, m.matAsk, "usato")} disabled={busy} data-testid="chat-mat-used"
                    className="text-xs px-3 py-1.5 rounded-full bg-white/15 hover:bg-white/25 text-white disabled:opacity-50">🧰 Usati oggi</button>
                  <button onClick={() => answerMat(i, m.matAsk, "da_prendere")} disabled={busy} data-testid="chat-mat-plan"
                    className="text-xs px-3 py-1.5 rounded-full bg-white/15 hover:bg-white/25 text-white disabled:opacity-50">📌 Da prendere</button>
                </div>
              )}
              {m.offerSave && (
                <button onClick={() => { setBusy(true); saveEntry(m.offerSave, [], i).catch((e) => toast.error(e.response?.data?.detail || "Errore")).finally(() => setBusy(false)); }}
                  disabled={busy} data-testid="chat-save-entry"
                  className="mt-1.5 inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full bg-white/15 hover:bg-white/25 text-white disabled:opacity-50">
                  <NotebookPen size={12} /> Salva nel diario
                </button>
              )}
            </div>
          ))}
          {busy && <Loader2 size={16} className="animate-spin text-white/70" />}
        </div>
      )}
      <div className="flex items-center gap-2 mb-2">
        {modeBtn("ask", MessageCircle, "Chiedi")}
        {modeBtn("diary", NotebookPen, "Scrivi nel diario")}
        <button onClick={onClose} title="Chiudi la chat" aria-label="Chiudi la chat" data-testid="commessa-chat-close"
          className="ml-auto h-8 w-8 rounded-full flex items-center justify-center bg-white/15 text-white hover:bg-white/25"><X size={15} /></button>
      </div>
      <div ref={composerRef} className={`relative flex items-start ${micRight ? "flex-row-reverse" : ""}`} style={{ gap: LIQUID_GAP }}>
        <LiquidGlass d={size.w ? liquidPath(size.w, size.h, !micRight, true) : null} width={size.w} height={size.h} />
        <button onClick={recording ? stopRec : startRec} disabled={transcribing} data-testid="commessa-chat-mic"
          title={recording ? "Ferma" : "Detta"} aria-label={recording ? "Ferma" : "Detta"}
          className="relative h-16 w-16 shrink-0 rounded-full flex items-center justify-center text-white active:scale-95 transition-transform">
          {recording && <span aria-hidden="true" className="mic-ring absolute inset-1 rounded-full" />}
          {recording && <span aria-hidden="true" className="mic-rec absolute inset-1 rounded-full" />}
          {transcribing ? <Loader2 size={20} className="animate-spin relative" /> : recording ? <Square size={16} fill="currentColor" className="relative" /> : <Mic size={22} strokeWidth={1.8} />}
        </button>
        <div className="relative flex-1 min-w-0 min-h-[128px] flex flex-col pl-5 pr-3 pt-3 pb-3">
          <textarea ref={taRef} value={text} onChange={(e) => setText(e.target.value)} rows={1} data-testid="commessa-chat-text"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && window.matchMedia("(min-width: 768px)").matches) { e.preventDefault(); send(); } }}
            placeholder={mode === "ask" ? `Chiedi su «${commessa.title}»: ore, materiali, cosa manca…` : "Cosa avete fatto? Ore, materiali, problemi…"}
            className="w-full bg-transparent border-0 outline-none resize-none text-[15px] leading-relaxed py-1 text-white placeholder:text-white/70 no-scrollbar" />
          {photos.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-1">
              {photos.map((p, i) => (
                <div key={i} className="relative h-12 w-12 rounded-lg overflow-hidden">
                  <img src={p} alt="" className="h-full w-full object-cover" />
                  <button onClick={() => setPhotos((xs) => xs.filter((_, j) => j !== i))} className="absolute top-0.5 right-0.5 h-4 w-4 rounded-full bg-black/60 flex items-center justify-center"><X size={10} /></button>
                </div>
              ))}
            </div>
          )}
          <div className="mt-auto pt-1 flex items-center gap-1">
            <span className="flex-1" />
            {mode === "diary" && (
              <button onClick={() => fileRef.current?.click()} title="Foto" aria-label="Foto" className="p-2 rounded-full text-white/90 hover:bg-white/15">
                <Camera size={19} />
              </button>
            )}
            <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={(e) => { pickPhotos(e.target.files); e.target.value = ""; }} />
            <button onClick={send} disabled={busy || recording || transcribing || (!text.trim() && !(mode === "diary" && photos.length))}
              data-testid="commessa-chat-send" title="Invia" aria-label="Invia"
              style={{ background: "rgba(255,255,255,0.22)", boxShadow: "inset 0 1px 1px rgba(255,255,255,0.6)" }}
              className="h-10 w-10 rounded-[10px] flex items-center justify-center text-white disabled:opacity-60">
              {busy ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function JobDiaryPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [commesse, setCommesse] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [q, setQ] = useState("");
  // level: "clients" -> "commessa" (its card) -> "diary"; a link (chat, Liste) opens the diary
  const linked = location.state?.commessa || new URLSearchParams(location.search).get("commessa") || null;
  const [level, setLevel] = useState(linked ? "diary" : "clients");
  const [selectedId, setSelectedId] = useState(linked);
  const [detail, setDetail] = useState(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [todoEditing, setTodoEditing] = useState(null);   // {} = new activity
  const [msEditing, setMsEditing] = useState(null);       // {} = new milestone
  const [contactsOpen, setContactsOpen] = useState(false);
  const [siteOpen, setSiteOpen] = useState(false);
  const [viewer, setViewer] = useState(null);   // {log, photo}
  const [section, setSection] = useState("diario");
  const [period, setPeriod] = useState({ key: "30" });
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [menu, setMenu] = useState(null);       // "stato" | "periodo" | "collab"
  // Admin: the collaborators (Telegram only) enabled on this commessa
  const { user: me } = useAuth();
  const isAdmin = me?.role === "admin";
  const [collabs, setCollabs] = useState(null);
  const loadCollabs = (id) => api.get(`/jobs/commesse/${id}/collaborators`).then((r) => setCollabs(r.data || [])).catch(() => setCollabs([]));
  useEffect(() => { if (isAdmin && selectedId) loadCollabs(selectedId); else setCollabs(null); }, [isAdmin, selectedId]); // eslint-disable-line react-hooks/exhaustive-deps
  const toggleCollab = async (x) => {
    setCollabs((cs) => cs.map((c) => (c.id === x.id ? { ...c, enabled: !x.enabled } : c)));
    try { await api.put(`/jobs/commesse/${selectedId}/collaborators/${x.id}`, { enabled: !x.enabled }); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); loadCollabs(selectedId); }
  };
  const [openClients, setOpenClients] = useState(() => new Set());   // client cards opened with the arrow
  const toggleClient = (id) => setOpenClients((cur) => {
    const next = new Set(cur);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const swipeX = useRef(null);

  const loadList = async () => {
    try { setCommesse((await api.get("/jobs/commesse")).data || []); }
    catch { toast.error("Errore nel caricamento delle commesse"); }
    finally { setLoaded(true); }
  };
  const loadDetail = async (id, p = period) => {
    if (!id) { setDetail(null); return; }
    const { from, to } = periodRange(p);
    const params = {};
    if (from) params.date_from = from;
    if (to) params.date_to = to;
    try { setDetail((await api.get(`/jobs/commesse/${id}`, { params })).data); }
    catch (e) {
      setDetail(null);
      if (e.response?.status === 404) { setSelectedId(null); setLevel("clients"); toast.error("Commessa non trovata"); }
    }
  };
  const reload = () => Promise.all([loadDetail(selectedId), loadList()]);
  useEffect(() => { loadList(); }, []);
  useEffect(() => { loadDetail(selectedId); }, [selectedId, period]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setSection("diario"); setMenu(null); setPeriod({ key: "30" }); }, [selectedId]);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [level, selectedId]);
  useEffect(() => { if (level === "clients") setChatOpen(false); }, [level]);

  // one card per client, its commesse in state order (in corso first, chiuse last)
  const groups = useMemo(() => {
    const ql = q.trim().toLowerCase();
    const by = new Map();
    commesse.forEach((c) => {
      if (ql && !`${c.title} ${c.client_name} ${c.address}`.toLowerCase().includes(ql)) return;
      const g = by.get(c.client_item_id) || { id: c.client_item_id, name: c.client_name, address: "", commesse: [], last: "" };
      g.commesse.push(c);
      g.last = [g.last, c.last_day || ""].sort().pop();
      if (!g.address && c.address) g.address = c.address;
      by.set(c.client_item_id, g);
    });
    const out = [...by.values()];
    out.forEach((g) => g.commesse.sort((a, b) => (STATO_ORDER[a.stato] ?? 3) - (STATO_ORDER[b.stato] ?? 3) || (b.last_day || "").localeCompare(a.last_day || "")));
    out.sort((a, b) => (Math.min(...a.commesse.map((c) => STATO_ORDER[c.stato] ?? 3)) - Math.min(...b.commesse.map((c) => STATO_ORDER[c.stato] ?? 3)))
      || b.last.localeCompare(a.last) || (a.name || "").localeCompare(b.name || ""));
    return out;
  }, [commesse, q]);
  // every client's commesse, all and active (all but the closed ones) - whatever the search shows
  const counts = useMemo(() => {
    const m = {};
    commesse.forEach((c) => {
      const x = m[c.client_item_id] || (m[c.client_item_id] = { total: 0, active: 0 });
      x.total += 1;
      if (c.stato !== "chiusa") x.active += 1;
    });
    return m;
  }, [commesse]);

  const openCommessa = (c) => { setSelectedId(c.id); setDetail((d) => (d?.commessa?.id === c.id ? d : null)); setLevel("diary"); };
  const setStato = async (stato) => {
    try { await api.patch(`/jobs/commesse/${selectedId}/stato`, { stato }); await reload(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const delLog = (log) => {
    toast(log.kind === "stato" ? "Togliere questo cambio di stato dal diario?"
      : log.kind === "report" ? "Togliere questa riga dal diario? Il report resta tra i documenti." : "Eliminare questa voce del diario?", {
      action: { label: "Elimina", onClick: async () => {
        try { await api.delete(`/jobs/logs/${log.id}`); await reload(); }
        catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
      } },
    });
  };
  const delPhoto = async () => {
    try { await api.delete(`/jobs/logs/${viewer.log.id}/photos/${viewer.photo.id}`); setViewer(null); await loadDetail(selectedId); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const c = detail?.commessa?.id === selectedId ? detail.commessa : null;
  const t = c ? detail.totals : null;
  const loading = <div className="kicker text-center py-10">caricamento…</div>;

  const back = (label, to) => (
    <button onClick={() => setLevel(to)} data-testid="job-back" className="flex items-center gap-1.5 text-sm text-white/65 hover:text-white mb-3">
      <ArrowLeft size={14} /> {label}
    </button>
  );

  const clientsView = (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 px-3 h-10 rounded-full bg-white/10">
        <Search size={15} className="text-white/60" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cerca cliente o commessa" className="flex-1 bg-transparent text-sm text-white placeholder:text-white/45 outline-none" />
      </div>
      {!loaded ? loading : commesse.length === 0 ? (
        <div className="card-soft p-5 text-sm text-white/75" data-testid="no-commesse">
          Nessuna commessa ancora. Le commesse stanno sotto ogni cliente nella lista <b>Clienti</b>: aggiungile da Liste,
          oppure detta un sopralluogo all'agente Report, o una voce di diario nominando il cliente («oggi dai Rossi…»).
          <button onClick={() => navigate("/dashboard/liste")} className="block mt-3 text-xs px-3 py-1.5 rounded-full bg-white/15">Apri le Liste</button>
        </div>
      ) : groups.length === 0 ? <div className="text-xs text-white/55 px-2">Nessun cliente o commessa trovato.</div> : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 items-start" data-testid="client-groups">
          {groups.map((g) => (
            // while searching, the cards open on the commesse found
            <ClientCard key={g.id} client={g} commesse={g.commesse} total={counts[g.id]?.total || 0} active={counts[g.id]?.active || 0}
              open={!!q.trim() || openClients.has(g.id)} onToggle={() => toggleClient(g.id)} onOpen={openCommessa} />
          ))}
        </div>
      )}
    </div>
  );

  // ===== the diary of one commessa =====
  const secAt = (i) => SECTIONS[(i + SECTIONS.length) % SECTIONS.length];
  const secIdx = Math.max(0, SECTIONS.findIndex((x) => x.key === section));
  const pickSection = (key) => { setSection(key); setMenu(null); };
  const onSwipeStart = (e) => { swipeX.current = e.touches?.[0]?.clientX ?? null; };
  const onSwipeEnd = (e) => {
    if (swipeX.current == null) return;
    const dx = (e.changedTouches?.[0]?.clientX ?? swipeX.current) - swipeX.current;
    swipeX.current = null;
    if (Math.abs(dx) > 40) pickSection(secAt(secIdx + (dx < 0 ? 1 : -1)).key);
  };
  const shownLogs = [...(detail?.logs || [])]
    .sort((a, b) => (b.date || "").localeCompare(a.date || "") || (b.created_at || "").localeCompare(a.created_at || ""))
    .filter((lg) => section === "diario" ? true
    : lg.kind ? false
    : section === "ore" ? lg.hours?.length > 0
    : section === "problemi" ? lg.problems?.length > 0
    : lg.materials?.length > 0);
  // days newest first; the month on its own line above its first day
  const diaryDays = (() => {
    const out = [];
    shownLogs.forEach((lg) => {
      const g = out[out.length - 1];
      if (g && g.day === lg.date) g.logs.push(lg); else out.push({ day: lg.date, logs: [lg] });
    });
    let prevMon = null;
    return out.map((g) => {
      const mon = (g.day || "").slice(0, 7);
      const showMonth = mon !== prevMon;
      prevMon = mon;
      const [y, m, d] = (g.day || "--").split("-").map(Number);
      return { ...g, showMonth, monLabel: `${IT_MONTHS[(m || 1) - 1]}${y !== new Date().getFullYear() ? ` ${y}` : ""}`, dayNum: String(d || "").padStart(2, "0") };
    });
  })();
  const pt = detail?.period_totals;
  const summary = !pt ? "" : section === "ore"
    ? `${fmtNum(pt.hours_total)} h nel periodo${Object.keys(pt.by_person).length ? " · " + Object.entries(pt.by_person).map(([k, v]) => `${k} ${fmtNum(v)} h`).join(" · ") : ""}`
    : section === "problemi" ? `${pt.problems.length} ${pt.problems.length === 1 ? "segnalazione" : "segnalazioni"} nel periodo`
    : section === "materiali" ? (pt.materials.map(matLabel).join(" · ") || "Nessun materiale nel periodo") : "";
  const range = periodRange(period);
  const rangeFrom = range.from || detail?.first_day;
  const rangeTo = range.to || todayIso();
  const nEntries = shownLogs.filter((lg) => !lg.kind).length;
  const docs = detail?.docs || { total: 0 };
  const applyCustom = () => {
    if (!customFrom || !customTo) { toast.error("Scegli le due date"); return; }
    setPeriod({ key: "custom", from: customFrom <= customTo ? customFrom : customTo, to: customFrom <= customTo ? customTo : customFrom });
    setMenu(null);
  };
  const delFromEdit = (log) => { setEditing(null); delLog(log); };
  const milestones = detail?.milestones || [];
  const msSum = detail?.milestones_summary || { total: 0, done: 0, late: 0 };
  const toggleMilestone = async (m) => {
    try { await api.patch(`/jobs/milestones/${m.id}`, { done: m.status !== "done" }); await loadDetail(selectedId); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const todos = detail?.todos || [];
  const openTodos = todos.filter((x) => !x.done).length;
  const toTake = todos.filter((x) => x.kind === "materiale" && !x.done);
  const toggleTodo = async (todo) => {
    try { await api.patch(`/jobs/todos/${todo.id}`, { done: !todo.done }); await loadDetail(selectedId); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const diaryView = !c ? loading : (
    <div className="relative max-w-xl" data-testid="commessa-detail">
      {/* only the commessa's name; the arrow goes back to its card */}
      <div className="flex items-center gap-2.5">
        <button onClick={() => setLevel("clients")} data-testid="job-back" aria-label="Torna ai clienti"
          className="h-[30px] w-[30px] shrink-0 rounded-full flex items-center justify-center text-white lg-frost">
          <ArrowLeft size={16} />
        </button>
        <h1 className="min-w-0 flex-1 text-[17px] font-semibold text-white truncate" data-testid="commessa-title">{c.title}</h1>
      </div>

      {/* the commessa in one row that scrolls sideways: state, hours, reports, documents, then
          the card's details (site, dates, phone, e-mail) */}
      <div className="mt-4 -mx-4 px-4 flex gap-7 overflow-x-auto no-scrollbar snap-x snap-mandatory scroll-px-4" data-testid="commessa-totals">
        <InfoCard icon={CircleDot} label="Stato" value={capFirst(c.stato || "senza stato")} testid="glance-stato"
          ariaLabel="Cambia lo stato della commessa" onClick={() => setMenu((m) => (m === "stato" ? null : "stato"))} />
        {(detail.on_site || []).length > 0 && (
          <InfoCard icon={HardHat} label="In cantiere ora" testid="glance-on-site" ariaLabel="Chi sta lavorando ora in cantiere"
            value={detail.on_site.map((x) => x.name.split(" ")[0]).join(", ")}
            note={`dalle ${hhmmOf(detail.on_site[0].since)}${detail.on_site.some((x) => x.far) ? " · ⚠️ lontano" : ""}`} />
        )}
        <InfoCard icon={Clock} label="Ore" value={`${fmtNum(t.hours_total)} h`} testid="glance-ore" ariaLabel="Mostra le ore" onClick={() => pickSection("ore")} />
        {detail.economics && (
          <InfoCard icon={Euro} label="Costi" value={eur(detail.economics.cost_total)} testid="glance-costi" ariaLabel="Mostra costi e margine"
            note={detail.economics.budget ? `${Math.round(detail.economics.used_pct || 0)}% del preventivo` : ""} onClick={() => pickSection("costi")} />
        )}
        <InfoCard icon={Flag} label="Milestone" value={msSum.total ? `${msSum.done}/${msSum.total}` : "nessuna"} testid="glance-milestone"
          ariaLabel="Mostra le milestone" onClick={() => pickSection("milestone")}
          note={msSum.late ? `${msSum.late} in ritardo` : msSum.next ? `prossima ${shortDay(msSum.next.due_date)}` : ""} />
        <InfoCard icon={AlertTriangle} label="Segnalazioni" value={String(t.problems.length)} testid="glance-problemi" ariaLabel="Mostra i problemi"
          onClick={() => pickSection("problemi")} note={t.problems.length ? `ultima ${shortDay(t.problems.map((x) => x.date || "").sort().pop())}` : ""} />
        <InfoCard icon={FileText} label="Documenti" value={String(docs.total)} testid="glance-documenti" ariaLabel={`${docs.photos || 0} foto e ${docs.reports || 0} report`} />
        <InfoCard icon={Contact} label="Contatti" value={String((detail.contacts || []).length)} testid="glance-contatti"
          ariaLabel="Contatti utili della commessa" onClick={() => setContactsOpen(true)}
          note={(detail.contacts || []).slice(0, 2).map((x) => x.role || x.name).join(", ")} />
        <InfoCard icon={MapPin} label="Cantiere" value={c.address || "non indicato"} testid="info-cantiere"
          onClick={() => setSiteOpen(true)} ariaLabel="Il cantiere: indirizzo e posizione per le presenze" />
        <InfoCard icon={CalendarDays} label="Date" testid="info-date"
          value={c.data_inizio ? `${shortDay(c.data_inizio)} → ${c.data_fine ? shortDay(c.data_fine) : "in corso"}` : "non indicate"} />
        {c.client_phone && <InfoCard icon={Phone} label="Telefono" value={c.client_phone} href={`tel:${c.client_phone}`} testid="info-telefono" ariaLabel={`Chiama ${c.client_name}`} />}
        {c.client_email && <InfoCard icon={Mail} label="Email" value={c.client_email} href={`mailto:${c.client_email}`} testid="info-email" ariaLabel={`Scrivi a ${c.client_name}`} />}
        {isAdmin && collabs && (
          <InfoCard icon={HardHat} label="Collaboratori" value={String(collabs.filter((x) => x.enabled).length)} testid="info-collaboratori"
            ariaLabel="Scegli i collaboratori abilitati su questa commessa" onClick={() => setMenu((m) => (m === "collab" ? null : "collab"))} />
        )}
      </div>

      {/* the section, like the agent's name in the chat: the chosen one in the middle (tone on
          tone, brighter than the two at its sides); swipe or tap a side one to change */}
      <div className="mt-7 -mx-4 h-[46px] flex items-center justify-center gap-[22px] overflow-hidden select-none" data-testid="section-carousel"
        onTouchStart={onSwipeStart} onTouchEnd={onSwipeEnd}
        style={{ WebkitMaskImage: "linear-gradient(to right, transparent 0, #000 18%, #000 82%, transparent 100%)", maskImage: "linear-gradient(to right, transparent 0, #000 18%, #000 82%, transparent 100%)" }}>
        <button type="button" onClick={() => pickSection(secAt(secIdx - 1).key)} className="flex-1 basis-0 text-right text-[15px] font-medium text-white/30">{secAt(secIdx - 1).label}</button>
        <h2 className="shrink-0 m-0 text-[30px] font-semibold tracking-tight text-white/[0.68]" data-testid="section-current"
          style={{ textShadow: "0 2px 16px rgba(60,10,60,0.18)" }}>{secAt(secIdx).label}</h2>
        <button type="button" onClick={() => pickSection(secAt(secIdx + 1).key)} className="flex-1 basis-0 text-left text-[15px] font-medium text-white/30">{secAt(secIdx + 1).label}</button>
      </div>

      {/* Costi, Milestone and To Do: their own content instead of the period and the days */}
      {section === "costi" ? (
        <CostsView commessaId={c.id} onChanged={() => loadDetail(selectedId)} />
      ) : section === "milestone" ? (
        <>
          <div className="mt-1.5 flex items-center justify-center gap-2.5">
            <button type="button" onClick={() => setMsEditing({})} data-testid="job-milestone-add" aria-label="Nuova milestone"
              className="h-[34px] flex items-center gap-2 text-white/90 active:opacity-70 whitespace-nowrap">
              <Plus size={17} />
              <span className="text-[12px] font-medium tracking-[0.16em] uppercase text-white/85">Nuova milestone</span>
            </button>
          </div>
          {msSum.total > 0 && (
            <div className="mt-0.5 text-center text-[11.5px] text-white/60" data-testid="job-milestone-count">
              {msSum.done}/{msSum.total} fatte
              {msSum.late ? <span style={{ color: LATE }}> · {msSum.late} in ritardo</span> : null}
              {msSum.done > 0 && <span data-testid="job-milestone-delays"> · {msSum.on_time} di {msSum.done} in tempo{msSum.avg_delay ? `, ritardo medio ${String(msSum.avg_delay).replace(".", ",")} g` : ""}</span>}
            </div>
          )}
          <div className="mt-3" data-testid="job-milestones">
            {milestones.map((m) => <MilestoneRow key={m.id} m={m} onToggle={toggleMilestone} onOpen={setMsEditing} />)}
            {milestones.length === 0 && (
              <div className="py-6 border-t border-white/[0.16] text-[13px] text-white/70" data-testid="job-milestones-empty">
                Nessuna milestone. Tocca «Nuova milestone» per segnare le tappe del lavoro: cosa, chi la esegue ed entro quando.
                Ti ricordo le scadenze su Telegram e, se una va in ritardo, puoi scrivere l'azione correttiva.
              </div>
            )}
          </div>
        </>
      ) : section === "todo" ? (
        <>
          <div className="mt-1.5 flex items-center justify-center gap-2.5">
            <button type="button" onClick={() => setTodoEditing({})} data-testid="job-todo-add" aria-label="Nuova attività"
              className="h-[34px] flex items-center gap-2 text-white/90 active:opacity-70">
              <Plus size={17} />
              <span className="text-[12px] font-medium tracking-[0.16em] uppercase text-white/85">Nuova attività</span>
            </button>
            <span className="text-[12px] tracking-[0.16em] uppercase text-white/55" data-testid="job-todo-count">· {openTodos} da fare</span>
          </div>
          <div className="mt-3" data-testid="job-todos">
            {todos.map((x) => <TodoRow key={x.id} todo={x} onToggle={toggleTodo} onOpen={setTodoEditing} />)}
            {todos.length === 0 && (
              <div className="py-6 border-t border-white/[0.16] text-[13px] text-white/70" data-testid="job-todos-empty">
                Nessuna attività in programma. Tocca «Nuova attività» per segnare cosa c'è da fare, chi se ne occupa ed entro quando.
              </div>
            )}
          </div>
        </>
      ) : (<>
      {section === "materiali" && toTake.length > 0 && (
        <div className="mt-1 mb-4" data-testid="materials-to-take">
          <div className="text-[10px] uppercase tracking-widest text-white/55 text-center mb-1">da prendere</div>
          {toTake.map((x) => <TodoRow key={x.id} todo={x} onToggle={toggleTodo} onOpen={setTodoEditing} />)}
        </div>
      )}
      {/* the period */}
      <div className="mt-1.5 flex items-center justify-center gap-2.5">
        <button type="button" onClick={() => setMenu((m) => (m === "periodo" ? null : "periodo"))} data-testid="period-btn" aria-label="Scegli il periodo"
          className="h-[34px] w-[30px] flex items-center justify-center text-white/90 active:opacity-70">
          <CalendarDays size={17} />
        </button>
        <span className="text-[12px] font-medium tracking-[0.16em] uppercase text-white/85" data-testid="period-label">
          {rangeFrom ? `${rangeDay(rangeFrom)} — ${rangeDay(rangeTo, true)}` : "nessuna voce"}
        </span>
        <span className="text-[12px] tracking-[0.16em] uppercase text-white/55">· {nEntries === 1 ? "1 voce" : `${nEntries} voci`}</span>
      </div>
      {summary && <div className="mt-2.5 text-[12.5px] text-white/80 text-center" data-testid="section-summary">{summary}</div>}

      {/* the days */}
      <div className="mt-1.5" data-testid="diary-days">
        {diaryDays.map((g) => (
          <React.Fragment key={g.day}>
            {g.showMonth && (
              <div className="grid grid-cols-[34px_minmax(0,1fr)] gap-x-3 pt-4 pb-1.5">
                <div className="text-[11px] font-medium tracking-[0.18em] uppercase text-white/60 whitespace-nowrap">{g.monLabel}</div>
                <div />
              </div>
            )}
            <div className="grid grid-cols-[34px_minmax(0,1fr)] gap-x-3 py-3 border-t border-white/[0.16]">
              <div className="text-[14px] font-medium leading-[1.45] text-white/90 tabular-nums">{g.dayNum}</div>
              <div className="flex flex-col gap-3 min-w-0">
                {g.logs.map((lg) => <DiaryLine key={lg.id} log={lg} section={section} me={me?.user_id} onOpen={(lg) => (lg.kind ? delLog(lg) : setEditing(lg))} onPhoto={(log, photo) => setViewer({ log, photo })} />)}
              </div>
            </div>
          </React.Fragment>
        ))}
        {diaryDays.length === 0 && (
          <div className="py-6 border-t border-white/[0.16] text-[13px] text-white/70" data-testid="diary-empty">
            {section === "diario" ? "Nessuna voce in questo periodo." : "Nessuna voce di questo tipo nel periodo."}
            {period.key !== "all" && (
              <button onClick={() => setPeriod({ key: "all" })} className="block mt-2 text-xs px-3 py-1.5 rounded-full bg-white/15">Mostra tutta la commessa</button>
            )}
            {section === "diario" && (
              <div className="mt-2 text-white/55">Per scrivere tocca il pulsante della chat <MessageCircle size={12} className="inline -mt-0.5" /> sul lato e scegli «Scrivi nel diario».</div>
            )}
          </div>
        )}
      </div>
      </>)}

      {/* state menu and period popup, like the profile menu */}
      {menu && <button type="button" aria-label="Chiudi" className="fixed inset-0 z-30 cursor-default" onClick={() => setMenu(null)} />}
      {menu === "stato" && (
        <div role="menu" aria-label="Stato della commessa" data-testid="stato-menu" className="glass-panel absolute z-40 left-0 top-[112px] w-[236px] py-1">
          {(detail.stati || []).map((s) => {
            const on = s === c.stato;
            return (
              <button key={s} type="button" role="menuitemradio" aria-checked={on} onClick={() => { setMenu(null); if (!on) setStato(s); }}
                className="glass-row w-full flex items-center gap-3.5 px-5 py-3.5 text-left text-[15px] text-white">
                <span className={`h-5 w-5 shrink-0 rounded-full flex items-center justify-center backdrop-blur-md ${on ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
                  {on && <Check size={12} strokeWidth={2.8} />}
                </span>
                <span>{capFirst(s)}</span>
              </button>
            );
          })}
          <div className="px-5 pt-2.5 pb-3 text-[11px] text-white/55 border-t border-white/[0.13]">Il cambio resta scritto nel diario</div>
        </div>
      )}
      {menu === "collab" && collabs && (
        <div role="menu" aria-label="Collaboratori abilitati" data-testid="collab-menu" className="glass-panel absolute z-40 right-0 top-[112px] w-[280px] py-1">
          {collabs.length === 0 && <div className="px-5 py-3.5 text-[13px] text-white/75">Nessun collaboratore: aggiungili in Impostazioni → Collaboratori.</div>}
          {collabs.map((x) => (
            <button key={x.id} type="button" role="menuitemcheckbox" aria-checked={x.enabled} onClick={() => toggleCollab(x)} data-testid={`collab-toggle-${x.id}`}
              className="glass-row w-full flex items-center gap-3.5 px-5 py-3 text-left text-[15px] text-white">
              <span className={`h-5 w-5 shrink-0 rounded-full flex items-center justify-center backdrop-blur-md ${x.enabled ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
                {x.enabled && <Check size={12} strokeWidth={2.8} />}
              </span>
              <span className="min-w-0">
                <span className="block truncate">{x.name}</span>
                {(x.company || x.status !== "active") && (
                  <span className="block text-[11px] text-white/55 truncate">{[x.company, x.status === "invited" ? "non ancora collegato" : x.status === "suspended" ? "sospeso" : ""].filter(Boolean).join(" · ")}</span>
                )}
              </span>
            </button>
          ))}
          <div className="px-5 pt-2.5 pb-3 text-[11px] text-white/55 border-t border-white/[0.13]">Con il pallino possono scrivere e chiedere su questa commessa da Telegram</div>
        </div>
      )}
      {menu === "periodo" && (
        <div role="dialog" aria-label="Periodo da consultare" data-testid="period-menu" className="glass-panel absolute z-40 left-1/2 -translate-x-1/2 top-[236px] w-[300px] pt-1 pb-3.5">
          {PERIODS.map((p) => (
            <button key={p.key} type="button" onClick={() => { setPeriod({ key: p.key }); setMenu(null); }}
              className="glass-row w-full flex items-center gap-3.5 px-5 py-3.5 text-left text-[15px] text-white">
              <span className="flex-1">{p.label}</span>
              {period.key === p.key && <Check size={16} strokeWidth={2.2} />}
            </button>
          ))}
          <div className="grid grid-cols-2 gap-2.5 px-5 pt-3 border-t border-white/[0.13]">
            <label className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase text-white/60">Dal
              <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} data-testid="period-from"
                className="h-9 rounded-xl px-2.5 bg-white/[0.12] text-white text-sm tracking-normal outline-none" />
            </label>
            <label className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase text-white/60">Al
              <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)} data-testid="period-to"
                className="h-9 rounded-xl px-2.5 bg-white/[0.12] text-white text-sm tracking-normal outline-none" />
            </label>
          </div>
          <div className="px-5 pt-3 flex justify-end">
            <button type="button" onClick={applyCustom} data-testid="period-apply" className="h-9 px-[18px] rounded-full bg-white text-[#403A3C] text-[13px] font-semibold">Applica</button>
          </div>
        </div>
      )}
    </div>
  );

  const inCommessa = level !== "clients" && !!selectedId;
  return (
    <div className="w-full" data-testid="job-diary-page" style={chatOpen ? { paddingBottom: "min(62vh, 520px)" } : undefined}>
      {(level !== "diary" || !selectedId) && (
        <div className="flex items-center gap-2 mb-4">
          <NotebookPen size={20} className="text-white/80" />
          <h1 className="text-2xl font-semibold text-white">Diario di commessa</h1>
        </div>
      )}
      {level === "clients" || !selectedId ? clientsView : diaryView}

      {inCommessa && c && !chatOpen && (
        <FloatingGlassButton icon={MessageCircle} label="Chat della commessa: chiedi o scrivi nel diario" testid="commessa-chat-toggle"
          onClick={() => setChatOpen(true)} />
      )}
      {chatOpen && c && <CommessaChat commessa={c} onClose={() => setChatOpen(false)} onSaved={reload} />}
      {contactsOpen && c && (
        <GlassBottomSheet onClose={() => setContactsOpen(false)} testid="contacts-sheet" className="max-h-[80vh] md:left-1/2 md:right-auto md:w-[480px] md:-translate-x-1/2 md:bottom-8">
          <div className="text-lg font-semibold text-white mb-3">Contatti · {c.title}</div>
          <CommessaContacts commessaId={c.id} onChanged={() => loadDetail(selectedId)} />
        </GlassBottomSheet>
      )}
      {siteOpen && c && <SiteSheet commessa={c} geo={detail?.geo} onClose={() => setSiteOpen(false)} onChanged={() => loadDetail(selectedId)} />}
      {msEditing && c && (
        <MilestoneSheet m={msEditing} commessaId={c.id} team={detail?.team || []} collaborators={detail?.collaborators || []} onClose={() => setMsEditing(null)}
          onSaved={async () => { setMsEditing(null); await loadDetail(selectedId); }} />
      )}
      {todoEditing && c && (
        <TodoDialog todo={todoEditing} commessaId={c.id} team={detail?.team || []} collaborators={detail?.collaborators || []} onClose={() => setTodoEditing(null)}
          onSaved={async () => { setTodoEditing(null); await loadDetail(selectedId); }} />
      )}
      {editing && (
        <EditDialog log={editing} onClose={() => setEditing(null)} onDelete={delFromEdit}
          onSaved={async () => { setEditing(null); await reload(); toast.success("Voce aggiornata"); }} />
      )}
      {viewer && (
        <Dialog open onOpenChange={() => setViewer(null)}>
          <DialogContent className="max-w-3xl bg-black/90 p-3" data-testid="job-photo-viewer">
            <img src={photoUrl(viewer.photo.id)} alt="" className="w-full max-h-[75vh] object-contain rounded-lg" />
            <div className="flex items-center gap-3 text-xs text-white/70 px-1">
              {viewer.photo.drive_link && <a href={viewer.photo.drive_link} target="_blank" rel="noreferrer" className="underline">Apri su Drive/OneDrive</a>}
              <button onClick={delPhoto} className="ml-auto inline-flex items-center gap-1 hover:text-white"><Trash2 size={13} /> Elimina foto</button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
