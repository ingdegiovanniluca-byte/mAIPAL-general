import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Search, Mic, Square, Camera, Loader2, Clock, Package, AlertTriangle, Trash2, Pencil, X, Plus, MapPin, Phone, NotebookPen } from "lucide-react";
import { api, API } from "@/lib/api";
import { useIsMobile } from "@/hooks/use-is-mobile";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

// Diario di commessa (verticale artigiano): what was done on each job, day by day.
// Left the commesse (from the Clienti list), right the chosen one: totals, a box to dictate
// or write today's entry (with photos), and the entries by day.

const ACCENT = "#8E2E11";   // the Diario color
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

function CommessaRow({ c, selected, onClick }) {
  return (
    <button data-testid="commessa-row" onClick={onClick}
      className={`w-full text-left px-4 py-3 rounded-2xl transition-colors ${selected ? "bg-white/20" : "bg-white/[0.06] hover:bg-white/10"}`}>
      <div className="flex items-center gap-2">
        <span className="font-medium text-white truncate flex-1">{c.title}</span>
        <StatoPill stato={c.stato} />
      </div>
      <div className="text-xs text-white/65 truncate mt-0.5">{c.client_name}{c.address ? ` · ${c.address}` : ""}</div>
      <div className="text-[11px] text-white/45 mt-1">
        {c.entries ? `${c.entries} voc${c.entries === 1 ? "e" : "i"} · ${fmtNum(c.hours_total)} h · ultima ${shortDay(c.last_day)}` : "nessuna voce"}
      </div>
    </button>
  );
}

