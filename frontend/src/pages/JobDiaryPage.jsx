import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Search, Mic, Square, Camera, Loader2, Clock, Package, AlertTriangle, Trash2, Pencil, X, Plus, MapPin, Phone, Mail,
  NotebookPen, MessageCircle, Send, ChevronRight, ChevronDown, RefreshCw, CalendarDays, CircleDot, FileText, Check, Briefcase, Activity,
  UserRound, HardHat, Euro, Flag, Contact, ListChecks, LayoutTemplate, BookmarkPlus, Copy, Users, Upload, ScrollText } from "lucide-react";
import { api, API } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import GlassBottomSheet from "@/components/GlassBottomSheet";
import InfoCard from "@/components/InfoCard";
import CommessaContacts from "@/components/CommessaContacts";
import ClientUpdatesSheet from "@/components/ClientUpdatesSheet";
import CommessaShareSheet from "@/components/CommessaShareSheet";
import { LiquidGlass, liquidPath, useMeasure, LIQUID_GAP } from "@/components/LiquidDock";
import { usePref } from "@/lib/prefs";
import FloatingGlassButton from "@/components/FloatingGlassButton";
import { useAuth } from "@/auth/AuthContext";
import { MOBILE_BREAKPOINT } from "@/hooks/use-is-mobile";
import SiteMapBand from "@/components/SiteMapBand";
import PresencePill from "@/components/PresencePill";
import OnSiteList from "@/components/OnSiteList";
import { firstName, onSiteSummary } from "@/lib/onSite";
import { stateColor, STATO_ORDER, isClosed, LOST_CATEGORIES } from "@/lib/commessaStati";

// Diario di commessa (verticale artigiano):
//   1. one card per client with its commesse and their state
//   2. a commessa opens its diary: its name, a row of cards that scrolls sideways (state,
//      hours, reports, documents, site, dates, phone, e-mail), the sections in a carousel,
//      the period, the entries by day. Every state change is written in the diary.
// The commessa's chat (ask about it, or write in its diary) opens from the round chat button
// floating on the side and sits at the bottom, like the one in the Chat section.

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
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: stateColor(stato) }} />
      {stato || "senza stato"}
    </span>
  );
}


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
  { key: "pianificazione", label: "Pianificazione" },
  { key: "descrizione", label: "Descrizione" },
  { key: "sopralluogo", label: "Sopralluogo" },
  { key: "preventivo", label: "Preventivo" },
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

// ===== Milestone templates: the steps of a kind of job (ready-made, or saved from a commessa),
// each due N working days after the start; applied to a commessa from a start date.
const tplSpan = (t) => Math.max(0, ...t.steps.map((x) => x.day));
const nextWorkday = (iso) => { const d = new Date(`${iso}T12:00:00`); while ([0, 6].includes(d.getDay())) d.setDate(d.getDate() + 1); return d; };
function addWorkdays(iso, n) {
  const d = nextWorkday(iso);
  for (let left = n; left > 0;) { d.setDate(d.getDate() + 1); if (![0, 6].includes(d.getDay())) left -= 1; }
  return d.toISOString().slice(0, 10);
}

function MilestoneTemplatesSheet({ commessa, onClose, onApplied }) {
  const [lists, setLists] = useState(null);
  const [open, setOpen] = useState(null);   // the template looked at
  const load = async () => {
    try { const r = await api.get("/jobs/milestone-templates"); setLists(r.data); return r.data; }
    catch { setLists({ builtin: [], custom: [] }); return null; }
  };
  useEffect(() => { load(); }, []);
  const row = (t) => (
    <button key={t.id} type="button" onClick={() => setOpen(t)} data-testid="ms-tpl-row" className="w-full text-left py-2.5 border-b border-white/[0.08] last:border-b-0">
      <div className="text-sm text-white font-medium">{t.name}</div>
      <div className="text-[11.5px] text-white/55">{t.steps.length} milestone · circa {tplSpan(t)} giorni lavorativi</div>
    </button>
  );
  return (
    <GlassBottomSheet onClose={onClose} testid="ms-tpl-sheet" className="max-h-[88vh] md:left-1/2 md:right-auto md:w-[520px] md:-translate-x-1/2 md:bottom-8">
      {open ? (
        <TemplateDetail key={open.id} t={open} commessa={commessa} onBack={() => setOpen(null)} onApplied={onApplied}
          onChanged={async (keepId) => { const l = await load(); setOpen(keepId && l ? [...l.custom].find((x) => x.id === keepId) || null : null); }} />
      ) : (
        <>
          <div className="text-lg font-semibold text-white mb-1">Milestone da modello</div>
          <div className="text-xs text-white/55 mb-3">Scegli un modello: le milestone partono dal giorno di inizio che indichi, in giorni lavorativi.</div>
          {lists === null ? <div className="kicker py-2">caricamento…</div> : (
            <>
              {lists.custom.length > 0 && (<><div className="text-[10px] uppercase tracking-widest text-white/50 mt-1">i tuoi modelli</div>{lists.custom.map(row)}</>)}
              <div className="text-[10px] uppercase tracking-widest text-white/50 mt-3">modelli pronti</div>
              {lists.builtin.map(row)}
            </>
          )}
        </>
      )}
    </GlassBottomSheet>
  );
}

function TemplateDetail({ t, commessa, onBack, onApplied, onChanged }) {
  const today = todayIso();
  const [start, setStart] = useState(commessa.data_inizio && commessa.data_inizio >= today ? commessa.data_inizio : today);
  const [steps, setSteps] = useState(t.steps.map((x) => ({ ...x })));
  const [name, setName] = useState(t.name);
  const [busy, setBusy] = useState(false);
  const mine = !t.builtin;
  const dirty = mine && (name !== t.name || JSON.stringify(steps) !== JSON.stringify(t.steps));
  const fail = (e) => toast.error(e.response?.data?.detail || "Errore");
  const apply = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/jobs/commesse/${commessa.id}/milestones/from-template`, { template_id: t.id, start_date: start });
      toast.success(`${r.data.created} milestone aggiunte${r.data.skipped.length ? ` (${r.data.skipped.length} c'erano già)` : ""}`);
      onApplied();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const save = async () => {
    setBusy(true);
    try { await api.patch(`/jobs/milestone-templates/${t.id}`, { name, steps: steps.map((x) => ({ title: x.title, day: Number(x.day) || 0 })) }); toast.success("Modello salvato"); await onChanged(t.id); }
    catch (e) { fail(e); } finally { setBusy(false); }
  };
  const copy = async () => {
    setBusy(true);
    try { const r = await api.post("/jobs/milestone-templates", { name: `${t.name} (mio)`, steps: t.steps }); toast.success("Copiato tra i tuoi modelli: ora puoi modificarlo"); await onChanged(r.data.id); }
    catch (e) { fail(e); } finally { setBusy(false); }
  };
  const del = () => toast(`Eliminare il modello "${t.name}"?`, {
    action: { label: "Elimina", onClick: async () => { try { await api.delete(`/jobs/milestone-templates/${t.id}`); await onChanged(null); } catch (e) { fail(e); } } },
    cancel: { label: "Annulla", onClick: () => {} }, duration: 6000,
  });
  const field = "h-9 rounded-lg bg-white/10 px-2.5 text-sm text-white placeholder:text-white/40 outline-none";
  return (
    <div data-testid="ms-tpl-detail">
      <button type="button" onClick={onBack} className="text-xs text-white/70 inline-flex items-center gap-1 mb-2"><ArrowLeft size={12} /> Modelli</button>
      {mine ? <input value={name} onChange={(e) => setName(e.target.value)} className={`${field} w-full text-base font-semibold mb-2`} data-testid="ms-tpl-name" />
        : <div className="text-lg font-semibold text-white mb-2">{t.name}</div>}
      <div className="flex items-center gap-2 mb-3">
        <span className="kicker">inizio</span>
        <input type="date" value={start} onChange={(e) => setStart(e.target.value)} data-testid="ms-tpl-start" className={`${field} flex-1`} />
      </div>
      <div className="mb-3" data-testid="ms-tpl-steps">
        {steps.map((x, i) => (
          <div key={i} className="flex items-center gap-2 py-1.5 border-b border-white/[0.08] last:border-b-0">
            {mine ? (
              <>
                <input value={x.title} onChange={(e) => setSteps((xs) => xs.map((y, j) => (j === i ? { ...y, title: e.target.value } : y)))} className={`${field} flex-1 min-w-0`} />
                <input value={x.day} onChange={(e) => setSteps((xs) => xs.map((y, j) => (j === i ? { ...y, day: e.target.value.replace(/\D/g, "") } : y)))}
                  inputMode="numeric" aria-label="giorni lavorativi dall'inizio" className={`${field} w-14 text-center`} />
                <button type="button" onClick={() => setSteps((xs) => xs.filter((_, j) => j !== i))} aria-label="Togli" className="p-1.5 text-white/55 hover:text-white"><X size={13} /></button>
              </>
            ) : <span className="text-sm text-white/90 flex-1 min-w-0">{x.title}</span>}
            <span className="text-[11.5px] text-white/55 w-[58px] text-right shrink-0">{shortDay(addWorkdays(start || today, Number(x.day) || 0))}</span>
          </div>
        ))}
        {mine && <button type="button" onClick={() => setSteps((xs) => [...xs, { title: "", day: (xs.at(-1)?.day ?? 0) }])} className="mt-1.5 text-xs text-white/75 inline-flex items-center gap-1"><Plus size={12} /> aggiungi</button>}
        {mine && <div className="text-[11px] text-white/45 mt-1">Il numero è la scadenza in giorni lavorativi dall'inizio.</div>}
      </div>
      <div className="flex flex-wrap justify-end gap-2">
        {mine ? (
          <>
            <button onClick={del} className="mr-auto px-3 py-2 rounded-full text-sm text-white/75 hover:bg-white/10 inline-flex items-center gap-1.5"><Trash2 size={14} /> Elimina</button>
            {dirty && <button onClick={save} disabled={busy} data-testid="ms-tpl-save" className="px-4 py-2 rounded-full text-sm bg-white/15 text-white disabled:opacity-50">Salva modifiche</button>}
          </>
        ) : (
          <button onClick={copy} disabled={busy} data-testid="ms-tpl-copy" className="mr-auto px-3 py-2 rounded-full text-sm text-white/80 hover:bg-white/10 inline-flex items-center gap-1.5"><Copy size={14} /> Copia e modifica</button>
        )}
        <button onClick={apply} disabled={busy || dirty} data-testid="ms-tpl-apply" className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50">
          {busy ? "…" : "Aggiungi alla commessa"}
        </button>
      </div>
    </div>
  );
}

function SaveTemplateSheet({ commessa, onClose }) {
  const [name, setName] = useState(commessa.title || "");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/jobs/commesse/${commessa.id}/milestone-templates`, { name });
      toast.success(`Modello «${r.data.name}» salvato: lo trovi in «Da modello» in tutte le commesse`);
      onClose();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); } finally { setBusy(false); }
  };
  return (
    <GlassBottomSheet onClose={onClose} testid="ms-tpl-save-sheet" className="max-h-[60vh] md:left-1/2 md:right-auto md:w-[440px] md:-translate-x-1/2 md:bottom-8">
      <div className="text-lg font-semibold text-white mb-1">Salva come modello</div>
      <div className="text-xs text-white/55 mb-3">Le milestone di questa commessa diventano un modello da riusare: le scadenze diventano giorni lavorativi dall'inizio.</div>
      <input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="Nome (es. Bagno chiavi in mano)" data-testid="ms-tpl-save-name"
        className="h-10 w-full rounded-xl bg-white/10 px-3 text-sm text-white placeholder:text-white/40 outline-none" />
      <div className="flex justify-end gap-2 mt-4">
        <button onClick={onClose} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Annulla</button>
        <button onClick={save} disabled={busy || !name.trim()} data-testid="ms-tpl-save-confirm" className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50">{busy ? "Salvo…" : "Salva"}</button>
      </div>
    </GlassBottomSheet>
  );
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
          {full && !isEvent && (log.hours?.length > 0 || log.hours_pending?.length > 0) && <Clock size={11} strokeWidth={2} />}
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
      {full && !isEvent && (log.hours_pending?.length > 0 || log.hours_review || log.hours_replaced_by) && (
        <span className="mt-1 block text-[12px] text-white/60" data-testid="job-hours-review">
          {log.hours_pending?.length > 0 ? `⏳ ${hoursLineOf(log)}${reviewDetail(log)}`
            : log.hours_replaced_by ? "Ore sostituite da una correzione approvata"
            : log.hours_review?.status === "rejected" ? `Ore non approvate (${(log.hours_review.rejected_hours || []).map((h) => `${h.who} ${fmtNum(h.hours)} h`).join(" · ")})`
            : log.hours_review?.status === "approved" ? `✓ Ore approvate${log.hours_review.decided_by ? ` da ${log.hours_review.decided_by}` : ""}${reviewDetail(log)}` : ""}
        </span>
      )}
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
const hoursLineOf = (log) => (log.hours?.length ? log.hours : log.hours_pending || []).map((h) => `${h.who} ${fmtNum(h.hours)} h`).join(" · ")
  + (log.hours_pending?.length ? " da approvare" : "");
// "(dalle 07:58 alle 17:10, al posto delle 10 h segnate con 📍)"
const reviewDetail = (log) => {
  const rv = log.hours_review || {};
  const bits = rv.start && rv.end ? [`dalle ${rv.start} alle ${rv.end}`] : [];
  const old = (rv.replaced_hours || []).reduce((n, h) => n + h.hours, 0);
  if (rv.replaces_log_id) bits.push(old ? `al posto delle ${fmtNum(old)} h segnate con 📍` : "al posto della presenza segnata con 📍");
  return bits.length ? ` (${bits.join(", ")})` : "";
};

// hours a collaborator wrote in a note: not counted until the owner approves them
function HoursToApprove({ log, onDone }) {
  const [busy, setBusy] = useState(false);
  const decide = async (approve) => {
    setBusy(true);
    try {
      await api.post(`/jobs/logs/${log.id}/hours-review`, { approve });
      toast.success(approve ? "Ore approvate: ora contano" : "Ore non approvate");
      onDone();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };
  return (
    <div className="grid grid-cols-[34px_minmax(0,1fr)] gap-x-3 py-3 border-t border-white/[0.16]" data-testid="hours-to-approve">
      <Clock size={16} strokeWidth={2} className="mt-[2px] text-white/70" />
      <div className="min-w-0">
        <span className="flex items-center gap-1.5 text-[12.5px] font-medium text-white/60">
          <span>{log.author_name}</span>{log.author_company && <span className="text-[11px] text-white/40">· {log.author_company}</span>}
          <span className="text-[11px] text-white/40">· {shortDay(log.date)}</span>
        </span>
        <span className="block mt-[3px] text-[14.5px] font-medium leading-snug text-white">
          {(log.hours_pending || []).map((h) => `${h.who} ${fmtNum(h.hours)} h`).join(" · ")}{reviewDetail(log)}
        </span>
        {log.text && <span className="block mt-[3px] text-[12.5px] leading-[1.45] text-white/60 whitespace-pre-wrap">{log.text}</span>}
        <div className="mt-2 flex gap-2">
          <button type="button" disabled={busy} onClick={() => decide(true)} data-testid="hours-approve"
            className="px-3.5 py-1.5 rounded-full text-[12.5px] bg-white text-[#403A3C] font-semibold disabled:opacity-50">Approva</button>
          <button type="button" disabled={busy} onClick={() => decide(false)} data-testid="hours-reject"
            className="px-3.5 py-1.5 rounded-full text-[12.5px] bg-white/15 text-white disabled:opacity-50">Non approvare</button>
        </div>
      </div>
    </div>
  );
}

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
// 2849.5 -> "2.849,50": the thousands' dot always (Italian formatting leaves it out on four digits)
const groupIt = (x) => {
  const [i, d] = Math.abs(x).toFixed(x % 1 ? 2 : 0).split(".");
  return `${x < 0 ? "-" : ""}${i.replace(/\B(?=(\d{3})+(?!\d))/g, ".")}${d ? `,${d}` : ""}`;
};
const eur = (x) => (x === null || x === undefined ? "—" : `${groupIt(x)}\u00a0€`);
const parseMoney = (v) => {
  const t = String(v ?? "").replace(/[€\s]/g, "").replace(/\.(?=\d{3}(\D|$))/g, "").replace(",", ".");
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) && n >= 0 ? n : NaN;
};

