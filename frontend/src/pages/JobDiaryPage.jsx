import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Search, Mic, Square, Camera, Loader2, Clock, Package, AlertTriangle, Trash2, Pencil, X, Plus, MapPin, Phone, Mail,
  NotebookPen, MessageCircle, Send, ChevronRight, RefreshCw, CalendarDays, CircleDot, FileText, Check } from "lucide-react";
import { api, API } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { LiquidGlass, liquidPath, useMeasure, LIQUID_GAP } from "@/components/LiquidDock";
import { usePref } from "@/lib/prefs";
import FloatingGlassButton from "@/components/FloatingGlassButton";

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
];
const PERIODS = [
  { key: "30", label: "Ultimi 30 giorni" },
  { key: "month", label: "Questo mese" },
  { key: "all", label: "Tutta la commessa" },
];
const periodRange = (p) => (p.key === "30" ? { from: daysAgoIso(29), to: todayIso() }
  : p.key === "month" ? { from: monthStartIso(), to: todayIso() }
  : p.key === "custom" ? { from: p.from || null, to: p.to || null }
  : { from: null, to: null });

// an item of the row on top of the diary: two lines only - the icon with a small caps label,
// the value under it (with a short grey note beside it when useful); no box behind
function InfoCard({ icon: Icon, label, value, note, onClick, href, testid, ariaLabel, external }) {
  const cls = "snap-start shrink-0 min-w-[92px] max-w-[190px] py-1 flex flex-col gap-1.5 text-left text-white"
    + (onClick || href ? " active:opacity-70" : "");
  const body = (
    <>
      <span className="flex items-center gap-1.5 min-w-0">
        <Icon size={14} className="text-white/55 shrink-0" />
        <span className="text-[10px] uppercase tracking-widest text-white/50 truncate">{label}</span>
      </span>
      <span className="flex items-baseline gap-1.5 min-w-0">
        <span className="text-[15px] font-medium text-white/90 truncate">{value}</span>
        {note && <span className="text-[11px] text-white/55 whitespace-nowrap">{note}</span>}
      </span>
    </>
  );
  if (href) return <a href={href} target={external ? "_blank" : undefined} rel={external ? "noreferrer" : undefined} data-testid={testid} aria-label={ariaLabel} className={cls}>{body}</a>;
  if (onClick) return <button type="button" onClick={onClick} data-testid={testid} aria-label={ariaLabel} className={cls}>{body}</button>;
  return <div data-testid={testid} aria-label={ariaLabel} className={cls}>{body}</div>;
}