function EntryCard({ log, onEdit, onDelete, onPhoto }) {
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

export default function JobDiaryPage() {
  const isMobile = useIsMobile();
  const location = useLocation();
  const navigate = useNavigate();
  const [commesse, setCommesse] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [showClosed, setShowClosed] = useState(false);
  const [q, setQ] = useState("");
  const [selectedId, setSelectedId] = useState(() => location.state?.commessa || new URLSearchParams(location.search).get("commessa") || null);
  const [detail, setDetail] = useState(null);
  const [text, setText] = useState("");
  const [photos, setPhotos] = useState([]);   // data URIs waiting to be saved with the entry
  const [saving, setSaving] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [editing, setEditing] = useState(null);
  const [viewer, setViewer] = useState(null);   // {log, photo}
  const recRef = useRef(null);
  const fileRef = useRef(null);

  const loadList = async () => {
    try { setCommesse((await api.get("/jobs/commesse")).data || []); }
    catch { toast.error("Errore nel caricamento delle commesse"); }
    finally { setLoaded(true); }
  };
  const loadDetail = async (id) => {
    if (!id) { setDetail(null); return; }
    try { setDetail((await api.get(`/jobs/commesse/${id}`)).data); }
    catch (e) { setDetail(null); if (e.response?.status === 404) { setSelectedId(null); toast.error("Commessa non trovata"); } }
  };
  useEffect(() => { loadList(); }, []);
  useEffect(() => { loadDetail(selectedId); setText(""); setPhotos([]); }, [selectedId]);
  // desktop: with nothing chosen, the most recent open commessa
  useEffect(() => {
    if (!isMobile && !selectedId && commesse.length) setSelectedId(commesse[0].id);
  }, [isMobile, commesse, selectedId]);

  const visible = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return commesse.filter((c) => (showClosed || c.stato !== "chiusa")
      && (!ql || `${c.title} ${c.client_name} ${c.address}`.toLowerCase().includes(ql)));
  }, [commesse, q, showClosed]);
  const closedCount = commesse.filter((c) => c.stato === "chiusa").length;

  const byDay = useMemo(() => {
    const groups = [];
    (detail?.logs || []).forEach((lg) => {
      const g = groups[groups.length - 1];
      if (g && g.day === lg.date) g.logs.push(lg); else groups.push({ day: lg.date, logs: [lg] });
    });
    return groups;
  }, [detail]);

  const startRec = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported?.("audio/webm") ? "audio/webm" : "";
      const mr = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      const chunks = [];
      mr.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: mr.mimeType || "audio/webm" });
        setTranscribing(true);
        try {
          const fd = new FormData();
          fd.append("file", blob, "voice.webm");
          fd.append("action", "journal");
          const res = await fetch(`${API}/voice/transcribe`, { method: "POST", body: fd, credentials: "include" });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const t = ((await res.json()).text || "").trim();
          if (t) setText((x) => (x ? `${x} ${t}` : t));
          else toast.error("Non ho capito l'audio");
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

  const save = async () => {
    const body = text.trim() || (photos.length ? "Foto dal cantiere" : "");
    if (!body || !selectedId) return;
    setSaving(true);
    try {
      const r = await api.post("/jobs/logs", { text: body, images: photos, commessa_id: selectedId });
      setText(""); setPhotos([]);
      toast.success(r.data.message?.split("\n").slice(1).join(" · ") || "Salvato nel diario");
      await Promise.all([loadDetail(selectedId), loadList()]);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore nel salvataggio"); }
    finally { setSaving(false); }
  };

  const setStato = async (stato) => {
    try {
      await api.patch(`/jobs/commesse/${selectedId}/stato`, { stato });
      await Promise.all([loadDetail(selectedId), loadList()]);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const delLog = (log) => {
    toast("Eliminare questa voce del diario?", {
      action: { label: "Elimina", onClick: async () => {
        try { await api.delete(`/jobs/logs/${log.id}`); await Promise.all([loadDetail(selectedId), loadList()]); }
        catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
      } },
    });
  };
  const delPhoto = async () => {
    try {
      await api.delete(`/jobs/logs/${viewer.log.id}/photos/${viewer.photo.id}`);
      setViewer(null);
      await loadDetail(selectedId);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const t = detail?.totals;
  const c = detail?.commessa;

  const list = (
    <div className="flex flex-col gap-3 min-h-0" data-testid="commesse-list">
      <div className="flex items-center gap-2 px-3 h-10 rounded-full bg-white/10">
        <Search size={15} className="text-white/60" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cerca cliente o commessa" className="flex-1 bg-transparent text-sm text-white placeholder:text-white/45 outline-none" />
      </div>
      {!loaded ? <div className="kicker text-center py-8">caricamento…</div>
        : commesse.length === 0 ? (
          <div className="card-soft p-5 text-sm text-white/75" data-testid="no-commesse">
            Nessuna commessa ancora. Le commesse stanno sotto ogni cliente nella lista <b>Clienti</b>: aggiungile da Liste,
            oppure detta un sopralluogo all'agente Report, o una voce di diario nominando il cliente («oggi dai Rossi…»).
            <button onClick={() => navigate("/dashboard/liste")} className="block mt-3 text-xs px-3 py-1.5 rounded-full bg-white/15">Apri le Liste</button>
          </div>
        ) : (
          <div className="flex flex-col gap-2 overflow-y-auto">
            {visible.map((x) => <CommessaRow key={x.id} c={x} selected={x.id === selectedId} onClick={() => setSelectedId(x.id)} />)}
            {visible.length === 0 && <div className="text-xs text-white/55 px-2">Nessuna commessa trovata.</div>}
            {closedCount > 0 && (
              <button onClick={() => setShowClosed((v) => !v)} className="text-xs text-white/60 hover:text-white mt-1 self-start px-2">
                {showClosed ? "Nascondi le chiuse" : `Mostra le chiuse (${closedCount})`}
              </button>
            )}
          </div>
        )}
    </div>
  );

  const composer = (
    <div className="chat-input-card p-4 rounded-2xl" data-testid="job-composer">
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} data-testid="job-composer-text"
        placeholder="Cosa avete fatto? Chi ha lavorato e quante ore, materiali usati, problemi…"
        className="w-full bg-transparent text-sm text-white placeholder:text-white/45 outline-none resize-none" />
      {photos.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {photos.map((p, i) => (
            <div key={i} className="relative h-16 w-16 rounded-lg overflow-hidden">
              <img src={p} alt="" className="h-full w-full object-cover" />
              <button onClick={() => setPhotos((xs) => xs.filter((_, j) => j !== i))} className="absolute top-0.5 right-0.5 h-5 w-5 rounded-full bg-black/60 flex items-center justify-center"><X size={11} /></button>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2">
        <button onClick={recording ? stopRec : startRec} disabled={transcribing} title={recording ? "Ferma" : "Detta"} data-testid="job-mic"
          className={`h-9 w-9 rounded-full flex items-center justify-center ${recording ? "bg-[#E8663F] text-white" : "bg-white/10 text-white/85 hover:bg-white/15"}`}>
          {transcribing ? <Loader2 size={15} className="animate-spin" /> : recording ? <Square size={14} /> : <Mic size={15} />}
        </button>
        <button onClick={() => fileRef.current?.click()} title="Foto" className="h-9 w-9 rounded-full flex items-center justify-center bg-white/10 text-white/85 hover:bg-white/15">
          <Camera size={15} />
        </button>
        <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={(e) => { pickPhotos(e.target.files); e.target.value = ""; }} />
        <span className="text-[11px] text-white/45 flex-1 truncate">{recording ? "Sto ascoltando…" : transcribing ? "Trascrivo…" : "Ore, materiali e problemi li riconosco io"}</span>
        <button onClick={save} disabled={saving || recording || transcribing || (!text.trim() && !photos.length)} data-testid="job-save"
          className="px-4 h-9 rounded-full text-sm font-medium text-white disabled:opacity-40" style={{ background: ACCENT }}>
          {saving ? "Salvo…" : "Salva"}
        </button>
      </div>
    </div>
  );

  const detailView = c && (
    <div className="flex flex-col gap-4" data-testid="commessa-detail">
      <div className="card-soft p-5">
        <div className="flex items-start gap-3">
          {isMobile && <button onClick={() => setSelectedId(null)} className="p-1 -ml-1 text-white/80"><ArrowLeft size={18} /></button>}
          <div className="min-w-0 flex-1">
            <div className="text-xl font-semibold text-white leading-tight" data-testid="commessa-title">{c.title}</div>
            <div className="text-sm text-white/75 mt-1">{c.client_name}</div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1.5 text-xs text-white/60">
              {c.address && <span className="inline-flex items-center gap-1"><MapPin size={12} />{c.address}</span>}
              {c.client_phone && <a href={`tel:${c.client_phone}`} className="inline-flex items-center gap-1"><Phone size={12} />{c.client_phone}</a>}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5 mt-3" data-testid="stato-selector">
          {(detail.stati || []).map((s) => (
            <button key={s} onClick={() => s !== c.stato && setStato(s)}
              className={`text-[11px] px-2.5 py-1 rounded-full inline-flex items-center gap-1 ${s === c.stato ? "bg-white text-[#403A3C] font-medium" : "bg-white/10 text-white/75 hover:bg-white/15"}`}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: STATO_COLOR[s] }} />{s}
            </button>
          ))}
        </div>
      </div>

      {isMobile && composer}
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

      {!isMobile && composer}

      {byDay.length === 0 ? (
        <div className="text-sm text-white/60 text-center py-6">Ancora nessuna voce: racconta cosa è stato fatto oggi.</div>
      ) : byDay.map((g) => (
        <div key={g.day} className="flex flex-col gap-2">
          <div className="kicker px-1">{dayLabel(g.day)}</div>
          {g.logs.map((lg) => <EntryCard key={lg.id} log={lg} onEdit={setEditing} onDelete={delLog} onPhoto={(log, photo) => setViewer({ log, photo })} />)}
        </div>
      ))}
    </div>
  );

  return (
    <div className="w-full" data-testid="job-diary-page">
      <div className="flex items-center gap-2 mb-4">
        <NotebookPen size={20} className="text-white/80" />
        <h1 className="text-2xl font-semibold text-white">Diario di commessa</h1>
      </div>
      {isMobile ? (selectedId && c ? detailView : selectedId ? <div className="kicker text-center py-8">caricamento…</div> : list) : (
        <div className="grid grid-cols-3 gap-6">
          <aside className="col-span-1 lg:max-h-[calc(100vh-14rem)] flex flex-col">{list}</aside>
          <section className="col-span-2">{detailView || (loaded && commesse.length > 0 && <div className="kicker py-8">scegli una commessa</div>)}</section>
        </div>
      )}

      {editing && (
        <EditDialog log={editing} onClose={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await Promise.all([loadDetail(selectedId), loadList()]); toast.success("Voce aggiornata"); }} />
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
