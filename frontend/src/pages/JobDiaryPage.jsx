import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Search, Mic, Square, Camera, Loader2, Clock, Package, AlertTriangle, Trash2, Pencil, X, Plus, MapPin, Phone, Mail,
  NotebookPen, MessageCircle, Send, ChevronRight, RefreshCw, CalendarDays } from "lucide-react";
import { api, API } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { LiquidGlass, liquidPath, useMeasure, LIQUID_GAP } from "@/components/LiquidDock";
import { usePref } from "@/lib/prefs";

// Diario di commessa (verticale artigiano), three levels:
//   1. one card per client with its commesse and their state
//   2. the commessa's card (client, site, dates, description, totals)
//   3. its diary: name, state on one row (every change is written in the diary), totals,
//      entries by day.
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

function EntryCard({ log, onEdit, onDelete, onPhoto }) {
  if (log.kind === "stato") {
    return (
      <div data-testid="job-stato-event" className="flex items-center gap-2 px-4 py-2 rounded-2xl bg-white/[0.06] text-xs text-white/75">
        <RefreshCw size={12} className="shrink-0 text-white/55" />
        <span className="flex-1">{log.text}</span>
        <button onClick={() => onDelete(log)} title="Elimina" className="p-1 text-white/45 hover:text-white"><Trash2 size={12} /></button>
      </div>
    );
  }
  return (
    <div data-testid="job-entry" className="card-soft p-4">
      <div className="flex items-center gap-2 text-[11px] text-white/55">
        <span className="font-medium text-white/80">{log.author_name}</span>
        {log.channel === "telegram" && <span>· Telegram</span>}
        {log.channel === "watch" && <span>· orologio</span>}
        <button onClick={() => onEdit(log)} title="Modifica" className="ml-auto p-1 hover:text-white"><Pencil size={13} /></button>
        <button onClick={() => onDelete(log)} title="Elimina" className="p-1 hover:text-white" data-testid="job-entry-delete"><Trash2 size={13} /></button>
      </div>
      <div className="text-sm text-white/90 whitespace-pre-wrap mt-1.5">{log.text}</div>
      {(log.hours?.length > 0 || log.materials?.length > 0 || log.problems?.length > 0) && (
        <div className="flex flex-wrap gap-1.5 mt-2.5">
          {(log.hours || []).map((h, i) => (
            <span key={`h${i}`} className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-white/10 text-white/85"><Clock size={11} />{h.who} {fmtNum(h.hours)} h</span>
          ))}
          {(log.materials || []).map((m, i) => (
            <span key={`m${i}`} className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-white/10 text-white/85"><Package size={11} />{matLabel(m)}</span>
          ))}
          {(log.problems || []).map((p, i) => (
            <span key={`p${i}`} className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-[#E8663F]/25 text-white"><AlertTriangle size={11} />{p}</span>
          ))}
        </div>
      )}
      {log.photos?.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-3">
          {log.photos.map((p) => (
            <button key={p.id} onClick={() => onPhoto(log, p)} className="h-20 w-20 rounded-xl overflow-hidden bg-white/10">
              <img src={photoUrl(p.id)} alt="" loading="lazy" className="h-full w-full object-cover" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function EditDialog({ log, onClose, onSaved }) {
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

// The chat button: a glass circle (the bottom menu's "+" glass, a bit smaller) floating on
// the right at 3/4 of the screen's height, over the page that scrolls under it. It slides
// away while the page scrolls and comes back when it stops (one passive listener and a
// timer; the state changes only twice per scroll).
function ChatFab({ onClick }) {
  const [hidden, setHidden] = useState(false);
  const hiddenRef = useRef(false);
  useEffect(() => {
    let timer = null;
    const onScroll = () => {
      if (!hiddenRef.current) { hiddenRef.current = true; setHidden(true); }
      clearTimeout(timer);
      timer = setTimeout(() => { hiddenRef.current = false; setHidden(false); }, 450);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => { window.removeEventListener("scroll", onScroll); clearTimeout(timer); };
  }, []);
  return (
    <button onClick={onClick} data-testid="commessa-chat-toggle" data-hidden={hidden ? "1" : "0"}
      title="Chat della commessa: chiedi o scrivi nel diario" aria-label="Chat della commessa"
      className="fixed z-40 right-3.5 md:right-8 h-[52px] w-[52px] rounded-full flex items-center justify-center text-white active:scale-95"
      style={{
        top: "calc(75vh - 26px)",
        transform: hidden ? "translateX(calc(100% + 24px))" : "none",
        opacity: hidden ? 0 : 1,
        pointerEvents: hidden ? "none" : "auto",
        transition: "transform 260ms ease, opacity 200ms ease",
      }}>
      <span aria-hidden="true" className="lg-goo absolute inset-0 rounded-full" style={{ boxShadow: "0 10px 22px rgba(60, 10, 40, 0.16)" }} />
      <MessageCircle size={21} strokeWidth={1.9} className="relative" />
    </button>
  );
}

function Fact({ icon: Icon, label, children }) {
  return (
    <div className="flex items-start gap-2 text-sm">
      <Icon size={14} className="text-white/55 mt-0.5 shrink-0" />
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-widest text-white/50">{label}</div>
        <div className="text-white/90 break-words">{children}</div>
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

  const loadList = async () => {
    try { setCommesse((await api.get("/jobs/commesse")).data || []); }
    catch { toast.error("Errore nel caricamento delle commesse"); }
    finally { setLoaded(true); }
  };
  const loadDetail = async (id) => {
    if (!id) { setDetail(null); return; }
    try { setDetail((await api.get(`/jobs/commesse/${id}`)).data); }
    catch (e) {
      setDetail(null);
      if (e.response?.status === 404) { setSelectedId(null); setLevel("clients"); toast.error("Commessa non trovata"); }
    }
  };
  const reload = () => Promise.all([loadDetail(selectedId), loadList()]);
  useEffect(() => { loadList(); }, []);
  useEffect(() => { loadDetail(selectedId); }, [selectedId]);
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

  const byDay = useMemo(() => {
    const out = [];
    (detail?.logs || []).forEach((lg) => {
      const g = out[out.length - 1];
      if (g && g.day === lg.date) g.logs.push(lg); else out.push({ day: lg.date, logs: [lg] });
    });
    return out;
  }, [detail]);

  const openCommessa = (c) => { setSelectedId(c.id); setDetail((d) => (d?.commessa?.id === c.id ? d : null)); setLevel("commessa"); };
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
  const row = commesse.find((x) => x.id === selectedId);
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

  const commessaView = !c ? loading : (
    <div className="max-w-2xl">
      {back("Clienti", "clients")}
      <button onClick={() => setLevel("diary")} data-testid="commessa-card"
        className="w-full text-left card-soft card-hover p-5 flex flex-col gap-4">
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="text-xl font-semibold text-white leading-tight">{c.title}</div>
            <div className="text-sm text-white/75 mt-1">{c.client_name}</div>
          </div>
          <StatoPill stato={c.stato} />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Fact icon={MapPin} label="Cantiere">{c.address || "non indicato"}</Fact>
          <Fact icon={CalendarDays} label="Date">{c.data_inizio ? `dal ${shortDay(c.data_inizio)}` : "inizio non indicato"}{c.data_fine ? ` al ${shortDay(c.data_fine)}` : ""}</Fact>
          {c.client_phone && <Fact icon={Phone} label="Telefono"><a href={`tel:${c.client_phone}`} onClick={(e) => e.stopPropagation()} className="hover:underline">{c.client_phone}</a></Fact>}
          {c.client_email && <Fact icon={Mail} label="Email"><a href={`mailto:${c.client_email}`} onClick={(e) => e.stopPropagation()} className="hover:underline break-all">{c.client_email}</a></Fact>}
        </div>
        {c.descrizione && <div className="text-sm text-white/80 whitespace-pre-wrap">{c.descrizione}</div>}
        <div className="flex items-center gap-4 text-xs text-white/65 pt-3 border-t border-white/10">
          <span><b className="text-white text-base">{fmtNum(t.hours_total)}</b> h</span>
          <span><b className="text-white text-base">{t.entries}</b> voc{t.entries === 1 ? "e" : "i"}</span>
          {row?.last_day && <span>ultima {shortDay(row.last_day)}</span>}
          <span className="ml-auto inline-flex items-center gap-1 text-white font-medium">Apri il diario <ChevronRight size={14} /></span>
        </div>
      </button>
    </div>
  );

  const diaryView = !c ? loading : (
    <div className="flex flex-col gap-4 max-w-3xl" data-testid="commessa-detail">
      <div>
        {back(c.title, "commessa")}
        <div className="text-2xl font-semibold text-white leading-tight" data-testid="commessa-title">{c.title}</div>
        <div className="text-sm text-white/65 mt-0.5">{c.client_name}{c.address ? ` · ${c.address}` : ""}</div>
        {/* the state, on one row (scrolls sideways on a narrow phone); every change goes in the diary */}
        <div className="flex gap-1.5 mt-3 overflow-x-auto no-scrollbar" data-testid="stato-selector">
          {(detail.stati || []).map((s) => (
            <button key={s} onClick={() => s !== c.stato && setStato(s)}
              className={`shrink-0 whitespace-nowrap text-xs px-3 py-1.5 rounded-full inline-flex items-center gap-1.5 ${s === c.stato ? "bg-white text-[#403A3C] font-medium" : "bg-white/10 text-white/75 hover:bg-white/15"}`}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: STATO_COLOR[s] }} />{s}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3" data-testid="commessa-totals">
        <div className="card-soft p-4">
          <div className="kicker">ore</div>
          <div className="text-2xl font-semibold text-white mt-1">{fmtNum(t.hours_total)} h</div>
          <div className="text-[11px] text-white/60 mt-1">{Object.entries(t.by_person).map(([k, v]) => `${k} ${fmtNum(v)} h`).join(" · ") || "non ancora indicate"}</div>
        </div>
        <div className="card-soft p-4">
          <div className="kicker">materiali</div>
          {t.materials.length ? (
            <ul className="mt-1.5 space-y-0.5 text-xs text-white/85 max-h-28 overflow-y-auto">{t.materials.map((m, i) => <li key={i}>{matLabel(m)}</li>)}</ul>
          ) : <div className="text-xs text-white/55 mt-1.5">nessuno registrato</div>}
        </div>
        <div className="card-soft p-4">
          <div className="kicker">problemi</div>
          {t.problems.length ? (
            <ul className="mt-1.5 space-y-0.5 text-xs text-white/85 max-h-28 overflow-y-auto">{t.problems.map((p, i) => <li key={i}><span className="text-white/50">{shortDay(p.date)}</span> {p.text}</li>)}</ul>
          ) : <div className="text-xs text-white/55 mt-1.5">nessuno segnalato</div>}
        </div>
      </div>

      {byDay.length === 0 ? (
        <div className="text-sm text-white/60 text-center py-6">
          Ancora nessuna voce. Tocca il pulsante della chat <MessageCircle size={13} className="inline -mt-0.5" /> sul lato e scegli «Scrivi nel diario».
        </div>
      ) : byDay.map((g) => (
        <div key={g.day} className="flex flex-col gap-2">
          <div className="kicker px-1">{dayLabel(g.day)}</div>
          {g.logs.map((lg) => <EntryCard key={lg.id} log={lg} onEdit={setEditing} onDelete={delLog} onPhoto={(log, photo) => setViewer({ log, photo })} />)}
        </div>
      ))}
    </div>
  );

  const inCommessa = level !== "clients" && !!selectedId;
  return (
    <div className="w-full" data-testid="job-diary-page" style={chatOpen ? { paddingBottom: "min(62vh, 520px)" } : undefined}>
      <div className="flex items-center gap-2 mb-4">
        <NotebookPen size={20} className="text-white/80" />
        <h1 className="text-2xl font-semibold text-white">Diario di commessa</h1>
      </div>
      {level === "clients" || !selectedId ? clientsView : level === "commessa" ? commessaView : diaryView}

      {inCommessa && c && !chatOpen && <ChatFab onClick={() => setChatOpen(true)} />}
      {chatOpen && c && <CommessaChat commessa={c} onClose={() => setChatOpen(false)} onSaved={reload} />}
      {editing && (
        <EditDialog log={editing} onClose={() => setEditing(null)}
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