// a line of the diary: who (grey) with a small icon when it carries hours / problems /
// materials, the text, the photos; tap to change or delete it
function DiaryLine({ log, section, onOpen, onPhoto }) {
  const isEvent = log.kind === "stato";
  const full = section === "diario";
  const detail = section === "ore" ? hoursLineOf(log) : section === "problemi" ? (log.problems || []).join("; ")
    : section === "materiali" ? (log.materials || []).map(matLabel).join(" · ") : "";
  return (
    <div data-testid={isEvent ? "job-stato-event" : "job-entry"}>
      <button type="button" onClick={() => onOpen(log)} className="w-full text-left">
        <span className="flex items-center gap-[5px] text-white/50">
          {isEvent && <RefreshCw size={11} strokeWidth={2} />}
          {full && !isEvent && log.hours?.length > 0 && <Clock size={11} strokeWidth={2} />}
          {full && !isEvent && log.problems?.length > 0 && <AlertTriangle size={11} strokeWidth={2} />}
          {full && !isEvent && log.materials?.length > 0 && <Package size={11} strokeWidth={2} />}
          <span className="text-[11.5px] font-medium">{log.author_name}</span>
          {log.channel === "telegram" && <span className="text-[10.5px] text-white/40">· Telegram</span>}
        </span>
        {detail && <span className="block mt-[3px] text-[14.5px] font-medium leading-snug text-white">{detail}</span>}
        <span className={`block mt-[3px] leading-[1.45] whitespace-pre-wrap ${isEvent ? "text-[13px] text-white/70"
          : full ? "text-[14px] text-white/90" : "text-[12.5px] text-white/55"}`}>
          {isEvent && log.stato_to ? `Stato: ${log.stato_from || "—"} → ${log.stato_to}` : log.text}
        </span>
      </button>
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
  const [text, setText] = useState(log.text || "");
  const [date, setDate] = useState(log.date || "");
  const [hours, setHours] = useState((log.hours || []).map((h) => ({ ...h, hours: fmtNum(h.hours) })));
  const [materials, setMaterials] = useState((log.materials || []).map((m) => ({ ...m, qty: fmtNum(m.qty) })));
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

function ClientCard({ client, commesse, onOpen }) {
  return (
    <div data-testid="client-group" className="card-soft p-4">
      <div className="font-semibold text-white text-base leading-snug">{client.name || "Cliente senza nome"}</div>
      {client.address && <div className="flex items-center gap-1 text-xs text-white/60 mt-0.5"><MapPin size={11} />{client.address}</div>}
      <div className="mt-3 flex flex-col gap-1.5">
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
      </div>
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

  const saveEntry = async (body, images, fromIdx = null) => {
    const r = await api.post("/jobs/logs", { text: body, images, commessa_id: commessa.id });
    setMessages((ms) => [...ms.map((m, i) => (i === fromIdx ? { ...m, offerSave: false } : m)), { role: "assistant", content: r.data.message, saved: true }]);
    onSaved();
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
  const [viewer, setViewer] = useState(null);   // {log, photo}
  const [section, setSection] = useState("diario");
  const [period, setPeriod] = useState({ key: "30" });
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [menu, setMenu] = useState(null);       // "stato" | "periodo"
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

  const openCommessa = (c) => { setSelectedId(c.id); setDetail((d) => (d?.commessa?.id === c.id ? d : null)); setLevel("diary"); };
  const setStato = async (stato) => {
    try { await api.patch(`/jobs/commesse/${selectedId}/stato`, { stato }); await reload(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const delLog = (log) => {
    toast(log.kind === "stato" ? "Togliere questo cambio di stato dal diario?" : "Eliminare questa voce del diario?", {
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
          {groups.map((g) => <ClientCard key={g.id} client={g} commesse={g.commesse} onOpen={openCommessa} />)}
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
        <InfoCard icon={Clock} label="Ore" value={`${fmtNum(t.hours_total)} h`} testid="glance-ore" ariaLabel="Mostra le ore" onClick={() => pickSection("ore")} />
        <InfoCard icon={AlertTriangle} label="Segnalazioni" value={String(t.problems.length)} testid="glance-problemi" ariaLabel="Mostra i problemi"
          onClick={() => pickSection("problemi")} note={t.problems.length ? `ultima ${shortDay(t.problems.map((x) => x.date || "").sort().pop())}` : ""} />
        <InfoCard icon={FileText} label="Documenti" value={String(docs.total)} testid="glance-documenti" ariaLabel={`${docs.photos || 0} foto e ${docs.reports || 0} report`} />
        <InfoCard icon={MapPin} label="Cantiere" value={c.address || "non indicato"} testid="info-cantiere"
          href={c.address ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(c.address)}` : undefined} external ariaLabel="Apri il cantiere sulla mappa" />
        <InfoCard icon={CalendarDays} label="Date" testid="info-date"
          value={c.data_inizio ? `${shortDay(c.data_inizio)} → ${c.data_fine ? shortDay(c.data_fine) : "in corso"}` : "non indicate"} />
        {c.client_phone && <InfoCard icon={Phone} label="Telefono" value={c.client_phone} href={`tel:${c.client_phone}`} testid="info-telefono" ariaLabel={`Chiama ${c.client_name}`} />}
        {c.client_email && <InfoCard icon={Mail} label="Email" value={c.client_email} href={`mailto:${c.client_email}`} testid="info-email" ariaLabel={`Scrivi a ${c.client_name}`} />}
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
                {g.logs.map((lg) => <DiaryLine key={lg.id} log={lg} section={section} onOpen={(lg) => (lg.kind ? delLog(lg) : setEditing(lg))} onPhoto={(log, photo) => setViewer({ log, photo })} />)}
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