// A small amount field: saved when it loses focus (or Enter), only if it changed. The number is
// shown with the thousands' dot; its unit (€, €/h, €/m...) stays beside the field, always.
function MoneyInput({ value, onSave, placeholder, testid, unit = "€", wide = false }) {
  const shown = value === null || value === undefined ? "" : groupIt(value);
  const [v, setV] = useState(shown);
  useEffect(() => { setV(shown); }, [shown]);
  const commit = () => {
    const n = parseMoney(v);
    if (Number.isNaN(n)) { toast.error("Importo non valido"); setV(shown); return; }
    if ((n ?? null) !== (value ?? null)) onSave(n);
  };
  return (
    <span className="shrink-0 inline-flex items-center gap-1.5">
      <input value={v} onChange={(e) => setV(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
        inputMode="decimal" placeholder={placeholder} data-testid={testid}
        className={`h-8 ${wide ? "w-28" : "w-[72px]"} rounded-lg bg-white/10 px-2 text-right text-[13px] text-white placeholder:text-white/35 outline-none`} />
      <span className="w-9 text-[12px] text-white/60 whitespace-nowrap" data-testid={testid ? `${testid}-unit` : undefined}>{unit}</span>
    </span>
  );
}

// Costi: open / closed lists of manodopera and materiali, kept on this device
const COSTS_OPEN_KEY = "maipal.costs.open";
const readOpen = () => { try { return { labor: true, materials: true, ...JSON.parse(localStorage.getItem(COSTS_OPEN_KEY) || "{}") }; } catch { return { labor: true, materials: true }; } };

// ===== A commessa lost: its reason is required (category + words), then the state changes
function LostSheet({ commessa, onClose, onSaved }) {
  const [cat, setCat] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await api.patch(`/jobs/commesse/${commessa.id}/stato`, { stato: "persa", lost_category: cat, lost_reason: text }); toast.success("Commessa segnata come persa"); onSaved(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };
  return (
    <GlassBottomSheet onClose={onClose} testid="lost-sheet" className="max-h-[85vh] md:left-1/2 md:right-auto md:w-[480px] md:-translate-x-1/2 md:bottom-8">
      <div className="kicker">· commessa persa</div>
      <div className="text-lg font-semibold text-white mt-1">Perché non è stata accettata?</div>
      <div className="mt-3 flex flex-wrap gap-2" data-testid="lost-categories">
        {LOST_CATEGORIES.map(([k, label]) => (
          <button key={k} type="button" onClick={() => setCat(k)} data-testid={`lost-${k}`}
            className={`px-3.5 py-1.5 rounded-full text-[13px] ${cat === k ? "bg-white text-[#403A3C] font-semibold" : "bg-white/10 text-white"}`}>{label}</button>
        ))}
      </div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} data-testid="lost-text" placeholder={cat === "altro" ? "Scrivi il motivo" : "Dettagli (facoltativi)"}
        className="mt-3 w-full rounded-2xl bg-white/10 px-3.5 py-3 text-[14px] text-white placeholder:text-white/40 outline-none resize-y" />
      <div className="text-[11.5px] text-white/55 mt-1">Lo storico dei motivi ti aiuta con i prossimi preventivi.</div>
      <div className="mt-4 flex gap-2">
        <button type="button" onClick={save} disabled={busy || !cat || (cat === "altro" && !text.trim())} data-testid="lost-save"
          className="flex-1 h-11 rounded-full bg-white text-[#403A3C] text-[14px] font-semibold inline-flex items-center justify-center gap-1.5 disabled:opacity-50">
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Segna come persa
        </button>
        <button type="button" onClick={onClose} className="h-11 px-5 rounded-full lg-glass text-[14px] text-white">Annulla</button>
      </div>
    </GlassBottomSheet>
  );
}

// ===== Every change of the commessa's parameters: who, when, from what to what
// Closing a commessa with something still open: listed, and closed only if confirmed (AUT-CHI-01)
function CloseCheckSheet({ check, onClose, onConfirm }) {
  const [busy, setBusy] = useState(false);
  const block = (title, rows) => rows?.length ? (
    <div className="mt-3">
      <div className="text-[10px] uppercase tracking-widest text-white/55 mb-1">{title}</div>
      {rows.map((x, i) => <div key={i} className="text-[13.5px] text-white/90 py-0.5">• {x}</div>)}
    </div>
  ) : null;
  return (
    <GlassBottomSheet onClose={onClose} testid="close-check-sheet" className="max-h-[88vh] md:left-1/2 md:right-auto md:w-[520px] md:-translate-x-1/2 md:bottom-8">
      <div className="kicker">· chiudere la commessa?</div>
      <div className="text-[13px] text-white/70 mt-1">Ci sono ancora cose aperte (i lavori extra non approvati restano fuori dal valore). Chiudendo, le attività pianificate vengono annullate, i promemoria si fermano
        e preparo il report finale nella cartella Report.</div>
      {block("problemi aperti", check.problems)}
      {block("attività non svolte", check.activities)}
      {block("lavori extra non approvati", check.extras)}
      <div className="mt-4 flex gap-2">
        <button type="button" disabled={busy} data-testid="close-confirm" onClick={async () => { setBusy(true); await onConfirm(); setBusy(false); }}
          className="flex-1 h-11 rounded-full bg-white text-[#403A3C] text-[14px] font-semibold inline-flex items-center justify-center gap-1.5 disabled:opacity-50">
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Chiudi comunque
        </button>
        <button type="button" onClick={onClose} className="h-11 px-5 rounded-full lg-glass text-[14px] text-white">Annulla</button>
      </div>
    </GlassBottomSheet>
  );
}

function HistorySheet({ rows, onClose }) {
  const val = (v) => (v === null || v === undefined || v === "" ? "—" : String(v));
  return (
    <GlassBottomSheet onClose={onClose} testid="history-sheet" className="max-h-[85vh] md:left-1/2 md:right-auto md:w-[520px] md:-translate-x-1/2 md:bottom-8">
      <div className="kicker">· modifiche della commessa</div>
      <div className="mt-2">
        {rows.length === 0 && <div className="text-[13px] text-white/70 py-3">Nessuna modifica registrata.</div>}
        {rows.map((h) => (
          <div key={h.id} className="py-2.5 border-t border-white/[0.13] first:border-t-0" data-testid="history-row">
            <div className="text-[14px] text-white"><b>{h.field}</b>: {val(h.old)} → {val(h.new)}</div>
            <div className="text-[11.5px] text-white/55">{h.by_name} · {new Date(h.at).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}{h.channel === "telegram" ? " · Telegram" : ""}</div>
          </div>
        ))}
      </div>
    </GlassBottomSheet>
  );
}

// ===== The problems of the commessa: open or solved (by a later note, or by hand), their severity
const SEVERITY = { bassa: "#8ED973", media: "#F2C14E", alta: "#F08A8A" };
const NEXT_SEVERITY = { bassa: "media", media: "alta", alta: "bassa" };
function ProblemsBlock({ problems, canEdit, onChanged }) {
  const open = problems.filter((p) => p.status !== "risolta");
  const solved = problems.filter((p) => p.status === "risolta");
  const patch = async (p, body) => {
    try { await api.patch(`/jobs/logs/${p.log_id}/problems/${p.idx}`, body); onChanged(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  if (!problems.length) return null;
  const row = (p) => (
    <div key={`${p.log_id}-${p.idx}`} className="flex items-start gap-3 py-2.5 border-t border-white/[0.13]" data-testid="problem-row">
      <button type="button" disabled={!canEdit} onClick={() => patch(p, { resolved: p.status !== "risolta" })} aria-pressed={p.status === "risolta"}
        aria-label={p.status === "risolta" ? "Riapri il problema" : "Segna come risolto"} data-testid="problem-toggle"
        className={`mt-0.5 h-5 w-5 shrink-0 rounded-full flex items-center justify-center backdrop-blur-md ${p.status === "risolta" ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
        {p.status === "risolta" && <Check size={12} strokeWidth={2.8} />}
      </button>
      <span className="min-w-0 flex-1">
        <span className={`block text-[14px] leading-snug ${p.status === "risolta" ? "text-white/55 line-through" : "text-white"}`}>{p.text}</span>
        <span className="block text-[11.5px] text-white/50">
          {shortDay(p.date)}{p.author ? ` · ${p.author}` : ""}{p.status === "risolta" ? ` · risolto${p.resolved_by ? ` da ${p.resolved_by}` : ""}` : ""}
        </span>
      </span>
      <button type="button" disabled={!canEdit} onClick={() => patch(p, { severity: NEXT_SEVERITY[p.severity] || "media" })} data-testid="problem-severity"
        className="shrink-0 inline-flex items-center gap-1 text-[10.5px] px-2 py-0.5 rounded-full bg-white/10 text-white/85" title="Gravità: tocca per cambiarla">
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: SEVERITY[p.severity] || SEVERITY.media }} />{p.severity}
      </button>
    </div>
  );
  return (
    <div className="mt-1 mb-4" data-testid="problems-block">
      <div className="text-[10px] uppercase tracking-widest text-white/55 text-center mb-1">aperte {open.length} · risolte {solved.length}</div>
      {open.map(row)}
      {solved.length > 0 && <details className="mt-1"><summary className="text-[12px] text-white/60 cursor-pointer py-1.5">Risolte ({solved.length})</summary>{solved.map(row)}</details>}
    </div>
  );
}

// ===== The description of the activities to carry out: written here, dictated in the chat
// («descrizione attività: …») or read from the site-survey report / the quote uploaded (the
// quote also gives the commessa's value). Only its owner or an administrator changes it.
const DOC_KIND_LABEL = { preventivo: "dal preventivo", sopralluogo: "dal report di sopralluogo", altro: "dal documento" };
const DESC_ACCEPT = ".pdf,.docx,.xlsx,.txt,.md,image/*";

function descSource(info) {
  if (!info) return "";
  const when = info.at ? shortDay(info.at.slice(0, 10)) : "";
  const what = info.source === "documento" ? `${DOC_KIND_LABEL[info.kind] || "dal documento"}${info.file ? ` «${info.file}»` : ""}`
    : info.source === "messaggio" ? "dettata in chat" : "scritta";
  return [capFirst(what), info.by, when].filter(Boolean).join(" · ");
}

function DescriptionDocSheet({ commessa, doc, onClose, onSaved }) {
  const [text, setText] = useState(doc.description || "");
  const [mode, setMode] = useState("sostituisci");
  const [useAmount, setUseAmount] = useState(!!doc.amount);
  const [busy, setBusy] = useState(false);
  const seg = (on) => `px-3 py-1 rounded-full text-[12px] transition-colors ${on ? "bg-white text-[#403A3C] font-semibold" : "text-white/75"}`;
  const save = async () => {
    setBusy(true);
    try {
      await api.put(`/jobs/commesse/${commessa.id}/description`, { text, mode, file_name: doc.file_name, doc_kind: doc.kind,
        ...(useAmount && doc.amount ? { budget: doc.amount } : {}) });
      toast.success(useAmount && doc.amount ? `Descrizione e valore della commessa (${eur(doc.amount)}) salvati` : "Descrizione salvata");
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };
  return (
    <GlassBottomSheet onClose={onClose} testid="desc-doc-sheet" className="max-h-[90vh] md:left-1/2 md:right-auto md:w-[560px] md:-translate-x-1/2 md:bottom-8">
      <div className="kicker">· {DOC_KIND_LABEL[doc.kind] || "dal documento"}</div>
      <div className="text-lg font-semibold text-white mt-1 break-words">{doc.file_name}</div>
      <div className="text-[12.5px] text-white/60 mt-0.5">Descrizione delle attività da svolgere: controllala e correggila prima di salvarla.</div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={9} data-testid="desc-doc-text"
        className="mt-3 w-full rounded-2xl bg-white/10 px-3.5 py-3 text-[14px] leading-relaxed text-white outline-none resize-y" />
      {doc.current_description && (
        <div className="mt-2 flex items-center gap-2 text-[12px] text-white/70">
          C'è già una descrizione:
          <span className="inline-flex rounded-full bg-white/10 p-0.5" data-testid="desc-doc-mode">
            <button type="button" onClick={() => setMode("sostituisci")} className={seg(mode === "sostituisci")}>Sostituiscila</button>
            <button type="button" onClick={() => setMode("aggiungi")} className={seg(mode === "aggiungi")}>Aggiungi in fondo</button>
          </span>
        </div>
      )}
      {doc.amount ? (
        <button type="button" onClick={() => setUseAmount((v) => !v)} aria-pressed={useAmount} data-testid="desc-doc-amount"
          className="mt-4 w-full flex items-start gap-3 text-left rounded-2xl bg-white/[0.06] px-3.5 py-3">
          <span className={`mt-0.5 h-5 w-5 shrink-0 rounded-full flex items-center justify-center backdrop-blur-md ${useAmount ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
            {useAmount && <Check size={12} strokeWidth={2.8} />}
          </span>
          <span className="min-w-0">
            <span className="block text-[14px] text-white">Valore della commessa: <b>{eur(doc.amount)}</b>{doc.amount_basis === "imponibile" ? " (imponibile, senza IVA)" : ""}</span>
            <span className="block text-[11.5px] text-white/55">
              Va nel preventivo dei Costi, per il margine.{doc.current_budget && doc.current_budget !== doc.amount ? ` Ora è ${eur(doc.current_budget)}.` : ""}
            </span>
          </span>
        </button>
      ) : doc.kind === "preventivo" ? (
        <div className="mt-3 text-[12px] text-white/55">Nel preventivo non trovo un totale chiaro: il valore della commessa lo puoi scrivere in Costi.</div>
      ) : null}
      <div className="mt-4 flex gap-2">
        <button type="button" onClick={save} disabled={busy || !text.trim()} data-testid="desc-doc-save"
          className="flex-1 h-11 rounded-full bg-white text-[#403A3C] text-[14px] font-semibold inline-flex items-center justify-center gap-1.5 disabled:opacity-50">
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Salva
        </button>
        <button type="button" onClick={onClose} className="h-11 px-5 rounded-full lg-glass text-[14px] text-white">Annulla</button>
      </div>
    </GlassBottomSheet>
  );
}

function DescriptionView({ commessa, canEdit, budget, onChanged, isAdmin }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const [doc, setDoc] = useState(null);
  const fileRef = useRef(null);
  const text = commessa.descrizione || "";
  const saveText = async () => {
    setBusy(true);
    try { await api.put(`/jobs/commesse/${commessa.id}/description`, { text: draft }); setEditing(false); toast.success("Descrizione salvata"); onChanged(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };
  const upload = async (file) => {
    if (!file) return;
    setReading(true);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api.post(`/jobs/commesse/${commessa.id}/documents`, fd);
      if (r.data.type === "quote") setQuote(r.data);   // a quote: its sheet (it also fills the description)
      else { toast.success(r.data.message.split("\n")[0]); onChanged(); if (r.data.doc_description) setDoc({ description: r.data.doc_description, file_name: r.data.file_name, kind: r.data.kind, amount: null, current_description: text }); }
    }
    catch (e) { toast.error(e.response?.data?.detail || "Non sono riuscito a leggere il documento"); }
    finally { setReading(false); if (fileRef.current) fileRef.current.value = ""; }
  };
  const [quote, setQuote] = useState(null);
  const action = "inline-flex items-center gap-1.5 active:opacity-70 disabled:opacity-50";
  return (
    <div data-testid="job-description">
      {canEdit && !editing && (
        <div className="mt-1.5 flex items-center justify-center gap-5 text-[12px] text-white/80">
          <button type="button" onClick={() => { setDraft(text); setEditing(true); }} data-testid="desc-edit" className={action}>
            <Pencil size={13} /> {text ? "Modifica" : "Scrivi"}
          </button>
          <button type="button" onClick={() => fileRef.current?.click()} disabled={reading} data-testid="desc-upload" className={action}>
            {reading ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />} {reading ? "Leggo il documento…" : "Carica sopralluogo o preventivo"}
          </button>
          <input ref={fileRef} type="file" accept={DESC_ACCEPT} className="hidden" data-testid="desc-file" onChange={(e) => upload(e.target.files?.[0])} />
        </div>
      )}
      {editing ? (
        <div className="mt-3">
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={10} autoFocus data-testid="desc-textarea"
            placeholder="Cosa prevede il lavoro: l'oggetto e l'elenco delle lavorazioni."
            className="w-full rounded-2xl bg-white/10 px-3.5 py-3 text-[14px] leading-relaxed text-white placeholder:text-white/40 outline-none resize-y" />
          <div className="mt-2 flex gap-2 justify-end">
            <button type="button" onClick={() => setEditing(false)} className="h-9 px-4 rounded-full lg-glass text-[13px] text-white">Annulla</button>
            <button type="button" onClick={saveText} disabled={busy} data-testid="desc-save"
              className="h-9 px-4 rounded-full bg-white text-[#403A3C] text-[13px] font-semibold inline-flex items-center gap-1.5 disabled:opacity-50">
              {busy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />} Salva
            </button>
          </div>
        </div>
      ) : text ? (
        <div className="mt-3 pt-4 border-t border-white/[0.16]">
          <div className="text-[14.5px] leading-relaxed text-white/90 whitespace-pre-wrap break-words" data-testid="desc-text">{text}</div>
          <div className="mt-3 text-[11.5px] text-white/55 flex flex-wrap gap-x-3 gap-y-1">
            {commessa.descrizione_info && <span data-testid="desc-source">{descSource(commessa.descrizione_info)}</span>}
            {budget ? <span data-testid="desc-budget">Valore della commessa {eur(budget)}</span> : null}
          </div>
        </div>
      ) : (
        <div className="mt-3 py-6 border-t border-white/[0.16] text-[13px] text-white/70" data-testid="desc-empty">
          {canEdit ? <>Nessuna descrizione delle attività. Scrivila qui, dettala nella chat della commessa (es. «descrizione attività: rifacimento
            del bagno con…») oppure carica il report di sopralluogo o il preventivo: la leggo io, e dal preventivo prendo anche il valore della commessa.</>
            : "Nessuna descrizione delle attività, per ora."}
        </div>
      )}
      {doc && <DescriptionDocSheet commessa={commessa} doc={doc} onClose={() => setDoc(null)} onSaved={() => { setDoc(null); onChanged(); }} />}
      {quote && <QuoteSheet commessa={commessa} proposal={quote} onClose={() => setQuote(null)} onSaved={() => { setQuote(null); onChanged(); }} />}
    </div>
  );
}

// ===== The survey (Sopralluogo): the section organized by the agent, its notes, photos, documents
const SURVEY_PARTS = [["date_participants", "Data e partecipanti"], ["state", "Stato di fatto e misure"], ["requests", "Lavori richiesti dal cliente"],
  ["issues", "Criticità e vincoli"], ["materials", "Materiali ipotizzati"]];
const DOC_ACCEPT = ".pdf,.docx,.xlsx,.txt,.md,image/*";

function UploadAction({ commessaId, hint, label, onResult }) {
  const ref = useRef(null);
  const [busy, setBusy] = useState(false);
  const go = async (file) => {
    if (!file) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("file", file);
    if (hint) fd.append("hint", hint);
    try { const r = await api.post(`/jobs/commesse/${commessaId}/documents`, fd); onResult(r.data); }
    catch (e) { toast.error(e.response?.data?.detail || "Non sono riuscito a leggere il documento"); }
    finally { setBusy(false); if (ref.current) ref.current.value = ""; }
  };
  return (
    <>
      <button type="button" onClick={() => ref.current?.click()} disabled={busy} data-testid={`upload-${hint || "doc"}`}
        className="inline-flex items-center gap-1.5 active:opacity-70 disabled:opacity-50">
        {busy ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />} {busy ? "Leggo il documento…" : label}
      </button>
      <input ref={ref} type="file" accept={DOC_ACCEPT} className="hidden" onChange={(e) => go(e.target.files?.[0])} />
    </>
  );
}

function SurveyView({ commessa, survey, logs, canWrite, onChanged }) {
  const [quote, setQuote] = useState(null);
  const entries = (logs || []).filter((lg) => lg.section === "sopralluogo");
  const onResult = (r) => { if (r.type === "quote") setQuote(r); else { toast.success(r.message.split("\n")[0]); onChanged(); } };
  return (
    <div data-testid="job-survey">
      {canWrite && (
        <div className="mt-1.5 flex items-center justify-center gap-5 text-[12px] text-white/80">
          <UploadAction commessaId={commessa.id} hint="sopralluogo" label="Carica appunti, foto o documenti" onResult={onResult} />
        </div>
      )}
      {survey ? (
        <div className="mt-3 pt-3 border-t border-white/[0.16]" data-testid="survey-summary">
          {SURVEY_PARTS.filter(([k]) => survey[k]).map(([k, label]) => (
            <div key={k} className="mb-3">
              <div className="text-[10px] uppercase tracking-widest text-white/55 mb-0.5">{label}</div>
              <div className="text-[14px] leading-relaxed text-white/90 whitespace-pre-wrap">{survey[k]}</div>
            </div>
          ))}
          <div className="text-[11.5px] text-white/50">Riorganizzato da mAIPAL da {survey.entries} {survey.entries === 1 ? "nota" : "note"} · non aggiunge niente che non sia scritto</div>
        </div>
      ) : (
        <div className="mt-3 py-6 border-t border-white/[0.16] text-[13px] text-white/70" data-testid="survey-empty">
          Nessuna nota di sopralluogo. Mandale dalla chat della commessa o da Telegram (testo, voce, foto, foto degli appunti scritti a mano, PDF):
          finché la commessa è nuova o in sopralluogo, o se scrivi «sopralluogo», finiscono qui e le riordino io.
        </div>
      )}
      {entries.length > 0 && (
        <div className="mt-2">
          <div className="text-[10px] uppercase tracking-widest text-white/55 mb-1">note, foto e documenti</div>
          {entries.map((lg) => (
            <div key={lg.id} className="py-2.5 border-t border-white/[0.13]" data-testid="survey-entry">
              <div className="text-[11.5px] text-white/50">{shortDay(lg.date)} · {lg.author_name}{(lg.photos || []).length ? ` · ${lg.photos.length} foto` : ""}</div>
              <div className="text-[13.5px] text-white/90 whitespace-pre-wrap leading-snug">{lg.text}</div>
              {(lg.ocr || []).map((o) => (
                <details key={o.photo_id} className="mt-1"><summary className="text-[12px] text-white/60 cursor-pointer">Appunti trascritti</summary>
                  <div className="text-[12.5px] text-white/80 whitespace-pre-wrap mt-1">{o.text}</div></details>
              ))}
              {lg.doc_archive?.link && <a href={lg.doc_archive.link} target="_blank" rel="noreferrer" className="text-[12px] text-white/70 underline">Apri il documento</a>}
            </div>
          ))}
        </div>
      )}
      {quote && <QuoteSheet commessa={commessa} proposal={quote} onClose={() => setQuote(null)} onSaved={() => { setQuote(null); onChanged(); }} />}
    </div>
  );
}

// ===== The quote: read, checked and confirmed (its value, its description), its versions and outcome
function QuoteSheet({ commessa, proposal, onClose, onSaved }) {
  const q = proposal.quote || {};
  const d = q.data || {};
  const differs = proposal.value && proposal.current_budget && Math.abs(proposal.current_budget - proposal.value) >= 0.01;
  const [valueChoice, setValueChoice] = useState(differs ? "new" : null);
  const [desc, setDesc] = useState(d.description || "");
  const [mode, setMode] = useState(proposal.current_description ? "aggiungi" : "sostituisci");
  const [useDesc, setUseDesc] = useState(!proposal.current_description);
  const [plan, setPlan] = useState(proposal.plan_default || "none");
  const [busy, setBusy] = useState(false);
  const seg = (on) => `px-3 py-1 rounded-full text-[12px] transition-colors ${on ? "bg-white text-[#403A3C] font-semibold" : "text-white/75"}`;
  const confirm = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/jobs/quotes/${q.id}/confirm`, { value_choice: differs && proposal.can_choose_value ? valueChoice : null, plan,
        ...(useDesc && desc.trim() ? { description_text: desc, description_mode: mode } : {}) });
      toast.success(r.data.message.split("\n")[0]); onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };
  const discard = async () => { try { await api.post(`/jobs/quotes/${q.id}/discard`); } catch { /* gone already */ } onClose(); };
  return (
    <GlassBottomSheet onClose={discard} testid="quote-sheet" className="max-h-[92vh] md:left-1/2 md:right-auto md:w-[580px] md:-translate-x-1/2 md:bottom-8">
      <div className="kicker">· preventivo</div>
      <div className="text-lg font-semibold text-white mt-1 break-words">{q.file_name}</div>
      <div className="text-[12.5px] text-white/60 mt-0.5">Controlla i dati letti dal documento: li salvo solo quando confermi.</div>
      <div className="mt-3 rounded-2xl bg-white/[0.06] px-3.5 py-3 text-[13.5px] text-white/90 space-y-1" data-testid="quote-data">
        {(d.taxable || d.total) ? <div>💶 {d.taxable ? `Imponibile ${eur(d.taxable)}` : ""}{d.taxable && d.total ? " · " : ""}{d.total ? `Totale ${eur(d.total)}` : ""}</div>
          : <div className="text-white/60">Totale non trovato nel documento</div>}
        {(d.start || d.end || d.validity) && <div>📅 {[d.start && `inizio ${shortDay(d.start)}`, d.end && `fine ${shortDay(d.end)}`, d.validity && `valido fino al ${shortDay(d.validity)}`].filter(Boolean).join(" · ")}</div>}
        {(d.payments || []).length > 0 && <div>💳 {d.payments.join("; ")}</div>}
        {(d.materials_planned || []).length > 0 && (
          <details data-testid="quote-sheet-materials"><summary className="cursor-pointer">🧰 {d.materials_planned.length} materiali previsti
            {d.materials_planned.some((m) => m.qty) ? ` (${d.materials_planned.filter((m) => m.qty).length} con la quantità)` : ""}</summary>
            {d.materials_planned.map((m, i) => (
              <div key={i} className="flex gap-2 text-[12.5px] text-white/80 py-0.5"><span className="flex-1">{m.name}</span>
                <span className="tabular-nums text-white/70">{m.qty ? `${fmtNum(m.qty)}${m.unit ? ` ${m.unit}` : ""}` : "quantità non scritta"}</span></div>
            ))}
          </details>
        )}
        {d.labor_hours ? <div data-testid="quote-sheet-hours">👷 Ore uomo previste: {fmtNum(d.labor_hours)} h</div>
          : (d.labor || []).length > 0 ? <div>👷 Manodopera: {d.labor.join("; ")} <span className="text-white/55">(ore non scritte come numero)</span></div> : null}
        {d.warranty && <div>🛡 Garanzia: {d.warranty}</div>}
        {(d.maintenance || []).length > 0 && <div>🔧 Manutenzione: {d.maintenance.map((m) => m.text + (m.every_months ? ` (ogni ${m.every_months} mesi)` : " (frequenza non scritta)")).join("; ")}</div>}
        {(d.items || []).length > 0 && (
          <details><summary className="cursor-pointer text-white/75">{d.items.length} {d.items.length === 1 ? "voce" : "voci"}</summary>
            {d.items.map((it, i) => <div key={i} className="flex gap-2 text-[12.5px] text-white/80 py-0.5"><span className="flex-1">{it.description}</span>
              {it.qty ? <span className="text-white/60 tabular-nums">{fmtNum(it.qty)}{it.unit ? ` ${it.unit}` : ""}</span> : null}{it.amount ? <span>{eur(it.amount)}</span> : null}</div>)}
          </details>
        )}
      </div>
      {differs && proposal.can_choose_value && (
        <div className="mt-3 text-[13px] text-white/85" data-testid="quote-value-choice">
          Valore della commessa:
          <span className="ml-2 inline-flex rounded-full bg-white/10 p-0.5">
            <button type="button" onClick={() => setValueChoice("new")} className={seg(valueChoice === "new")}>Usa {eur(proposal.value)}</button>
            <button type="button" onClick={() => setValueChoice("keep")} className={seg(valueChoice === "keep")}>Tieni {eur(proposal.current_budget)}</button>
          </span>
        </div>
      )}
      {!proposal.current_budget && proposal.value ? <div className="mt-2 text-[12px] text-white/60">Il valore della commessa diventa {eur(proposal.value)}.</div> : null}
      {(d.activities || []).length > 0 && (
        <div className="mt-3 text-[13px] text-white/85" data-testid="quote-plan">
          Le {d.activities.length} attività del preventivo:
          <span className="ml-2 inline-flex rounded-full bg-white/10 p-0.5">
            <button type="button" onClick={() => proposal.plan_dates?.end && setPlan("milestone")} disabled={!proposal.plan_dates?.end}
              className={`${seg(plan === "milestone")} disabled:opacity-40`} data-testid="quote-plan-milestone">Milestone</button>
            <button type="button" onClick={() => setPlan("todo")} className={seg(plan === "todo")} data-testid="quote-plan-todo">To Do</button>
            <button type="button" onClick={() => setPlan("none")} className={seg(plan === "none")}>Niente</button>
          </span>
          <div className="text-[11.5px] text-white/55 mt-1">
            {plan === "milestone" ? `Scadenze distribuite nei giorni lavorativi dal ${shortDay(proposal.plan_dates.start)} al ${shortDay(proposal.plan_dates.end)}, nell'ordine del preventivo: poi le cambi tu.`
              : plan === "todo" ? (proposal.plan_dates?.end ? "Un To Do per attività, senza scadenza." : "Senza date di inizio e fine lavori le milestone non si possono fare: un To Do per attività.")
              : "Non creo né milestone né To Do (le attività restano da pianificare)."}
          </div>
        </div>
      )}
      {proposal.loss_feedback && <div className="mt-3 text-[12.5px] text-[#F2C14E]" data-testid="quote-loss-feedback">{proposal.loss_feedback}</div>}
      {proposal.history_check && <div className="mt-2 text-[12.5px] text-white/85" data-testid="quote-history-check">{proposal.history_check}</div>}
      {desc && (
        <div className="mt-3">
          <button type="button" onClick={() => setUseDesc((v) => !v)} aria-pressed={useDesc} className="flex items-center gap-2.5 text-[13px] text-white">
            <span className={`h-5 w-5 rounded-full flex items-center justify-center ${useDesc ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>{useDesc && <Check size={12} strokeWidth={2.8} />}</span>
            Usa le attività come descrizione della commessa
          </button>
          {useDesc && (
            <>
              <textarea value={desc} onChange={(e) => setDesc(e.target.value)} rows={6} data-testid="quote-desc"
                className="mt-2 w-full rounded-2xl bg-white/10 px-3.5 py-3 text-[13.5px] leading-relaxed text-white outline-none resize-y" />
              {proposal.current_description && (
                <span className="inline-flex rounded-full bg-white/10 p-0.5 mt-1">
                  <button type="button" onClick={() => setMode("sostituisci")} className={seg(mode === "sostituisci")}>Sostituisci</button>
                  <button type="button" onClick={() => setMode("aggiungi")} className={seg(mode === "aggiungi")}>Aggiungi in fondo</button>
                </span>
              )}
            </>
          )}
        </div>
      )}
      <div className="mt-4 flex gap-2">
        <button type="button" onClick={confirm} disabled={busy} data-testid="quote-confirm"
          className="flex-1 h-11 rounded-full bg-white text-[#403A3C] text-[14px] font-semibold inline-flex items-center justify-center gap-1.5 disabled:opacity-50">
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Conferma il preventivo
        </button>
        <button type="button" onClick={discard} className="h-11 px-5 rounded-full lg-glass text-[14px] text-white">Annulla</button>
      </div>
    </GlassBottomSheet>
  );
}

// ===== Pianificazione: the planned activities - when, who (and whether they confirmed), what to bring
const ACT_CATEGORIES = [["materiali", "Materiali"], ["attrezzi", "Attrezzi"], ["dpi", "DPI"], ["documenti", "Documenti"]];
const ACT_STATUS = { pianificata: ["Pianificata", "#F2C14E"], confermata: ["Confermata", "#8ED973"], in_corso: ["In corso", "#7FC8F8"],
  svolta: ["Svolta", "rgba(255,255,255,0.55)"], annullata: ["Annullata", "rgba(255,255,255,0.35)"] };
const CONFIRM_MARK = { confermato: "✓", rifiutato: "✗", in_attesa: "…" };
const actWhen = (a) => [shortDay(a.date), a.start_time && (a.end_time ? `${a.start_time}–${a.end_time}` : `ore ${a.start_time}`)].filter(Boolean).join(" · ");
const normDesc = (x) => (x || "").toLowerCase().replace(/[^a-z0-9àèéìòù]+/g, " ").trim();

function ActivitySheet({ commessa, activity, prefill, onClose, onSaved }) {
  const isNew = !activity;
  const [people, setPeople] = useState([]);
  const [desc, setDesc] = useState(activity?.description || prefill || "");
  const [day, setDay] = useState(activity?.date || todayIso());
  const [start, setStart] = useState(activity?.start_time || "");
  const [end, setEnd] = useState(activity?.end_time || "");
  const [chosen, setChosen] = useState((activity?.assignees || []).map((p) => `${p.type}:${p.id}`));
  const [items, setItems] = useState(isNew ? [] : activity.items || []);
  const [itemText, setItemText] = useState("");
  const [itemCat, setItemCat] = useState("materiali");
  const [info, setInfo] = useState(activity?.info || "");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get(`/jobs/commesse/${commessa.id}/plan-people`).then((r) => setPeople(r.data || [])).catch(() => setPeople([])); }, [commessa.id]);
  const toggle = (k) => setChosen((cur) => (cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k]));
  const assignees = () => chosen.map((k) => { const [type, ...id] = k.split(":"); return { type, id: id.join(":") }; });
  const addItem = async () => {
    const text = itemText.trim();
    if (!text) return;
    if (isNew) setItems((cur) => [...cur, { id: `new-${cur.length}`, category: itemCat, text }]);
    else {
      try { const r = await api.post(`/jobs/activities/${activity.id}/items`, { text, category: itemCat }); setItems((cur) => [...cur, r.data]); }
      catch (e) { toast.error(e.response?.data?.detail || "Errore"); return; }
    }
    setItemText("");
  };
  const removeItem = async (it) => {
    if (!isNew) {
      try { await api.delete(`/jobs/activities/${activity.id}/items/${it.id}`); } catch (e) { toast.error(e.response?.data?.detail || "Errore"); return; }
    }
    setItems((cur) => cur.filter((x) => x.id !== it.id));
  };
  const save = async () => {
    if (!desc.trim()) { toast.error("Scrivi l'attività"); return; }
    if (!day) { toast.error("Scegli il giorno"); return; }
    setBusy(true);
    try {
      if (isNew) {
        await api.post(`/jobs/commesse/${commessa.id}/activities`, { description: desc, date: day, start_time: start || null, end_time: end || null,
          assignees: assignees(), items: items.map(({ category, text }) => ({ category, text })), info: info || null, origin: prefill ? "preventivo" : "admin" });
        toast.success(chosen.length ? "Pianificata: l'ho mandata a chi la svolge" : "Pianificata");
      } else {
        await api.patch(`/jobs/activities/${activity.id}`, { description: desc, date: day, start_time: start || "", end_time: end || "", assignees: assignees(), info });
        toast.success("Attività aggiornata");
      }
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore nel salvataggio"); }
    finally { setBusy(false); }
  };
  const cancelActivity = async () => {
    try { await api.patch(`/jobs/activities/${activity.id}`, { status: "annullata" }); toast.success("Attività annullata"); onSaved(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const field = "h-10 rounded-xl bg-white/10 px-3 text-[14px] text-white placeholder:text-white/40 outline-none";
  const chip = (on) => `shrink-0 whitespace-nowrap inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs ${on ? "lg-bubble text-white font-medium" : "bg-white/10 text-white/75"}`;
  return (
    <GlassBottomSheet onClose={onClose} testid="activity-sheet" className="max-h-[92vh] md:left-1/2 md:right-auto md:w-[580px] md:-translate-x-1/2 md:bottom-8">
      <div className="kicker">· {isNew ? "pianifica un'attività" : "modifica l'attività"}</div>
      <div className="mt-2 space-y-3.5">
        <textarea value={desc} onChange={(e) => setDesc(e.target.value)} rows={2} autoFocus={isNew && !prefill} placeholder="Es. Smontaggio sanitari"
          data-testid="activity-desc" className="w-full rounded-2xl bg-white/10 px-3.5 py-3 text-[14px] text-white placeholder:text-white/40 outline-none resize-none" />
        <input type="date" value={day} onChange={(e) => setDay(e.target.value)} data-testid="activity-date" className={`${field} w-full`} />
        <div className="grid grid-cols-2 gap-2">
          <label className="text-[11px] text-white/60">Inizio
            <input type="time" value={start} onChange={(e) => setStart(e.target.value)} data-testid="activity-start" className={`${field} w-full mt-0.5`} /></label>
          <label className="text-[11px] text-white/60">Fine (facoltativa)
            <input type="time" value={end} onChange={(e) => setEnd(e.target.value)} data-testid="activity-end" className={`${field} w-full mt-0.5`} /></label>
        </div>
        <div className="text-[11.5px] text-white/55 -mt-2">Senza ora d'inizio vale quella dell'organizzazione.</div>
        <div>
          <div className="text-[10px] uppercase tracking-widest text-white/55 mb-1">chi la svolge</div>
          <div className="flex gap-1.5 flex-wrap" data-testid="activity-people">
            {people.map((p) => (
              <button key={`${p.type}:${p.id}`} type="button" onClick={() => toggle(`${p.type}:${p.id}`)} className={chip(chosen.includes(`${p.type}:${p.id}`))}
                data-testid={`activity-person-${p.id}`}>
                {p.telegram && <Send size={10} strokeWidth={2} />} {p.name}{p.company ? ` · ${p.company}` : ""}
              </button>
            ))}
            {!people.length && <span className="text-[12px] text-white/55">Nessuno da assegnare: aggiungi utenti o abilita collaboratori sulla commessa.</span>}
          </div>
          <div className="text-[11.5px] text-white/55 mt-1">Chi ha Telegram (<Send size={9} className="inline" />) la riceve subito e il giorno prima conferma se c'è.</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-widest text-white/55 mb-1">da portare</div>
          {ACT_CATEGORIES.map(([k, label]) => {
            const list = items.filter((i) => i.category === k);
            return list.length ? (
              <div key={k} className="mb-1">
                <span className="text-[12px] text-white/60">{label}: </span>
                {list.map((i) => (
                  <span key={i.id} className="inline-flex items-center gap-1 mr-1.5 mb-1 px-2 py-0.5 rounded-full bg-white/10 text-[12.5px] text-white/90">
                    {i.text}<button type="button" onClick={() => removeItem(i)} aria-label="Togli" className="text-white/55"><X size={11} /></button>
                  </span>
                ))}
              </div>
            ) : null;
          })}
          <div className="flex gap-2 mt-1">
            <select value={itemCat} onChange={(e) => setItemCat(e.target.value)} data-testid="activity-item-cat" className={`${field} w-[118px] [&>option]:text-black`}>
              {ACT_CATEGORIES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
            <input value={itemText} onChange={(e) => setItemText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addItem())}
              placeholder="Es. flex, casco, DICO" data-testid="activity-item-text" className={`${field} flex-1 min-w-0`} />
            <button type="button" onClick={addItem} aria-label="Aggiungi" data-testid="activity-item-add" className="h-10 w-10 shrink-0 rounded-full bg-white/15 inline-flex items-center justify-center"><Plus size={16} /></button>
          </div>
        </div>
        <textarea value={info} onChange={(e) => setInfo(e.target.value)} rows={2} placeholder="Informazioni utili (chiavi, accessi, parcheggio…)"
          data-testid="activity-info" className="w-full rounded-2xl bg-white/10 px-3.5 py-2.5 text-[13.5px] text-white placeholder:text-white/40 outline-none resize-none" />
      </div>
      <div className="mt-4 flex gap-2">
        <button type="button" onClick={save} disabled={busy} data-testid="activity-save"
          className="flex-1 h-11 rounded-full bg-white text-[#403A3C] text-[14px] font-semibold inline-flex items-center justify-center gap-1.5 disabled:opacity-50">
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} {isNew ? "Pianifica" : "Salva"}
        </button>
        {!isNew && activity.status !== "annullata" && activity.status !== "svolta" && (
          <button type="button" onClick={cancelActivity} data-testid="activity-cancel" className="h-11 px-4 rounded-full lg-glass text-[14px] text-white">Annulla attività</button>
        )}
        <button type="button" onClick={onClose} className="h-11 px-5 rounded-full lg-glass text-[14px] text-white">Chiudi</button>
      </div>
    </GlassBottomSheet>
  );
}

function ActivityCard({ a, meId, isAdmin, canWrite, onEdit, onChanged }) {
  const [adding, setAdding] = useState(false);
  const [text, setText] = useState("");
  const mine = (a.assignees || []).find((p) => p.type === "user" && p.id === meId);
  const open = ["pianificata", "confermata", "in_corso"].includes(a.status);
  const [label, color] = ACT_STATUS[a.status] || ACT_STATUS.pianificata;
  const call = async (fn, ok) => { try { const r = await fn(); toast.success(ok || r.data?.message || "Fatto"); onChanged(); } catch (e) { toast.error(e.response?.data?.detail || "Errore"); } };
  const confirm = (status) => {
    let reason = "";
    if (status === "rifiutato") { reason = window.prompt("Perché non puoi esserci? Lo dico all'amministratore.") ?? null; if (reason === null) return; }
    call(() => api.post(`/jobs/activities/${a.id}/confirm`, { status, reason }));
  };
  const addItem = () => { if (!text.trim()) return; call(() => api.post(`/jobs/activities/${a.id}/items`, { text }), "Aggiunto"); setText(""); setAdding(false); };
  const btn = "text-[12px] px-3 py-1.5 rounded-full bg-white/10 text-white active:opacity-70";
  return (
    <div className={`py-3 border-t border-white/[0.13] ${open ? "" : "opacity-70"}`} data-testid="activity-card">
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <div className="text-[15px] font-semibold text-white leading-snug break-words">{a.description}</div>
          <div className="text-[12px] text-white/60 mt-0.5">{actWhen(a)}{a.origin === "preventivo" ? " · dal preventivo" : ""}</div>
        </div>
        <span className="shrink-0 inline-flex items-center gap-1.5 text-[11px] px-2 py-0.5 rounded-full bg-white/10 text-white/90" data-testid="activity-status">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />{label}</span>
        {isAdmin && canWrite && open && (
          <button type="button" onClick={() => onEdit(a)} aria-label="Modifica" data-testid="activity-edit" className="p-1 text-white/60"><Pencil size={14} /></button>
        )}
      </div>
      {(a.assignees || []).length > 0 && (
        <div className="flex gap-1.5 flex-wrap mt-1.5">
          {a.assignees.map((p) => {
            const st = p.confirm?.status || "in_attesa";
            return (
              <span key={`${p.type}:${p.id}`} title={p.confirm?.reason || ""} data-testid="activity-assignee"
                className={`text-[11.5px] px-2 py-0.5 rounded-full ${st === "confermato" ? "bg-[#8ED973]/20 text-white" : st === "rifiutato" ? "bg-[#F08A8A]/25 text-white" : "bg-white/10 text-white/75"}`}>
                {CONFIRM_MARK[st]} {p.name}{st === "rifiutato" && p.confirm?.reason ? ` — ${p.confirm.reason}` : ""}
              </span>
            );
          })}
        </div>
      )}
      {ACT_CATEGORIES.some(([k]) => (a.items || []).some((i) => i.category === k)) && (
        <div className="mt-1.5 text-[13px] text-white/85 space-y-0.5">
          {ACT_CATEGORIES.map(([k, lbl]) => {
            const list = (a.items || []).filter((i) => i.category === k);
            return list.length ? <div key={k}><span className="text-white/55">{lbl}:</span> {list.map((i) => i.text).join(", ")}</div> : null;
          })}
        </div>
      )}
      {a.info && <div className="mt-1 text-[12.5px] text-white/70">ℹ️ {a.info}</div>}
      {open && (mine || (isAdmin && canWrite)) && (
        <div className="mt-2 flex gap-1.5 flex-wrap" data-testid="activity-actions">
          {mine && (mine.confirm?.status || "in_attesa") !== "confermato" && <button type="button" onClick={() => confirm("confermato")} className={btn} data-testid="activity-confirm">👍 Ci sono</button>}
          {mine && (mine.confirm?.status || "in_attesa") !== "rifiutato" && <button type="button" onClick={() => confirm("rifiutato")} className={btn} data-testid="activity-refuse">✋ Non posso</button>}
          <button type="button" onClick={() => setAdding((v) => !v)} className={btn} data-testid="activity-add-item">➕ Da portare</button>
          <button type="button" onClick={() => call(() => api.post(`/jobs/activities/${a.id}/done`), "Attività svolta")} className={btn} data-testid="activity-done">✅ Svolta</button>
        </div>
      )}
      {adding && (
        <div className="mt-2 flex gap-2">
          <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addItem()} autoFocus placeholder="Cosa portare"
            className="h-9 flex-1 min-w-0 rounded-xl bg-white/10 px-3 text-[13.5px] text-white placeholder:text-white/40 outline-none" data-testid="activity-item-input" />
          <button type="button" onClick={addItem} className="h-9 px-3 rounded-full bg-white text-[#403A3C] text-[13px] font-medium">Aggiungi</button>
        </div>
      )}
    </div>
  );
}

function PlanView({ commessa, activities, quotes, meId, isAdmin, canWrite, onChanged }) {
  const [sheet, setSheet] = useState(null);   // {activity} | {prefill}
  const [showPast, setShowPast] = useState(false);
  const acts = activities || [];
  const open = acts.filter((a) => ["pianificata", "confermata", "in_corso"].includes(a.status));
  const past = acts.filter((a) => !["pianificata", "confermata", "in_corso"].includes(a.status)).reverse();
  const planned = new Set(acts.map((a) => normDesc(a.description)));
  const fromQuote = isAdmin ? ((quotes || [])[0]?.data?.activities || []).filter((x) => !planned.has(normDesc(x))) : [];
  const card = (a) => <ActivityCard key={a.id} a={a} meId={meId} isAdmin={isAdmin} canWrite={canWrite} onEdit={(x) => setSheet({ activity: x })} onChanged={onChanged} />;
  return (
    <div data-testid="job-plan">
      {isAdmin && canWrite && (
        <div className="mt-1.5 flex items-center justify-center text-[12px] text-white/80">
          <button type="button" onClick={() => setSheet({})} data-testid="activity-new" className="inline-flex items-center gap-1.5 active:opacity-70"><Plus size={13} /> Pianifica un'attività</button>
        </div>
      )}
      {fromQuote.length > 0 && canWrite && (
        <div className="mt-3 pt-3 border-t border-white/[0.16]" data-testid="plan-from-quote">
          <div className="text-[10px] uppercase tracking-widest text-white/55 mb-1">da pianificare (dal preventivo)</div>
          {fromQuote.map((x, i) => (
            <button key={i} type="button" onClick={() => setSheet({ prefill: x })} className="w-full text-left flex items-center gap-2 py-1.5 text-[13.5px] text-white/85 active:opacity-70">
              <CalendarDays size={13} className="shrink-0 text-white/55" /><span className="flex-1">{x}</span><ChevronRight size={14} className="text-white/45" />
            </button>
          ))}
        </div>
      )}
      {open.length ? <div className="mt-3">{open.map(card)}</div> : (
        <div className="mt-3 py-6 border-t border-white/[0.16] text-[13px] text-white/70" data-testid="plan-empty">
          {isAdmin ? "Nessuna attività pianificata. Pianificala qui o scrivi in chat, ad esempio «pianifica smontaggio sanitari giovedì alle 8 con Marco, portare il flex»: chi la svolge la riceve su Telegram, conferma il giorno prima e riceve il meteo."
            : "Nessuna attività pianificata per questa commessa."}
        </div>
      )}
      {past.length > 0 && (
        <div className="mt-2">
          <button type="button" onClick={() => setShowPast((v) => !v)} className="text-[12px] text-white/60 py-1 inline-flex items-center gap-1" data-testid="plan-past-toggle">
            {showPast ? <ChevronDown size={13} /> : <ChevronRight size={13} />} Svolte e annullate ({past.length})
          </button>
          {showPast && past.map(card)}
        </div>
      )}
      {sheet && <ActivitySheet commessa={commessa} activity={sheet.activity} prefill={sheet.prefill} onClose={() => setSheet(null)}
        onSaved={() => { setSheet(null); onChanged(); }} />}
    </div>
  );
}

// ===== The quote from history: the similar commesse already closed, what they really cost, the value that keeps the margin
function HistoryEstimate({ commessa }) {
  const [est, setEst] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = (refresh = false) => {
    setBusy(true);
    api.get(`/jobs/commesse/${commessa.id}/estimate`, { params: refresh ? { refresh: true } : {} }).then((r) => setEst(r.data))
      .catch((e) => setEst({ status: "error", message: e.response?.data?.detail || "Stima non disponibile" })).finally(() => setBusy(false));
  };
  useEffect(() => { load(); }, [commessa.id]);
  const rng = (x, fmt) => (x?.median == null ? "—" : `${fmt(x.median)}${x.min !== x.max ? ` (${fmt(x.min)}–${fmt(x.max)})` : ""}`);
  return (
    <div className="mt-4 pt-3 border-t border-white/[0.16]" data-testid="history-estimate">
      <div className="flex items-center gap-2">
        <div className="flex-1 text-[10px] uppercase tracking-widest text-white/55">stima dai tuoi lavori simili</div>
        <button type="button" onClick={() => load(true)} disabled={busy} aria-label="Aggiorna la stima" data-testid="estimate-refresh" className="p-1 text-white/70 disabled:opacity-50">
          {busy ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
        </button>
      </div>
      {!est ? <div className="text-[12.5px] text-white/60 py-2">Cerco le commesse simili…</div> : est.status !== "ok" ? (
        <div className="text-[12.5px] text-white/65 py-2" data-testid="estimate-empty">{est.message}
          {(est.lost_for_price || []).length > 0 && ` Preventivi simili persi per il prezzo: ${est.lost_for_price.map((x) => x.value ? eur(x.value) : x.title).join(", ")}.`}</div>
      ) : (
        <div className="mt-1.5 text-[13.5px] text-white/90 space-y-1">
          {est.suggested_value && (
            <div className="text-[15px] font-semibold text-white" data-testid="estimate-value">
              Valore consigliato ≈ {eur(est.suggested_value)}
              <span className="block text-[12px] font-normal text-white/60">per tenere il margine dei simili ({Math.round(est.margin_pct_median)}%) sul costo atteso</span>
            </div>
          )}
          <div>💶 Costo atteso {rng(est.cost, eur)}</div>
          <div>⏱ Ore {rng(est.hours, (x) => `${fmtNum(x)} h`)}{est.days?.median ? ` · durata ${rng(est.days, (x) => `${fmtNum(x)} gg`)}` : ""}</div>
          {est.margin_pct_median != null && <div>📈 Margine medio {Math.round(est.margin_pct_median)}%</div>}
          {est.value_check && <div className="text-[12.5px] text-white/80" data-testid="estimate-check">{est.value_check}</div>}
          {(est.lost_for_price || []).length > 0 && (
            <div className="text-[12.5px] text-[#F2C14E]">Persi per il prezzo: {est.lost_for_price.map((x) => `${x.title}${x.value ? ` (${eur(x.value)})` : ""}`).join(", ")}</div>
          )}
          <details className="pt-0.5"><summary className="text-[12px] text-white/60 cursor-pointer">Su {est.n} {est.n === 1 ? "commessa" : "commesse"} simili</summary>
            {est.similar.map((x) => (
              <div key={x.id} className="text-[12.5px] text-white/75 py-0.5">{x.title} — {x.client_name}: {eur(x.cost)}{x.hours ? ` · ${fmtNum(x.hours)} h` : ""}
                {x.margin_pct != null ? ` · margine ${Math.round(x.margin_pct)}%` : ""}{x.complete ? "" : " · costi incompleti"}</div>
            ))}
            <div className="text-[11.5px] text-white/50 pt-1">Numeri dal tuo diario e dai Costi: ore × tariffa, materiali × prezzo, altre spese. {est.method === "parole" ? "Simili per parole in comune." : "Simili scelte da mAIPAL tra le tue commesse."}</div>
          </details>
        </div>
      )}
    </div>
  );
}

// ===== The man-hours the quote foresees against the ones written in the diary (the whole commessa)
function HoursPlan({ plan }) {
  const over = plan.planned && plan.done > plan.planned;
  const color = over ? "#F08A8A" : plan.pct >= 80 ? "#F2C14E" : "rgba(255,255,255,0.8)";
  return (
    <div className="mt-1 mb-4" data-testid="hours-plan">
      <div className="text-[10px] uppercase tracking-widest text-white/55 text-center mb-1">ore previste dal preventivo{plan.quote_version ? ` v${plan.quote_version}` : ""}</div>
      {plan.planned ? (
        <div className="py-2 border-t border-white/[0.13]">
          <div className="flex items-baseline gap-2">
            <span className="flex-1 text-[14px] text-white/90">Ore uomo</span>
            <span className="text-[13px] tabular-nums text-white/90" data-testid="hours-plan-figures">{fmtNum(plan.done)} h / {fmtNum(plan.planned)} h</span>
          </div>
          <div className="mt-1 h-1 rounded-full bg-white/15 overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${Math.min(100, plan.pct || 0)}%`, background: color }} />
          </div>
          <div className="text-[11.5px] mt-0.5" style={{ color }}>
            {over ? `oltre il previsto di ${fmtNum(-plan.left)} h` : `${plan.pct}% · ne restano ${fmtNum(plan.left)} h`}
            {plan.pending ? <span className="text-white/55"> · {fmtNum(plan.pending)} h da approvare non contate</span> : null}
          </div>
        </div>
      ) : null}
      {(plan.labor || []).length > 0 && <div className="text-[12px] text-white/65 pt-1">Dal preventivo: {plan.labor.join("; ")}</div>}
    </div>
  );
}

// ===== The materials the quote foresees against the ones the diary says were used (the whole commessa)
const MAT_STATUS = { oltre: ["oltre il previsto", "#F08A8A"], completo: ["usato tutto", "#8ED973"], in_uso: ["in uso", "rgba(255,255,255,0.8)"],
  da_usare: ["non ancora usato", "rgba(255,255,255,0.5)"], usato: ["usato", "#8ED973"] };
function MaterialsPlan({ plan }) {
  const [open, setOpen] = useState(true);
  const q = (x, u) => (x == null ? "—" : `${fmtNum(x)}${u ? ` ${u}` : ""}`);
  return (
    <div className="mt-1 mb-4" data-testid="materials-plan">
      <button type="button" onClick={() => setOpen((v) => !v)} className="w-full flex items-center justify-center gap-1 text-[10px] uppercase tracking-widest text-white/55 mb-1">
        previsti dal preventivo{plan.quote_version ? ` v${plan.quote_version}` : ""} {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {open && (
        <>
          {plan.rows.map((r, i) => {
            const [label, color] = MAT_STATUS[r.status] || MAT_STATUS.in_uso;
            return (
              <div key={i} className="py-2 border-t border-white/[0.13]" data-testid="materials-plan-row">
                <div className="flex items-baseline gap-2">
                  <span className="flex-1 min-w-0 text-[14px] text-white/90 break-words">{r.name}</span>
                  <span className="shrink-0 text-[12.5px] tabular-nums text-white/85">{r.planned == null ? (r.used ? q(r.used, r.unit) : "") : `${q(r.used, r.unit)} / ${q(r.planned, r.unit)}`}</span>
                </div>
                {r.planned ? (
                  <div className="mt-1 h-1 rounded-full bg-white/15 overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${Math.min(100, r.pct || 0)}%`, background: color }} />
                  </div>
                ) : null}
                <div className="text-[11.5px] mt-0.5" style={{ color }}>
                  {label}{r.status === "oltre" ? ` di ${q(-r.left, r.unit)}` : r.status === "in_uso" ? ` · ne restano ${q(r.left, r.unit)}` : ""}
                  {(r.other_units || []).length > 0 && <span className="text-white/55"> · usato anche {r.other_units.join(", ")} (altra unità)</span>}
                </div>
              </div>
            );
          })}
          {plan.unplanned.length > 0 && (
            <div className="pt-2 border-t border-white/[0.13] text-[12.5px] text-white/75" data-testid="materials-unplanned">
              <span className="text-white/55">Usati e non previsti:</span> {plan.unplanned.map((u) => [fmtNum(u.qty), u.unit, u.name].filter(Boolean).join(" ")).join(" · ")}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ===== Lavori extra: done on the site, not in the quote - found in the diary, approved by the client, billed
const EXTRA_DONE = ["approvato", "rifiutato", "compreso", "scartato"];
function ExtraWorksView({ commessa, rows, onChanged }) {
  const [list, setList] = useState(rows || []);
  const [busy, setBusy] = useState("");
  const [adding, setAdding] = useState(false);
  const [text, setText] = useState("");
  const [showDone, setShowDone] = useState(false);
  useEffect(() => { setList(rows || []); }, [rows]);
  const run = async (key, fn, ok) => {
    setBusy(key);
    try { const r = await fn(); if (r.data?.extra_works) setList(r.data.extra_works); if (ok || r.data?.message) toast.success(ok || r.data.message.replace(/^\S+\s/, "")); onChanged?.(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(""); }
  };
  const act = (x, action, extra = {}) => run(`${x.id}:${action}`, () => api.patch(`/jobs/extra-works/${x.id}`, { action, ...extra }));
  const scan = () => run("scan", async () => {
    const r = await api.post(`/jobs/commesse/${commessa.id}/extra-works/scan`);
    toast.success(r.data.found ? `Trovati ${r.data.found} possibili lavori extra` : `Controllate ${r.data.checked} note: nessun lavoro extra nuovo`);
    return { data: { extra_works: r.data.extra_works } };
  });
  const add = () => { if (!text.trim()) return; run("add", () => api.post(`/jobs/commesse/${commessa.id}/extra-works`, { work: text }), "Aggiunto"); setText(""); setAdding(false); };
  const variant = () => run("variant", async () => {
    const r = await api.post(`/jobs/commesse/${commessa.id}/variante`, { extra_ids: [] });
    window.open(`${API}/work/reports/${r.data.report.id}/download`, "_blank");
    return { data: { extra_works: r.data.extra_works } };
  }, "Variante pronta: è anche nella cartella Preventivi");
  const open = list.filter((x) => !EXTRA_DONE.includes(x.status));
  const done = list.filter((x) => EXTRA_DONE.includes(x.status));
  const toApprove = open.filter((x) => x.status === "extra");
  const btn = "text-[12px] px-3 py-1.5 rounded-full bg-white/10 text-white active:opacity-70 disabled:opacity-50";
  const row = (x) => (
    <div key={x.id} className={`py-2.5 border-t border-white/[0.13] ${EXTRA_DONE.includes(x.status) ? "opacity-70" : ""}`} data-testid="extra-work">
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0 text-[14px] text-white leading-snug break-words">{x.work}</div>
        <span className="shrink-0 text-[11px] px-2 py-0.5 rounded-full bg-white/10 text-white/85" data-testid="extra-status">{x.status_label}</span>
      </div>
      <div className="text-[11.5px] text-white/55 mt-0.5">
        {[x.date && shortDay(x.date), x.author, x.by_hand ? "aggiunto a mano" : x.quote_version ? `non nel preventivo v${x.quote_version}` : "non nel preventivo"].filter(Boolean).join(" · ")}
      </div>
      {x.why && <div className="text-[12.5px] text-white/70 mt-0.5">{x.why}</div>}
      {(x.hours > 0 || (x.materials || []).length > 0 || x.note_cost) && (
        <div className="text-[12px] text-white/60 mt-0.5">Nella nota: {[x.hours > 0 && `${fmtNum(x.hours)} h`, (x.materials || []).map(matLabel).join(", "),
          x.note_cost ? `costo registrato ${eur(x.note_cost)}` : ""].filter(Boolean).join(" · ")}</div>
      )}
      {x.status === "da_valutare" && (
        <div className="mt-2 flex gap-1.5 flex-wrap">
          <button type="button" disabled={!!busy} onClick={() => act(x, "extra")} className={btn} data-testid="extra-yes">💶 È un extra</button>
          <button type="button" disabled={!!busy} onClick={() => act(x, "compreso")} className={btn} data-testid="extra-in-quote">✅ Nel preventivo</button>
          <button type="button" disabled={!!busy} onClick={() => act(x, "scartato")} className={btn} data-testid="extra-no">🗑 Non è un lavoro</button>
        </div>
      )}
      {x.status === "extra" && (
        <div className="mt-2 flex items-center gap-1.5 flex-wrap">
          <span className="text-[12px] text-white/70">Importo per il cliente</span>
          <MoneyInput value={x.amount} onSave={(n) => act(x, "update", { amount: n })} placeholder="0" testid="extra-amount" wide />
          <button type="button" disabled={!!busy} onClick={() => act(x, "approvato")} className={btn} data-testid="extra-approved">👍 Approvato dal cliente</button>
          <button type="button" disabled={!!busy} onClick={() => act(x, "rifiutato")} className={btn}>✋ Rifiutato</button>
        </div>
      )}
      {x.status === "approvato" && x.amount ? <div className="text-[12px] text-white/70 mt-0.5">{eur(x.amount)} aggiunti al valore della commessa</div> : null}
    </div>
  );
  return (
    <div className="mt-4 pt-3 border-t border-white/[0.16]" data-testid="extra-works">
      <div className="flex items-center gap-2">
        <div className="flex-1 text-[10px] uppercase tracking-widest text-white/55">lavori extra</div>
        <button type="button" onClick={scan} disabled={!!busy} data-testid="extra-scan" className="text-[12px] text-white/80 inline-flex items-center gap-1 active:opacity-70">
          {busy === "scan" ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />} Controlla il diario
        </button>
        <button type="button" onClick={() => setAdding((v) => !v)} aria-label="Aggiungi un lavoro extra" data-testid="extra-add" className="p-1 text-white/70"><Plus size={14} /></button>
      </div>
      {adding && (
        <div className="mt-2 flex gap-2">
          <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} autoFocus placeholder="Es. presa in più in bagno"
            className="h-9 flex-1 min-w-0 rounded-xl bg-white/10 px-3 text-[13.5px] text-white placeholder:text-white/40 outline-none" data-testid="extra-add-text" />
          <button type="button" onClick={add} className="h-9 px-3 rounded-full bg-white text-[#403A3C] text-[13px] font-medium">Aggiungi</button>
        </div>
      )}
      {!list.length && (
        <div className="py-3 text-[12.5px] text-white/65" data-testid="extra-empty">
          Confronto ogni nota del diario con il preventivo e la descrizione: se trovo un lavoro fatto che lì non c'è te lo segnalo qui e su Telegram,
          così puoi farlo approvare al cliente e fatturarlo.
        </div>
      )}
      {open.map(row)}
      {toApprove.length > 0 && (
        <button type="button" onClick={variant} disabled={!!busy} data-testid="extra-variant"
          className="mt-2 h-10 px-4 rounded-full bg-white text-[#403A3C] text-[13.5px] font-semibold inline-flex items-center gap-1.5 disabled:opacity-50">
          {busy === "variant" ? <Loader2 size={14} className="animate-spin" /> : <FileText size={14} />} Prepara la variante per il cliente ({toApprove.length})
        </button>
      )}
      {done.length > 0 && (
        <div className="mt-1">
          <button type="button" onClick={() => setShowDone((v) => !v)} className="text-[12px] text-white/60 py-1 inline-flex items-center gap-1">
            {showDone ? <ChevronDown size={13} /> : <ChevronRight size={13} />} Decisi ({done.length})
          </button>
          {showDone && done.map(row)}
        </div>
      )}
    </div>
  );
}

const OUTCOME_LABEL = { accettato: "Accettato", perso: "Perso", in_attesa: "In attesa" };

function QuoteView({ commessa, quotes, outcome, isAdmin, canWrite, onChanged, onLost }) {
  const [proposal, setProposal] = useState(null);
  const last = (quotes || [])[0];
  const d = last?.data || {};
  const setOutcome = async (o) => {
    if (o === "perso") { onLost(); return; }
    try { const r = await api.post(`/jobs/commesse/${commessa.id}/quote/outcome`, { outcome: o }); toast.success(r.data.message.split("\n")[0]); onChanged(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const chooseValue = async (choice) => {
    try { const r = await api.post(`/jobs/quotes/${last.id}/value`, { choice }); toast.success(r.data.message); onChanged(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const btn = "text-[12px] px-3 py-1.5 rounded-full bg-white/10 text-white active:opacity-70";
  return (
    <div data-testid="job-quote">
      {canWrite && (
        <div className="mt-1.5 flex items-center justify-center gap-5 text-[12px] text-white/80">
          <UploadAction commessaId={commessa.id} hint="preventivo" label={last ? "Carica una nuova versione" : "Carica il preventivo"}
            onResult={(r) => (r.type === "quote" ? setProposal(r) : (toast.success(r.message.split("\n")[0]), onChanged()))} />
        </div>
      )}
      {!last ? (
        <div className="mt-3 py-6 border-t border-white/[0.16] text-[13px] text-white/70" data-testid="quote-empty">
          Nessun preventivo. Caricalo qui o mandalo su Telegram (PDF, Word o foto): leggo totale, voci, date e attività e lo salvo quando confermi.
        </div>
      ) : (
        <div className="mt-3 pt-3 border-t border-white/[0.16]">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[15px] font-semibold text-white">Versione {last.version}</span>
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-white/10 text-white/85" data-testid="quote-outcome">{OUTCOME_LABEL[outcome] || "esito da registrare"}</span>
            {last.archive_link && <a href={last.archive_link} target="_blank" rel="noreferrer" className="text-[12px] text-white/70 underline">apri</a>}
          </div>
          <div className="text-[13.5px] text-white/85 mt-1 space-y-0.5">
            {(d.taxable || d.total) ? <div>💶 {d.taxable ? `Imponibile ${eur(d.taxable)}` : ""}{d.taxable && d.total ? " · " : ""}{d.total ? `Totale ${eur(d.total)}` : ""}</div> : null}
            {(d.start || d.end || d.validity) && <div>📅 {[d.start && `inizio ${shortDay(d.start)}`, d.end && `fine ${shortDay(d.end)}`, d.validity && `valido fino al ${shortDay(d.validity)}`].filter(Boolean).join(" · ")}</div>}
            {(d.payments || []).length > 0 && <div>💳 {d.payments.join("; ")}</div>}
            {d.labor_hours ? <div>👷 Ore uomo previste: {fmtNum(d.labor_hours)} h</div> : null}
            {(d.materials_planned || []).length > 0 && <div>🧰 Materiali previsti: {d.materials_planned.map((m) => [fmtNum(m.qty), m.unit, m.name].filter(Boolean).join(" ")).join("; ")}</div>}
            {d.warranty && <div>🛡 Garanzia: {d.warranty}</div>}
            {(d.maintenance || []).length > 0 && <div data-testid="quote-maintenance">🔧 Manutenzione: {d.maintenance.map((m) => m.text).join("; ")}
              <span className="text-white/55"> · a fine lavori fisso i promemoria</span></div>}
          </div>
          {last.value_pending && isAdmin && (
            <div className="mt-2 text-[12.5px] text-white/85" data-testid="quote-value-pending">
              Il valore del preventivo è diverso da quello della commessa:
              <button type="button" onClick={() => chooseValue("new")} className={`${btn} ml-2`}>Usa il nuovo</button>
              <button type="button" onClick={() => chooseValue("keep")} className={`${btn} ml-1`}>Tieni l'attuale</button>
            </div>
          )}
          {isAdmin && outcome !== "accettato" && commessa.stato !== "persa" && (
            <div className="mt-3 flex gap-2 flex-wrap" data-testid="quote-outcome-actions">
              <button type="button" onClick={() => setOutcome("accettato")} className={btn}>✅ Accettato</button>
              <button type="button" onClick={() => setOutcome("perso")} className={btn}>❌ Perso</button>
              <button type="button" onClick={() => setOutcome("in_attesa")} className={btn}>⏳ In attesa</button>
            </div>
          )}
          {(d.activities || []).length > 0 && (
            <div className="mt-3">
              <div className="text-[10px] uppercase tracking-widest text-white/55 mb-1">attività previste</div>
              {d.activities.map((a, i) => <div key={i} className="text-[13.5px] text-white/85 py-0.5">• {a}</div>)}
            </div>
          )}
          {(d.items || []).length > 0 && (
            <details className="mt-2"><summary className="text-[12px] text-white/60 cursor-pointer py-1">Voci ({d.items.length})</summary>
              {d.items.map((it, i) => <div key={i} className="flex gap-2 text-[12.5px] text-white/80 py-0.5"><span className="flex-1">{it.description}</span>
              {it.qty ? <span className="text-white/60 tabular-nums">{fmtNum(it.qty)}{it.unit ? ` ${it.unit}` : ""}</span> : null}{it.amount ? <span>{eur(it.amount)}</span> : null}</div>)}
            </details>
          )}
          {quotes.length > 1 && (
            <div className="mt-3">
              <div className="text-[10px] uppercase tracking-widest text-white/55 mb-1">versioni precedenti</div>
              {quotes.slice(1).map((v) => (
                <div key={v.id} className="text-[12.5px] text-white/70 py-0.5">v{v.version} · {shortDay((v.confirmed_at || "").slice(0, 10))}
                  {(v.data?.taxable || v.data?.total) ? ` · ${eur(v.data.taxable || v.data.total)}` : ""}
                  {v.archive_link && <a href={v.archive_link} target="_blank" rel="noreferrer" className="ml-2 underline">apri</a>}</div>
              ))}
            </div>
          )}
        </div>
      )}
      {proposal && <QuoteSheet commessa={commessa} proposal={proposal} onClose={() => setProposal(null)} onSaved={() => { setProposal(null); onChanged(); }} />}
    </div>
  );
}

// The margin at the end of the works, from the progress (or the history): how it is computed is said
function ForecastBlock({ f }) {
  const bad = f.margin < 0;
  const low = !bad && f.hist_margin_pct != null && f.margin_pct < f.hist_margin_pct / 2;
  return (
    <div className="mt-3 rounded-2xl bg-white/[0.07] px-3.5 py-3" data-testid="costs-forecast">
      <div className="text-[10px] uppercase tracking-widest text-white/55">previsione a fine lavori</div>
      <div className="mt-1 flex items-baseline gap-2 flex-wrap">
        <span className="text-[15px] font-semibold" style={{ color: bad ? "#F08A8A" : low ? "#F2C14E" : "#fff" }} data-testid="forecast-margin">
          Margine {eur(f.margin)} ({Math.round(f.margin_pct)}%)
        </span>
        <span className="text-[12.5px] text-white/70">costi {eur(f.cost)}</span>
      </div>
      <div className="text-[12px] text-white/65 mt-1 leading-snug">
        {f.basis === "andamento" ? `Al ritmo attuale: speso ${eur(f.cost_now)} con il ${f.progress_pct}% fatto (${f.progress_source}).`
          : f.basis === "storico" ? `Stima dal costo dei tuoi lavori simili${f.progress_pct != null ? ` (avanzamento ${f.progress_pct}%, ancora poco per il ritmo)` : ""}.`
          : "Lavori conclusi: è il costo registrato."}
        {f.hist_margin_pct != null && ` Nei lavori simili il margine è stato ${Math.round(f.hist_margin_pct)}%.`}
        {f.expected_end && ` Fine prevista ${shortDay(f.expected_end)}${f.delay_days > 0 ? ` (${f.delay_days} ${f.delay_days === 1 ? "giorno" : "giorni"} dopo il previsto)` : ""}.`}
        {f.confidence === "bassa" && " Stima indicativa: diventa più affidabile con l'avanzare dei lavori."}
        {!f.complete && " Ci sono ore o materiali senza tariffa: i costi sono per difetto."}
      </div>
    </div>
  );
}

function CostsView({ commessaId, onChanged }) {
  const [open, setOpen] = useState(readOpen);
  const toggle = (k) => setOpen((o) => {
    const n = { ...o, [k]: !o[k] };
    try { localStorage.setItem(COSTS_OPEN_KEY, JSON.stringify(n)); } catch { /* private mode */ }
    return n;
  });
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
  // a list's header with the arrow that closes / opens it
  const fold = (k, title, total, n, testid) => (
    <button type="button" onClick={() => toggle(k)} aria-expanded={open[k]} data-testid={testid}
      className={`${head} w-full flex items-center gap-2 text-left`}>
      <span className="flex-1">{title} · <span className="text-[13px]">{eur(total)}</span>{!open[k] && n ? <span className="normal-case tracking-normal text-white/45"> · {n} voc{n === 1 ? "e" : "i"}</span> : null}</span>
      <ChevronDown size={15} className={`text-white/60 transition-transform duration-200 ${open[k] ? "rotate-180" : ""}`} />
    </button>
  );
  const row = "flex items-center gap-3 py-2.5 border-t border-white/[0.16]";
  return (
    <div className="mt-2" data-testid="costs-view">
      {/* the quote, the costs, the margin */}
      <div className={row}>
        <span className="flex-1 text-[14px] text-white/90">Preventivo</span>
        <MoneyInput value={e.budget} onSave={setBudget} placeholder="0" testid="costs-budget" wide />
      </div>
      <div className={row}>
        <span className="flex-1 text-[14px] text-white/90">Costi</span>
        <span className="text-[15px] font-medium text-white" data-testid="costs-total">{eur(e.cost_total)}</span>
        <span className="w-9" />
      </div>
      <div className={row}>
        <span className="flex-1 text-[14px] text-white/90">Margine</span>
        <span className="text-[15px] font-medium text-white" data-testid="costs-margin">{e.budget ? eur(e.margin) : "—"}</span>
        <span className="w-9" />
      </div>
      {e.budget ? (
        <div className="pt-1 pb-1">
          <div className="h-1.5 rounded-full bg-white/15 overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${Math.min(100, pct || 0)}%`, background: barColor }} />
          </div>
          <div className="mt-1.5 text-[12px] text-white/70" data-testid="costs-pct">
            {pct >= 100 ? `Preventivo superato: speso il ${Math.round(pct)}%` : `Speso il ${Math.round(pct || 0)}% del preventivo`}
          </div>
          {e.forecast && <ForecastBlock f={e.forecast} />}
        </div>
      ) : <div className="text-[12px] text-white/55 pb-1">Inserisci il preventivo per vedere il margine.</div>}
      {!e.complete && (
        <div className="text-[12px] text-white/60" data-testid="costs-missing">
          Non conteggiati: {[e.unpriced_hours ? `${fmtNum(e.unpriced_hours)} h senza tariffa` : "", e.unpriced_materials.length ? `${e.unpriced_materials.length} material${e.unpriced_materials.length === 1 ? "e" : "i"} senza prezzo` : ""].filter(Boolean).join(", ")}: inseriscili qui sotto.
        </div>
      )}

      {fold("labor", "manodopera", e.labor_total, e.labor.length, "costs-labor-toggle")}
      {open.labor && (
        <div className={row}>
          <span className="flex-1 min-w-0">
            <span className="block text-[14px] text-white/90">Tariffa standard</span>
            <span className="block text-[11.5px] text-white/50">per chi non ha una tariffa sua</span>
          </span>
          <MoneyInput value={e.default_rate} onSave={(n) => costs(n === null ? { clear_default_rate: true } : { default_rate: n })} unit="€/h" testid="costs-default-rate" />
        </div>
      )}
      {open.labor && e.labor.map((x) => (
        <div key={x.who} className={row} data-testid="costs-labor-row">
          <span className="flex-1 min-w-0">
            <span className="block text-[14px] text-white/90 truncate">{x.who}</span>
            <span className="block text-[11.5px] text-white/50">{fmtNum(x.hours)} h{x.cost !== null ? ` · ${eur(x.cost)}` : " · senza tariffa"}</span>
          </span>
          <MoneyInput value={x.own_rate ? x.rate : null} placeholder={e.default_rate ? groupIt(e.default_rate) : ""} unit="€/h"
            onSave={(n) => costs({ rates: { [x.who]: n } })} testid={`costs-rate-${x.who}`} />
        </div>
      ))}
      {open.labor && e.labor.length === 0 && <div className="py-2.5 border-t border-white/[0.16] text-[13px] text-white/55">Nessuna ora registrata.</div>}

      {fold("materials", "materiali", e.materials_total, e.materials.length, "costs-materials-toggle")}
      {open.materials && e.materials.map((m) => (
        <div key={m.key} className={row} data-testid="costs-material-row">
          <span className="flex-1 min-w-0">
            <span className="block text-[14px] text-white/90 truncate">{m.name}</span>
            <span className="block text-[11.5px] text-white/50">
              {m.qty !== null ? `${fmtNum(m.qty)} ${m.unit || ""}` : "quantità non indicata"}{m.cost !== null ? ` · ${eur(m.cost)}` : ""}
            </span>
          </span>
          <MoneyInput value={m.price} unit={`€/${m.unit || "pz"}`} onSave={(n) => costs({ prices: [{ name: m.name, unit: m.unit || "", price: n }] })}
            testid={`costs-price-${m.key}`} />
        </div>
      ))}
      {open.materials && e.materials.length === 0 && <div className="py-2.5 border-t border-white/[0.16] text-[13px] text-white/55">Nessun materiale registrato.</div>}

      <div className={head}>altre spese · <span className="text-[13px]">{eur(e.extras_total)}</span></div>
      {e.extras.map((x) => (
        <div key={x.id} className={row} data-testid="costs-extra-row">
          <span className="flex-1 min-w-0">
            <span className="block text-[14px] text-white/90 truncate">{x.label}</span>
            <span className="block text-[11.5px] text-white/50">{shortDay(x.date)}{x.by ? ` · ${x.by}` : ""}{x.supplier ? ` · ${x.supplier}` : ""}{x.log_id ? " · dal diario" : ""}</span>
          </span>
          <span className="text-[14px] text-white">{eur(x.amount)}</span>
          <button type="button" onClick={() => delExtra(x)} aria-label="Elimina la spesa" className="p-1.5 text-white/55 hover:text-white"><Trash2 size={14} /></button>
        </div>
      ))}
      <div className="flex items-center gap-2 py-2.5 border-t border-white/[0.16]">
        <input value={label} onChange={(ev) => setLabel(ev.target.value)} placeholder="Es. noleggio ponteggio" data-testid="costs-extra-label"
          className="h-8 flex-1 min-w-0 rounded-lg bg-white/10 px-2 text-[13px] text-white placeholder:text-white/35 outline-none" />
        <input value={amount} onChange={(ev) => setAmount(ev.target.value)} placeholder="0" inputMode="decimal" data-testid="costs-extra-amount"
          onKeyDown={(ev) => { if (ev.key === "Enter") addExtra(); }}
          className="h-8 w-[72px] rounded-lg bg-white/10 px-2 text-right text-[13px] text-white placeholder:text-white/35 outline-none" />
        <span className="text-[12px] text-white/60">€</span>
        {/* keeps the field focused: a blur would bring the tab bar back under the finger */}
        <button type="button" onMouseDown={(ev) => ev.preventDefault()} onClick={addExtra} data-testid="costs-extra-add" aria-label="Aggiungi la spesa" className="h-8 w-8 shrink-0 rounded-full bg-white/15 flex items-center justify-center text-white"><Plus size={15} /></button>
      </div>
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
        {client.shared_by != null && (
          <span className="flex items-center gap-1 text-xs text-white/60 mt-0.5" data-testid="client-shared-by"><Users size={11} />condivisa da {client.shared_by || "un collega"}</span>
        )}
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
            {c.perm === "read" && <span className="text-[10.5px] text-white/50 shrink-0" data-testid="commessa-read-only">sola lettura</span>}
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
  const docRef = useRef(null);
  const taRef = useRef(null);
  const listRef = useRef(null);
  const [quote, setQuote] = useState(null);

  useEffect(() => { setMessages([]); setText(""); setPhotos([]); }, [commessa.id]);
  // a document of this commessa (a quote, survey notes…): "preventivo" in the message -> read as the quote
  const sendDoc = async (file) => {
    if (!file || busy) return;
    const said = text.trim();
    setMessages((ms) => [...ms, { role: "user", content: `${said ? said + "\n" : ""}📎 ${file.name}`, mode }]);
    setText("");
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (/\bpreventiv/i.test(said)) fd.append("hint", "preventivo");
      if (said) fd.append("caption", said);
      const r = (await api.post(`/jobs/commesse/${commessa.id}/documents`, fd)).data;
      if (r.type === "quote") {
        setMessages((ms) => [...ms, { role: "assistant", content: "📄 Ho letto il preventivo: controlla i dati e conferma." }]);
        setQuote(r);
      } else {
        setMessages((ms) => [...ms, { role: "assistant", content: r.message || "Documento salvato nel diario." }]);
        onSaved?.();
      }
    } catch (e) {
      setMessages((ms) => [...ms, { role: "assistant", content: "⚠️ " + (e.response?.data?.detail || "Non sono riuscito a leggere il documento") }]);
    } finally { setBusy(false); }
  };
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
    const ok = ["ok", "planned", "description", "commessa_update"].includes(r.data.status);
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
      {quote && <QuoteSheet commessa={commessa} proposal={quote} onClose={() => setQuote(null)}
        onSaved={() => { setQuote(null); setMessages((ms) => [...ms, { role: "assistant", content: "✅ Preventivo salvato: lo trovi nella sezione Preventivo e nel diario." }]); onSaved?.(); }} />}
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
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && window.matchMedia(`(min-width: ${MOBILE_BREAKPOINT}px)`).matches) { e.preventDefault(); send(); } }}
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
            <button onClick={() => docRef.current?.click()} disabled={busy} title="Documento (preventivo, sopralluogo…)" aria-label="Documento"
              data-testid="commessa-chat-doc" className="p-2 rounded-full text-white/90 hover:bg-white/15 disabled:opacity-50">
              <FileText size={19} />
            </button>
            <input ref={docRef} type="file" accept={DOC_ACCEPT} hidden data-testid="commessa-chat-doc-file" onChange={(e) => { sendDoc(e.target.files?.[0]); e.target.value = ""; }} />
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
  const [detailError, setDetailError] = useState(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [todoEditing, setTodoEditing] = useState(null);   // {} = new activity
  const [msEditing, setMsEditing] = useState(null);       // {} = new milestone
  const [contactsOpen, setContactsOpen] = useState(false);
  const [lostOpen, setLostOpen] = useState(false);
  const [closeCheck, setCloseCheck] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [updatesOpen, setUpdatesOpen] = useState(false);   // the client's weekly progress on Telegram
  const [siteOpen, setSiteOpen] = useState(false);
  const [tplOpen, setTplOpen] = useState(null);   // "apply" | "save"
  const [viewer, setViewer] = useState(null);   // {log, photo}
  const [section, setSection] = useState("diario");
  const [planTab, setPlanTab] = useState("tutto");   // Pianificazione: tutto | attivita | milestone | todo
  const [period, setPeriod] = useState({ key: "30" });
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [menu, setMenu] = useState(null);       // "stato" | "periodo" | "collab" | "onsite"
  // Admin: the collaborators (Telegram only) enabled on this commessa
  const { user: me } = useAuth();
  const access = detail?.access || { perm: "owner", is_owner: true, shared_by: null };
  const ro = access.perm === "read";                                   // shared with me read-only
  const isAdmin = !!me?.can_collaborators && access.shared_by == null && !ro;   // links collaborators (an administrator of the organization)
  const [shareOpen, setShareOpen] = useState(false);                   // the commessa shared with team-mates
  const [collabs, setCollabs] = useState(null);
  const loadCollabs = (id) => api.get(`/jobs/commesse/${id}/collaborators`).then((r) => setCollabs(r.data || [])).catch(() => setCollabs([]));
  useEffect(() => { if (isAdmin && selectedId) loadCollabs(selectedId); else setCollabs(null); }, [isAdmin, selectedId]); // eslint-disable-line react-hooks/exhaustive-deps
  const setCollabLevel = async (x, level) => {
    setCollabs((cs) => cs.map((c) => (c.id === x.id ? { ...c, level } : c)));
    try { await api.put(`/jobs/commesse/${selectedId}/collaborators/${x.id}`, { enabled: true, level }); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); loadCollabs(selectedId); }
  };
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
  // the menus open just under what opened them (the row of figures, the period)
  const detailBox = useRef(null), totalsRow = useRef(null), periodBtn = useRef(null);
  const under = (el) => (el && detailBox.current ? el.getBoundingClientRect().bottom - detailBox.current.getBoundingClientRect().top + 6 : undefined);

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
    setDetailError(null);
    try { setDetail((await api.get(`/jobs/commesse/${id}`, { params, timeout: 45000 })).data); }
    catch (e) {
      setDetail(null);
      if (e.response?.status === 404) { setSelectedId(null); setLevel("clients"); toast.error("Commessa non trovata"); return; }
      // never an endless "caricamento…": why, and try again
      const d = e.response?.data?.detail;
      setDetailError({ id, status: e.response?.status || null,
        message: (typeof d === "string" ? d : null) || (e.code === "ECONNABORTED" ? "Il server non risponde: riprova tra poco." : "Non sono riuscito ad aprire il diario di questa commessa.") });
    }
  };
  const reload = () => Promise.all([loadDetail(selectedId), loadList()]);
  useEffect(() => { loadList(); }, []);
  useEffect(() => { loadDetail(selectedId); }, [selectedId, period]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setSection("diario"); setPlanTab("tutto"); setMenu(null); setPeriod({ key: "30" }); }, [selectedId]);
  // back on top: the page, or (desktop split) the right column, which scrolls by itself
  useEffect(() => { (document.querySelector('[data-testid="split-right"]') || window).scrollTo({ top: 0 }); }, [level, selectedId]);
  useEffect(() => { if (level === "clients") setChatOpen(false); }, [level]);

  // one card per client, its commesse in state order (in corso first, chiuse last)
  const groups = useMemo(() => {
    const ql = q.trim().toLowerCase();
    const by = new Map();
    commesse.forEach((c) => {
      if (ql && !`${c.title} ${c.client_name} ${c.address}`.toLowerCase().includes(ql)) return;
      const g = by.get(c.client_item_id) || { id: c.client_item_id, name: c.client_name, address: "", commesse: [], last: "", shared_by: c.shared ? c.shared_by : null };
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
      if (!isClosed(c.stato)) x.active += 1;
    });
    return m;
  }, [commesse]);

  const openCommessa = (c) => { setSelectedId(c.id); setDetail((d) => (d?.commessa?.id === c.id ? d : null)); setLevel("diary"); };
  const setStato = async (stato, confirmClose = false) => {
    if (stato === "persa") { setLostOpen(true); return; }   // only with its reason
    try {
      await api.patch(`/jobs/commesse/${selectedId}/stato`, { stato, confirm_close: confirmClose });
      if (stato === "completata") toast.success("Commessa completata: preparo il report finale nella cartella Report");
      setCloseCheck(null); await reload();
    } catch (e) {
      const d = e.response?.data?.detail;
      if (d?.code === "close_check") { setCloseCheck(d); return; }
      toast.error((typeof d === "string" ? d : d?.message) || "Errore");
    }
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
  const detailFailed = detailError && detailError.id === selectedId ? (
    <div className="text-center py-10" data-testid="detail-error">
      <div className="text-[14px] text-white/85">{detailError.message}</div>
      {detailError.status && <div className="text-[11.5px] text-white/50 mt-1">Errore {detailError.status}</div>}
      <div className="mt-3 flex justify-center gap-2">
        <button type="button" onClick={() => loadDetail(selectedId)} data-testid="detail-retry" className="px-4 py-2 rounded-full bg-white text-[#403A3C] text-sm font-medium">Riprova</button>
        <button type="button" onClick={() => { setSelectedId(null); setLevel("clients"); }} className="px-4 py-2 rounded-full bg-white/15 text-white text-sm">Torna ai clienti</button>
      </div>
    </div>
  ) : null;

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
  const secs = SECTIONS.filter((x) => x.key !== "costi" || detail?.can_see_costs !== false);   // costs: who may see them
  const secAt = (i) => secs[(i + secs.length) % secs.length];
  const secIdx = Math.max(0, secs.findIndex((x) => x.key === section));
  const pickSection = (key) => {
    if (key === "milestone" || key === "todo") { setSection("pianificazione"); setPlanTab(key); }   // now inside Pianificazione
    else setSection(key);
    setMenu(null);
  };
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
    : section === "ore" ? lg.hours?.length > 0 || lg.hours_pending?.length > 0 || !!lg.hours_replaced_by
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
      + (pt.hours_pending_total ? ` · ${fmtNum(pt.hours_pending_total)} h da approvare (non contate)` : "")
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

  const diaryView = !c ? (detailFailed || loading) : (
    <div ref={detailBox} className="relative w-full" data-testid="commessa-detail">
      {/* only the commessa's name; the arrow goes back to its card */}
      <div className="flex items-center gap-2.5">
        <button onClick={() => setLevel("clients")} data-testid="job-back" aria-label="Torna ai clienti"
          className="h-[30px] w-[30px] shrink-0 rounded-full flex items-center justify-center text-white lg-frost">
          <ArrowLeft size={16} />
        </button>
        <h1 className="min-w-0 flex-1 text-[17px] font-semibold text-white truncate" data-testid="commessa-title">
          {c.codice && <span className="text-white/50 font-normal mr-1.5" data-testid="commessa-code">{c.codice}</span>}{c.title}
        </h1>
      </div>
      {/* me on site: "Sono in cantiere" / "Ho finito", like the collaborators on Telegram */}
      {access.shared_by != null && (
        <div className="mt-2 flex items-center gap-1.5 text-[12px] text-white/65" data-testid="commessa-shared-banner">
          <Users size={12} /> Condivisa da {access.shared_by || "un collega"} · {ro ? "sola lettura" : "puoi scriverci"}
        </div>
      )}
      {!ro && <PresencePill commessa={c} onChanged={() => loadDetail(selectedId)} />}

      {/* the commessa in one row that scrolls sideways: state, hours, reports, documents, then
          the card's details (site, dates, phone, e-mail) */}
      <div ref={totalsRow} className="mt-4 -mx-4 px-4 flex gap-7 overflow-x-auto no-scrollbar snap-x snap-mandatory scroll-px-4" data-testid="commessa-totals">
        <InfoCard icon={CircleDot} label="Stato" value={capFirst(c.stato || "senza stato")} testid="glance-stato"
          ariaLabel="Cambia lo stato della commessa" onClick={ro || detail.is_admin === false ? undefined : () => setMenu((m) => (m === "stato" ? null : "stato"))}
          note={c.stato === "persa" && c.lost_reason ? (LOST_CATEGORIES.find(([k]) => k === c.lost_reason.category) || [])[1] : ""} />
        <InfoCard icon={ScrollText} label="Attività" testid="glance-descrizione" ariaLabel="La descrizione delle attività da svolgere"
          value={c.descrizione ? (c.descrizione.split("\n")[0].slice(0, 26) + (c.descrizione.length > 26 ? "…" : "")) : "da descrivere"}
          onClick={() => pickSection("descrizione")} />
        {(detail.on_site || []).length > 0 && (
          // one: the name; more: how many and of which role - tapped, everyone by role
          <InfoCard icon={HardHat} label="In cantiere ora" testid="glance-on-site" ariaLabel="Chi sta lavorando ora in cantiere" wide
            onClick={() => setMenu((m) => (m === "onsite" ? null : "onsite"))}
            value={detail.on_site.length === 1 ? firstName(detail.on_site[0]) : `${detail.on_site.length} persone`}
            note={detail.on_site.length === 1 ? `dalle ${hhmmOf(detail.on_site[0].since)}${detail.on_site[0].far ? " · ⚠️ lontano" : ""}`
              : (onSiteSummary(detail.on_site) || detail.on_site.map(firstName).join(", "))} />
        )}
        <InfoCard icon={Clock} label="Ore" value={`${fmtNum(t.hours_total)} h`} testid="glance-ore" ariaLabel="Mostra le ore" onClick={() => pickSection("ore")}
          note={t.hours_pending_total ? `${fmtNum(t.hours_pending_total)} h da approvare` : ""} />
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
        {/* the site is on the map below; only without a position (no map) it is here, to set it */}
        {detail.geo?.lat == null && (
          <InfoCard icon={MapPin} label="Cantiere" value={c.address || "non indicato"} testid="info-cantiere"
            onClick={() => setSiteOpen(true)} ariaLabel="Il cantiere: indirizzo e posizione per le presenze" />
        )}
        <InfoCard icon={CalendarDays} label="Date" testid="info-date"
          value={c.data_inizio ? `${shortDay(c.data_inizio)} → ${c.data_fine ? shortDay(c.data_fine) : "in corso"}` : "non indicate"} />
        {c.client_phone && <InfoCard icon={Phone} label="Telefono" value={c.client_phone} href={`tel:${c.client_phone}`} testid="info-telefono" ariaLabel={`Chiama ${c.client_name}`} />}
        {c.client_email && <InfoCard icon={Mail} label="Email" value={c.client_email} href={`mailto:${c.client_email}`} testid="info-email" ariaLabel={`Scrivi a ${c.client_name}`} />}
        {access.is_owner && me?.org_id && (
          <InfoCard icon={Users} label="Condivisione" value={(detail.shared_count || 0) ? `${detail.shared_count} ${detail.shared_count === 1 ? "collega" : "colleghi"}` : "solo tu"}
            testid="info-condivisione" ariaLabel="Condividi il diario della commessa con i colleghi del team" onClick={() => setShareOpen(true)} />
        )}
        {access.is_owner && (
          <InfoCard icon={Send} label="Avanzamento" value="al cliente" testid="info-avanzamento"
            ariaLabel="Avanzamento settimanale al cliente su Telegram" onClick={() => setUpdatesOpen(true)} />
        )}
        {detail.is_admin && (
          <InfoCard icon={RefreshCw} label="Modifiche" value={String((detail.history || []).length)} testid="info-modifiche"
            note={(detail.history || [])[0] ? shortDay((detail.history[0].at || "").slice(0, 10)) : ""}
            ariaLabel="Lo storico delle modifiche della commessa" onClick={() => setHistoryOpen(true)} />
        )}
        {isAdmin && collabs && (
          <InfoCard icon={HardHat} label="Collaboratori" value={String(collabs.filter((x) => x.enabled).length)} testid="info-collaboratori"
            ariaLabel="Scegli i collaboratori abilitati su questa commessa" onClick={() => setMenu((m) => (m === "collab" ? null : "collab"))} />
        )}
      </div>

      {/* the site on the map, across the page; its bar hides it or opens it more */}
      <SiteMapBand geo={detail.geo} onSite={detail.on_site || []} address={c.address} onEditSite={() => setSiteOpen(true)} className="mt-4 -mx-4 md:-mx-8" />

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

      {/* Costi, Milestone, To Do and Descrizione: their own content instead of the period and the days */}
      {section === "sopralluogo" ? (
        <SurveyView commessa={c} survey={detail.survey} logs={detail.survey_logs || []} canWrite={!ro} onChanged={() => loadDetail(selectedId)} />
      ) : section === "preventivo" ? (
        <>
          <QuoteView commessa={c} quotes={detail.quotes || []} outcome={detail.quote_outcome} isAdmin={!!detail.is_admin} canWrite={!ro}
            onChanged={() => loadDetail(selectedId)} onLost={() => setLostOpen(true)} />
          {detail.can_see_costs && <HistoryEstimate commessa={c} />}
          {detail.is_admin && !ro && <ExtraWorksView commessa={c} rows={detail.extra_works || []} onChanged={() => loadDetail(selectedId)} />}
        </>
      ) : section === "descrizione" ? (
        <DescriptionView commessa={c} canEdit={!ro && (access.is_owner || me?.role === "admin")} budget={detail.economics?.budget}
          onChanged={() => loadDetail(selectedId)} />
      ) : section === "costi" ? (
        <div className={ro ? "pointer-events-none" : ""} data-testid={ro ? "costs-read-only" : undefined}>
          <CostsView commessaId={c.id} onChanged={() => loadDetail(selectedId)} />
        </div>
      ) : section === "pianificazione" ? (
        <div data-testid="job-plan-section">
          {/* planned activities on site, milestones and To Do: one place, all together or one kind at a time */}
          <div className="mt-1.5 flex justify-center">
            <span className="inline-flex rounded-full bg-white/10 p-0.5" data-testid="plan-tabs">
              {[["tutto", "Tutto", null], ["attivita", "Attività", (detail.activities || []).filter((x) => ["pianificata", "confermata", "in_corso"].includes(x.status)).length], ["milestone", "Milestone", msSum.total - msSum.done], ["todo", "To Do", openTodos]].map(([k, label, n]) => (
                <button key={k} type="button" onClick={() => setPlanTab(k)} data-testid={`plan-tab-${k}`}
                  className={`px-3 py-1 rounded-full text-[12px] transition-colors ${planTab === k ? "bg-white text-[#403A3C] font-semibold" : "text-white/75"}`}>
                  {label}{n ? <span className={planTab === k ? "text-[#403A3C]/60" : "text-white/50"}> {n}</span> : null}
                </button>
              ))}
            </span>
          </div>
          {(planTab === "tutto" || planTab === "attivita") && (
            <div data-testid="plan-block-attivita">
              {planTab === "tutto" && <div className="mt-4 text-[10px] uppercase tracking-widest text-white/55 text-center">attività in cantiere</div>}
              <PlanView commessa={c} activities={detail.activities || []} quotes={detail.quotes || []} meId={detail.me_id} isAdmin={!!detail.is_admin}
          canWrite={!ro} onChanged={() => loadDetail(selectedId)} />
            </div>
          )}
          {(planTab === "tutto" || planTab === "milestone") && (
            <div data-testid="plan-block-milestone">
              {planTab === "tutto" && <div className="mt-6 text-[10px] uppercase tracking-widest text-white/55 text-center">milestone</div>}
              <>
          <div className={`mt-1.5 flex items-center justify-center gap-2.5 ${ro ? "hidden" : ""}`}>
            <button type="button" onClick={() => setMsEditing({})} data-testid="job-milestone-add" aria-label="Nuova milestone"
              className="h-[34px] flex items-center gap-2 text-white/90 active:opacity-70 whitespace-nowrap">
              <Plus size={17} />
              <span className="text-[12px] font-medium tracking-[0.16em] uppercase text-white/85">Nuova milestone</span>
            </button>
          </div>
          <div className={`mt-0.5 flex items-center justify-center gap-4 text-[12px] text-white/75 ${ro ? "hidden" : ""}`}>
            <button type="button" onClick={() => setTplOpen("apply")} data-testid="ms-tpl-apply-btn" className="inline-flex items-center gap-1.5 active:opacity-70">
              <LayoutTemplate size={13} /> Da modello
            </button>
            {msSum.total > 0 && (
              <button type="button" onClick={() => setTplOpen("save")} data-testid="ms-tpl-save-btn" className="inline-flex items-center gap-1.5 active:opacity-70">
                <BookmarkPlus size={13} /> Salva come modello
              </button>
            )}
          </div>
          {msSum.total > 0 && (
            <div className="mt-0.5 text-center text-[11.5px] text-white/60" data-testid="job-milestone-count">
              {msSum.done}/{msSum.total} fatte
              {msSum.late ? <span style={{ color: LATE }}> · {msSum.late} in ritardo</span> : null}
              {msSum.done > 0 && <span data-testid="job-milestone-delays"> · {msSum.on_time} di {msSum.done} in tempo{msSum.avg_delay ? `, ritardo medio ${String(msSum.avg_delay).replace(".", ",")} g` : ""}</span>}
            </div>
          )}
          <div className="mt-3" data-testid="job-milestones">
            {milestones.map((m) => <MilestoneRow key={m.id} m={m} onToggle={ro ? () => {} : toggleMilestone} onOpen={ro ? () => {} : setMsEditing} />)}
            {milestones.length === 0 && (
              <div className="py-6 border-t border-white/[0.16] text-[13px] text-white/70" data-testid="job-milestones-empty">
                Nessuna milestone. Tocca «Nuova milestone» per segnare le tappe del lavoro: cosa, chi la esegue ed entro quando.
                Ti ricordo le scadenze su Telegram e, se una va in ritardo, puoi scrivere l'azione correttiva.
              </div>
            )}
          </div>
        </>
            </div>
          )}
          {(planTab === "tutto" || planTab === "todo") && (
            <div data-testid="plan-block-todo">
              {planTab === "tutto" && <div className="mt-6 text-[10px] uppercase tracking-widest text-white/55 text-center">to do</div>}
              <>
          <div className="mt-1.5 flex items-center justify-center gap-2.5">
            <button type="button" onClick={() => setTodoEditing({})} data-testid="job-todo-add" aria-label="Nuova attività"
              className={`h-[34px] flex items-center gap-2 text-white/90 active:opacity-70 ${ro ? "hidden" : ""}`}>
              <Plus size={17} />
              <span className="text-[12px] font-medium tracking-[0.16em] uppercase text-white/85">Nuova attività</span>
            </button>
            <span className="text-[12px] tracking-[0.16em] uppercase text-white/55" data-testid="job-todo-count">· {openTodos} da fare</span>
          </div>
          <div className="mt-3" data-testid="job-todos">
            {todos.map((x) => <TodoRow key={x.id} todo={x} onToggle={ro ? () => {} : toggleTodo} onOpen={ro ? () => {} : setTodoEditing} />)}
            {todos.length === 0 && (
              <div className="py-6 border-t border-white/[0.16] text-[13px] text-white/70" data-testid="job-todos-empty">
                Nessuna attività in programma. Tocca «Nuova attività» per segnare cosa c'è da fare, chi se ne occupa ed entro quando.
              </div>
            )}
          </div>
        </>
            </div>
          )}
        </div>
      ) : (<>
      {section === "ore" && detail.hours_plan && <HoursPlan plan={detail.hours_plan} />}
      {section === "ore" && (access.is_owner || me?.role === "admin") && (detail.hours_to_approve || []).length > 0 && (
        <div className="mt-1 mb-4" data-testid="hours-to-approve-list">
          <div className="text-[10px] uppercase tracking-widest text-white/55 text-center mb-1">ore da approvare</div>
          {detail.hours_to_approve.map((lg) => <HoursToApprove key={lg.id} log={lg} onDone={() => loadDetail(selectedId)} />)}
        </div>
      )}
      {section === "problemi" && (
        <ProblemsBlock problems={t.problems || []} canEdit={!ro} onChanged={() => loadDetail(selectedId)} />
      )}
      {section === "materiali" && detail.materials_plan && <MaterialsPlan plan={detail.materials_plan} />}
      {section === "materiali" && toTake.length > 0 && (
        <div className="mt-1 mb-4" data-testid="materials-to-take">
          <div className="text-[10px] uppercase tracking-widest text-white/55 text-center mb-1">da prendere</div>
          {toTake.map((x) => <TodoRow key={x.id} todo={x} onToggle={ro ? () => {} : toggleTodo} onOpen={ro ? () => {} : setTodoEditing} />)}
        </div>
      )}
      {/* the period */}
      <div className="mt-1.5 flex items-center justify-center gap-2.5">
        <button ref={periodBtn} type="button" onClick={() => setMenu((m) => (m === "periodo" ? null : "periodo"))} data-testid="period-btn" aria-label="Scegli il periodo"
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
                {g.logs.map((lg) => <DiaryLine key={lg.id} log={lg} section={section} me={me?.user_id} onOpen={(lg) => (ro ? null : lg.kind ? delLog(lg) : setEditing(lg))} onPhoto={(log, photo) => setViewer({ log, photo })} />)}
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
        <div role="menu" aria-label="Stato della commessa" data-testid="stato-menu" style={{ top: under(totalsRow.current) }} className="glass-panel absolute z-40 left-0 top-[112px] w-[236px] py-1">
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
      {menu === "onsite" && (detail.on_site || []).length > 0 && (
        <div role="dialog" aria-label="Chi è in cantiere ora" data-testid="on-site-menu" style={{ top: under(totalsRow.current) }} className="glass-panel absolute z-40 left-0 top-[112px] w-[300px] max-w-[calc(100vw-32px)] max-h-[60vh] overflow-y-auto px-5 pt-3.5 pb-3">
          <div className="text-[15px] font-semibold text-white mb-2.5">In cantiere ora · {detail.on_site.length}</div>
          <OnSiteList people={detail.on_site} />
        </div>
      )}
      {menu === "collab" && collabs && (
        <div role="menu" aria-label="Collaboratori abilitati" data-testid="collab-menu" style={{ top: under(totalsRow.current) }} className="glass-panel absolute z-40 right-0 top-[112px] w-[280px] py-1">
          {collabs.length === 0 && <div className="px-5 py-3.5 text-[13px] text-white/75">Nessun collaboratore: aggiungili in Impostazioni → Collaboratori.</div>}
          {collabs.map((x) => (
            <div key={x.id} className="relative">
            <button type="button" role="menuitemcheckbox" aria-checked={x.enabled} onClick={() => toggleCollab(x)} data-testid={`collab-toggle-${x.id}`}
              className={`glass-row w-full flex items-center gap-3.5 px-5 py-3 text-left text-[15px] text-white ${x.enabled ? "pr-[92px]" : ""}`}>
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
            {x.enabled && (
              <button type="button" onClick={() => setCollabLevel(x, x.level === "write" ? "read_write" : "write")} data-testid={`collab-level-${x.id}`}
                title={x.level === "write" ? "Può solo inviare informazioni: tocca per fargli anche chiedere" : "Può inviare e chiedere: tocca perché possa solo inviare"}
                className="absolute right-4 top-1/2 -translate-y-1/2 text-[10.5px] px-2 py-0.5 rounded-full bg-white/10 text-white/85">
                {x.level === "write" ? "solo invia" : "invia e chiede"}
              </button>
            )}
            </div>
          ))}
          <div className="px-5 pt-2.5 pb-3 text-[11px] text-white/55 border-t border-white/[0.13]">Con il pallino scrivono su questa commessa da Telegram; «invia e chiede» possono anche fare domande. I costi non li vedono mai.</div>
        </div>
      )}
      {menu === "periodo" && (
        <div role="dialog" aria-label="Periodo da consultare" data-testid="period-menu" style={{ top: under(periodBtn.current) }} className="glass-panel absolute z-40 left-1/2 -translate-x-1/2 top-[236px] w-[300px] pt-1 pb-3.5">
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
      {closeCheck && <CloseCheckSheet check={closeCheck} onClose={() => setCloseCheck(null)} onConfirm={() => setStato("completata", true)} />}
      {lostOpen && c && <LostSheet commessa={c} onClose={() => setLostOpen(false)} onSaved={() => { setLostOpen(false); reload(); }} />}
      {historyOpen && c && <HistorySheet rows={detail?.history || []} onClose={() => setHistoryOpen(false)} />}
      {contactsOpen && c && (
        <GlassBottomSheet onClose={() => setContactsOpen(false)} testid="contacts-sheet" className="max-h-[80vh] md:left-1/2 md:right-auto md:w-[480px] md:-translate-x-1/2 md:bottom-8">
          <div className="text-lg font-semibold text-white mb-3">Contatti · {c.title}</div>
          <CommessaContacts commessaId={c.id} onChanged={() => loadDetail(selectedId)} />
        </GlassBottomSheet>
      )}
      {updatesOpen && c && <ClientUpdatesSheet commessa={c} onClose={() => setUpdatesOpen(false)} />}
      {shareOpen && c && <CommessaShareSheet commessa={c} onClose={() => setShareOpen(false)} onChanged={() => loadDetail(selectedId)} />}
      {tplOpen === "apply" && c && <MilestoneTemplatesSheet commessa={c} onClose={() => setTplOpen(null)} onApplied={() => { setTplOpen(null); loadDetail(selectedId); }} />}
      {tplOpen === "save" && c && <SaveTemplateSheet commessa={c} onClose={() => setTplOpen(null)} />}
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
