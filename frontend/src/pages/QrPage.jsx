import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { QrCode, Plus, ArrowLeft, ChevronRight, ChevronDown, Printer, Download, RefreshCw, Trash2, Link2, X, Check, FileText, Upload, Image as ImageIcon, Loader2, MapPin, Box, Crosshair, Search, Tag, Type, Briefcase, Eye, Palette, Layers, Maximize2, SlidersHorizontal } from "lucide-react";
import { api, API } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { phonePosition } from "@/pages/QrScanPage";

// The augmented reality (three.js and the readers): loaded only when tried.
const QrArViewer = React.lazy(() => import("@/components/QrArViewer"));

/* QR (administrator): the organization's labels for tools, sites and info points. The label holds only a link
   with a code: what it shows is written here and can be changed at any time without printing it again. Only who
   is in the organization opens it (see QrScanPage). */

const KINDS = [["cantiere", "Cantiere"], ["attrezzo", "Attrezzo"], ["punto", "Punto informativo"], ["altro", "Altro"]];
const VISIBILITY = [["public", "Pubblico"], ["org", "Solo organizzazione"], ["admins", "Solo amministratori"]];
const VISIBILITY_NOTE = {
  public: "Lo vede chiunque, anche senza account: non scrivere dati riservati. Commessa e cliente non si vedono.",
  org: "Solo chi è nella tua organizzazione, dopo l'accesso a mAIPAL.",
  admins: "Solo gli amministratori della tua organizzazione.",
};
const VISIBILITY_SHORT = { public: "Pubblico: lo vede chiunque lo scansioni", org: "Lo vede tutta l'organizzazione", admins: "Lo vedono solo gli amministratori" };
const IT_MONTHS_SHORT = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const when = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getDate()} ${IT_MONTHS_SHORT[d.getMonth()]} ${d.getFullYear()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};
const CHANGED = { ar: "realtà aumentata", place: "luogo", files: "file", title: "nome", kind: "tipo", text: "testo", links: "link", commessa_id: "commessa", visibility: "chi lo vede", active: "attivo", code: "codice" };

// A button of the editor tapped while typing: the field keeps the focus, so the keyboard closing doesn't bring the
// bottom bar under the finger and swallow the tap (see "Crea QR").
const keepFocus = (e) => e.preventDefault();

/* The form's pieces: the label above, the field with its icon on the left, the dropdowns with their chevron. */
const INPUT = "h-11 w-full min-w-0 rounded-xl bg-white/10 border border-white/15 text-sm text-white placeholder:text-white/40 outline-none focus:border-white/45 focus:bg-white/[0.14] transition-colors";

function Field({ label, hint, children, testid, className = "" }) {
  return (
    <div className={`flex flex-col gap-1.5 min-w-0 ${className}`} data-testid={testid}>
      {label && <span className="text-[12px] font-medium text-white/85">{label}</span>}
      {children}
      {hint && <span className="text-[11px] text-white/55 leading-snug">{hint}</span>}
    </div>
  );
}

function Input({ icon: Icon, className = "", ...p }) {
  return (
    <div className="relative min-w-0">
      {Icon && <Icon size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-white/50 pointer-events-none" />}
      <input {...p} className={`${INPUT} ${Icon ? "pl-10" : "pl-3.5"} pr-3.5 ${className}`} />
    </div>
  );
}

// a native dropdown (the phone's own picker): options [[value, label]], value given back with its own type
function Select({ icon: Icon, value, onChange, options, testid, placeholder }) {
  return (
    <div className="relative min-w-0">
      {Icon && <Icon size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-white/50 pointer-events-none" />}
      <select value={String(value ?? "")} data-testid={testid}
        onChange={(e) => { const o = options.find(([k]) => String(k) === e.target.value); onChange(o ? o[0] : e.target.value); }}
        className={`${INPUT} appearance-none truncate ${Icon ? "pl-10" : "pl-3.5"} pr-10 cursor-pointer`}>
        {placeholder != null && <option value="" disabled hidden className="text-black">{placeholder}</option>}
        {options.map(([k, label]) => <option key={k} value={String(k)} className="text-black">{label}</option>)}
      </select>
      <ChevronDown size={16} className="absolute right-3.5 top-1/2 -translate-y-1/2 text-white/60 pointer-events-none" />
    </div>
  );
}

const PRIMARY = "h-11 rounded-xl text-sm font-semibold bg-white/90 text-[#7A2A5C] disabled:opacity-60 inline-flex items-center justify-center gap-1.5";
const SECONDARY = "h-11 rounded-xl text-sm font-medium bg-white/10 border border-white/15 text-white/90 disabled:opacity-60 inline-flex items-center justify-center gap-1.5";

function QrTile({ q, onOpen }) {
  return (
    <div role="button" tabIndex={0} data-testid="qr-tile" onClick={onOpen} onKeyDown={(e) => { if (e.key === "Enter") onOpen(); }}
      className={`w-full text-left rounded-[20px] px-3 h-[64px] flex items-center gap-3 backdrop-blur-xl cursor-pointer ${q.active ? "bg-white/[0.22] border border-white/30" : "bg-white/[0.07] border border-white/10"}`}>
      <span className="w-9 h-9 rounded-xl bg-white/12 flex items-center justify-center shrink-0"><QrCode size={17} /></span>
      <span className="flex-1 min-w-0">
        <span className="block text-[13px] font-semibold text-white leading-tight truncate" data-testid="qr-tile-title">{q.title}</span>
        <span className="block text-[11px] text-white/60 leading-tight mt-0.5 truncate">
          {q.kind_label}{q.visibility === "public" ? " · pubblico" : ""}{q.place?.on ? " · solo sul posto" : ""}{q.commessa ? ` · ${q.commessa.title}` : ""} · {q.code_label}{q.active ? "" : " · disattivato"}
        </span>
      </span>
      <ChevronRight size={14} className="shrink-0 text-white/45" />
    </div>
  );
}

// the label, printed from a page of its own (the browser's print: on A4 or a label printer)
function printLabel(q, cm) {
  const w = window.open("", "_blank", "width=480,height=640");
  if (!w) { toast.error("Il browser ha bloccato la finestra di stampa"); return; }
  const esc = (s) => String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(q.title)}</title>
<style>@page{margin:10mm}body{margin:0;font-family:Poppins,Arial,sans-serif;color:#111}
.l{display:inline-flex;flex-direction:column;align-items:center;gap:2mm;padding:3mm;border:0.3mm dashed #bbb;border-radius:2mm;width:${cm + 0.6}cm}
.l img{width:${cm}cm;height:${cm}cm}.t{font-size:${cm >= 4 ? 10 : 8}pt;font-weight:600;text-align:center;line-height:1.15;max-width:${cm}cm;word-break:break-word}
.c{font-size:${cm >= 4 ? 9 : 7}pt;letter-spacing:.06em;font-family:monospace}</style></head>
<body><div class="l"><img src="${q.images.svg}" alt=""><div class="t">${esc(q.title)}</div><div class="c">${esc(q.code_label)}</div></div>
<script>window.onload=function(){setTimeout(function(){window.print()},150)}</script></body></html>`);
  w.document.close();
}

const RADII = [[50, "50 m"], [100, "100 m"], [250, "250 m"], [500, "500 m"], [1000, "1 km"]];
const radiusLabel = (m) => (m >= 1000 ? `${(m / 1000).toString().replace(".", ",")} km` : `${m} m`);
const mapLink = (p) => `https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=18/${p.lat}/${p.lon}`;

/* Where the QR opens: anywhere, or only within a distance of a point (the admin's position now, the commessa's
   site, an address). Checked against the phone's position when it is scanned. */
function QrPlace({ place, setPlace, commessaId }) {
  const [busy, setBusy] = useState(null);
  const [source, setSource] = useState("");
  const [address, setAddress] = useState("");
  const on = !!place?.on;
  const set = (x) => setPlace({ radius_m: 100, label: "", ...(place || {}), ...x, on: true });
  const mine = async () => {
    setBusy("me");
    try {
      const p = await phonePosition();
      set({ lat: +p.lat.toFixed(6), lon: +p.lon.toFixed(6) });
      if (p.acc > 100) toast.message(`Posizione presa con una precisione di ${p.acc} m: se puoi, riprova all'aperto`);
    } catch (e) { toast.error(e.message); }
    finally { setBusy(null); }
  };
  const lookup = async (body, what) => {
    setBusy(what);
    try { const r = await api.post("/qr/place-lookup", body); set({ lat: r.data.lat, lon: r.data.lon, label: (place?.label || r.data.label || "").slice(0, 80) }); }
    catch (e) { toast.error(e.response?.data?.detail || "Posizione non trovata"); }
    finally { setBusy(null); }
  };
  const run = (v) => (v === "mine" ? mine() : v === "commessa" ? lookup({ commessa_id: commessaId }, "job") : null);
  const pick = (v) => { setSource(v); run(v); };
  const sources = [["mine", "La mia posizione adesso"], ...(commessaId ? [["commessa", "Il cantiere della commessa"]] : []), ["address", "Un indirizzo"]];
  const radius = place?.radius_m || 100;
  return (
    <div className="flex flex-col gap-4" data-testid="qr-place">
      <Field label="Dove si apre">
        <Select icon={MapPin} value={on ? "here" : "any"} testid="qr-place-mode"
          options={[["any", "Ovunque"], ["here", "Solo in un luogo"]]}
          onChange={(v) => (v === "here" ? set({}) : setPlace({ ...(place || {}), on: false }))} />
      </Field>
      {on && (
        <>
          <Field label="Punto">
            <Select icon={Crosshair} value={source} onChange={pick} options={sources} testid="qr-place-source"
              placeholder={place.lat != null ? "Punto già scelto" : "Scegli il punto"} />
          </Field>
          {source === "address" && (
            <form className="relative" onSubmit={(e) => { e.preventDefault(); if (address.trim()) lookup({ address }, "addr"); }}>
              <Input icon={Search} value={address} onChange={(e) => setAddress(e.target.value)} placeholder="Via, numero, comune"
                className="pr-[84px]" data-testid="qr-place-address" />
              <button type="submit" disabled={!!busy || !address.trim()} data-testid="qr-place-search"
                className="absolute right-1.5 top-1/2 -translate-y-1/2 h-8 px-3 rounded-lg bg-white/85 text-[#7A2A5C] text-xs font-semibold disabled:opacity-50">
                {busy === "addr" ? <Loader2 size={13} className="animate-spin" /> : "Cerca"}</button>
            </form>
          )}
          {(place.lat != null || busy) && (
            <div className="flex items-center gap-2 text-[12px] text-white/75 -mt-1" data-testid="qr-place-point">
              {busy && busy !== "addr" ? <><Loader2 size={13} className="animate-spin" /> Cerco la posizione…</> : (
                <>
                  <span className="truncate">{place.lat.toFixed(5)}, {place.lon.toFixed(5)}</span>
                  <a href={mapLink(place)} target="_blank" rel="noopener noreferrer" className="underline shrink-0">mappa</a>
                  {(source === "mine" || source === "commessa") && (
                    <button type="button" onClick={() => run(source)} onMouseDown={keepFocus} aria-label="Aggiorna la posizione"
                      className="ml-auto h-7 w-7 shrink-0 rounded-lg bg-white/10 flex items-center justify-center"><RefreshCw size={13} /></button>
                  )}
                </>
              )}
            </div>
          )}
          <div className="grid grid-cols-[1fr_116px] gap-3">
            <Field label="Nome del luogo">
              <Input icon={Tag} value={place.label || ""} onChange={(e) => set({ label: e.target.value })} maxLength={80}
                placeholder="Facoltativo" data-testid="qr-place-label" />
            </Field>
            <Field label="Entro">
              <Select value={radius} onChange={(r) => set({ radius_m: r })} options={RADII} testid="qr-place-radius" />
            </Field>
          </div>
          <span className="text-[11px] text-white/55 leading-snug -mt-2">
            Si apre solo entro {radiusLabel(radius)}; gli amministratori ovunque. La posizione del telefono si può falsificare: è un filtro in più, non una protezione.
          </span>
        </>
      )}
    </div>
  );
}

function QrEditor({ initial, commesse, onSaved, onCancel }) {
  const [title, setTitle] = useState(initial?.title || "");
  const [kind, setKind] = useState(initial?.kind || "cantiere");
  const [text, setText] = useState(initial?.text || "");
  const [links, setLinks] = useState(initial?.links?.length ? initial.links : []);
  const [commessaId, setCommessaId] = useState(initial?.commessa_id || "");
  const [visibility, setVisibility] = useState(initial?.visibility || "org");
  const [place, setPlace] = useState(initial?.place || null);
  const [style, setStyle] = useState(initial?.style || "maipal");
  const [busy, setBusy] = useState(false);
  const setLink = (i, k, v) => setLinks((xs) => xs.map((x, j) => (j === i ? { ...x, [k]: v } : x)));

  const save = async () => {
    if (place?.on && place.lat == null) { toast.error("Scegli il luogo in cui si apre il QR, o metti «Ovunque»"); return; }
    setBusy(true);
    const body = { title, kind, text, links: links.filter((l) => (l.url || "").trim()), commessa_id: commessaId, visibility,
      place: place?.on ? place : { on: false }, style };
    try {
      const r = initial?.id ? await api.patch(`/qr/${initial.id}`, body) : await api.post("/qr", body);
      toast.success(initial?.id ? "Contenuto aggiornato: l'etichetta stampata resta la stessa" : "QR creato");
      onSaved(r.data);
    } catch (e) { toast.error(e.response?.data?.detail || "Non salvato"); }
    finally { setBusy(false); }
  };

  return (
    <div className="card-soft p-5 flex flex-col gap-4" data-testid="qr-editor">
      <Field label="Nome">
        <Input icon={Type} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} placeholder="Es. Cantiere Rossi · ingresso"
          data-testid="qr-title" />
      </Field>
      <Field label="Tipo">
        <Select icon={Tag} value={kind} onChange={setKind} options={KINDS} testid="qr-kind" />
      </Field>
      {commesse.length > 0 && (
        <Field label="Commessa">
          <Select icon={Briefcase} value={commessaId} onChange={setCommessaId} testid="qr-commessa"
            options={[["", "Nessuna"], ...commesse.map((c) => [c.id, `${c.title}${c.client_name ? ` · ${c.client_name}` : ""}`])]} />
        </Field>
      )}
      <Field label="Cosa mostra">
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} maxLength={5000} data-testid="qr-text"
          placeholder={"Es. Referente: Marco 333 1234567\nCancello: codice 4521"}
          className="w-full min-w-0 rounded-xl bg-white/10 border border-white/15 px-3.5 py-3 text-sm text-white placeholder:text-white/40 outline-none focus:border-white/45 focus:bg-white/[0.14] transition-colors leading-relaxed resize-none" />
      </Field>
      <Field label="Link">
        {links.map((l, i) => (
          <div key={i} className="grid grid-cols-[96px_1fr_44px] gap-2" data-testid="qr-link-row">
            <Input value={l.label || ""} onChange={(e) => setLink(i, "label", e.target.value)} placeholder="Nome" />
            <Input icon={Link2} value={l.url || ""} onChange={(e) => setLink(i, "url", e.target.value)} placeholder="https://…" inputMode="url" data-testid="qr-link-url" />
            <button type="button" onClick={() => setLinks((xs) => xs.filter((_, j) => j !== i))} aria-label="Togli il link"
              className="h-11 w-11 rounded-xl bg-white/10 border border-white/15 flex items-center justify-center text-white/75"><X size={15} /></button>
          </div>
        ))}
        {links.length < 10 && (
          <button type="button" onClick={() => setLinks((xs) => [...xs, { label: "", url: "" }])} data-testid="qr-add-link" onMouseDown={keepFocus}
            className="h-11 rounded-xl border border-dashed border-white/25 text-[13px] text-white/80 inline-flex items-center justify-center gap-1.5">
            <Plus size={15} /> {links.length ? "Un altro link" : "Aggiungi un link (planimetria, scheda, Drive…)"}
          </button>
        )}
      </Field>
      <Field label="Chi lo vede" hint={<span data-testid="qr-visibility-note">{VISIBILITY_NOTE[visibility]}</span>}>
        <Select icon={Eye} value={visibility} onChange={setVisibility} options={VISIBILITY} testid="qr-visibility" />
      </Field>
      <QrPlace place={place} setPlace={setPlace} commessaId={commessaId} />
      <Field label="Aspetto" testid="qr-style-box"
        hint={`${style === "maipal" ? "Forma e colori del logo mAIPAL, con il logo al centro." : "Bianco e nero: si legge anche piccolo o sbiadito."}${initial?.id && initial.style !== style ? " Cambiando aspetto ristampa l'etichetta (per la realtà aumentata serve la nuova)." : ""}`}>
        <Select icon={Palette} value={style} onChange={setStyle} options={[["maipal", "mAIPAL"], ["classic", "Classico"]]} testid="qr-style" />
      </Field>
      <div className={`grid gap-3 pt-1 ${onCancel ? "grid-cols-2" : "grid-cols-1"}`}>
        {onCancel && <button type="button" onClick={onCancel} onMouseDown={keepFocus} className={SECONDARY}>Annulla</button>}
        {/* (onMouseDown: the field keeps the focus, so the keyboard closing doesn't bring the bottom bar under the finger
            and swallow the tap) */}
        <button type="button" onClick={save} onMouseDown={keepFocus} disabled={busy} data-testid="qr-save" className={PRIMARY}>
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} {initial?.id ? "Salva" : "Crea QR"}
        </button>
      </div>
    </div>
  );
}

const sizeLabel = (n) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1).replace(".", ",")} MB` : `${Math.max(1, Math.round((n || 0) / 1024))} KB`);
const MAX_FILES = 5;

/* The photos and PDFs on the QR: who scans it sees them (with the QR's own visibility). From the phone (gallery,
   camera, files) or, for a QR linked to a commessa, one of its photos. */
function QrFiles({ q, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [photos, setPhotos] = useState(null);   // the commessa's photos, when the picker is open
  const input = useRef(null);
  const files = q.files || [];
  const upload = async (list) => {
    const all = Array.from(list || []);
    const picked = all.slice(0, MAX_FILES - files.length);
    if (all.length > picked.length) toast.error(`Al massimo ${MAX_FILES} file per QR`);
    if (!picked.length) return;
    setBusy(true);
    let last = null;
    for (const f of picked) {
      const fd = new FormData();
      fd.append("file", f, f.name);
      try { last = (await api.post(`/qr/${q.id}/files`, fd)).data; }
      catch (e) { toast.error(`${f.name}: ${e.response?.data?.detail || "non caricato"}`); }
    }
    if (last) { onChanged(last); toast.success(picked.length > 1 ? "File aggiunti" : "File aggiunto"); }
    setBusy(false);
    if (input.current) input.current.value = "";
  };
  const remove = (f) => toast(`Togliere «${f.name}» dal QR? Resta nello storico delle modifiche.`, {
    action: { label: "Togli", onClick: async () => {
      try { onChanged((await api.delete(`/qr/${q.id}/files/${f.id}`)).data); toast.success("File tolto"); }
      catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    } }, cancel: { label: "Annulla", onClick: () => {} }, duration: 8000 });
  const openPhotos = async () => {
    if (photos) { setPhotos(null); return; }
    try { setPhotos((await api.get(`/qr/${q.id}/commessa-photos`)).data); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const addPhoto = async (p) => {
    setBusy(true);
    try { onChanged((await api.post(`/qr/${q.id}/files/from-photo`, { photo_id: p.id })).data); setPhotos(null); toast.success("Foto aggiunta"); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };
  return (
    <div className="card-soft p-5 flex flex-col gap-4" data-testid="qr-files">
      <div className="flex items-center justify-between gap-2">
        <span className="kicker">Foto e PDF ({files.length}/{MAX_FILES})</span>
        {busy && <Loader2 size={15} className="animate-spin text-white/70" />}
      </div>
      {files.map((f) => (
        <div key={f.id} className="flex items-center gap-3" data-testid="qr-file">
          <a href={`${API}/${f.url}`} target="_blank" rel="noopener noreferrer" className="shrink-0">
            {f.kind === "image"
              ? <img src={`${API}/${f.url}`} alt="" className="h-12 w-12 rounded-xl object-cover bg-white/10" />
              : <span className="h-12 w-12 rounded-xl bg-white/15 flex items-center justify-center">{f.kind === "model" ? <Box size={20} /> : <FileText size={20} />}</span>}
          </a>
          <a href={`${API}/${f.url}`} target="_blank" rel="noopener noreferrer" className="flex-1 min-w-0">
            <span className="block text-sm text-white truncate">{f.name}</span>
            <span className="block text-[11px] text-white/55">{f.kind === "pdf" ? `PDF · ${f.pages} ${f.pages === 1 ? "pagina" : "pagine"} · ` : f.kind === "model" ? "Modello 3D · " : "Foto · "}{sizeLabel(f.size)}</span>
          </a>
          <button type="button" onClick={() => remove(f)} aria-label={`Togli ${f.name}`} data-testid="qr-file-remove"
            className="h-9 w-9 shrink-0 rounded-full bg-white/10 flex items-center justify-center text-white/80"><X size={15} /></button>
        </div>
      ))}
      {files.length < MAX_FILES && (
        <div className={`grid gap-3 ${q.commessa ? "grid-cols-2" : "grid-cols-1"}`}>
          <input ref={input} type="file" accept="image/*,application/pdf,.pdf,.glb,model/gltf-binary" multiple hidden onChange={(e) => upload(e.target.files)} data-testid="qr-file-input" />
          <button type="button" disabled={busy} onClick={() => input.current?.click()} data-testid="qr-file-upload" className={SECONDARY}>
            <Upload size={15} /> Carica file</button>
          {q.commessa && (
            <button type="button" disabled={busy} onClick={openPhotos} data-testid="qr-file-from-commessa" className={SECONDARY}>
              <ImageIcon size={15} /> Foto commessa</button>
          )}
        </div>
      )}
      {photos && (photos.length ? (
        <div className="grid grid-cols-4 gap-2" data-testid="qr-commessa-photos">
          {photos.map((p) => (
            <button key={p.id} type="button" disabled={busy} onClick={() => addPhoto(p)} className="aspect-square rounded-xl overflow-hidden bg-white/10">
              <img src={`${API}/${p.url}`} alt="" className="h-full w-full object-cover" loading="lazy" />
            </button>
          ))}
        </div>
      ) : <div className="text-xs text-white/55">La commessa non ha foto.</div>)}
      <div className="text-[11px] text-white/55 leading-snug">
        Foto (JPG, PNG, HEIC) e PDF fino a 10 MB, modelli 3D GLB fino a 25 MB (per la realtà aumentata). Li vede chi può aprire il QR{q.visibility === "public" ? ": è pubblico, quindi chiunque lo scansioni" : ""}. Alle foto viene tolta la posizione GPS.
      </div>
    </div>
  );
}

const AR_LABEL_SIZES = { qr: [[3, "3 cm"], [5, "5 cm"], [8, "8 cm"], [10, "10 cm"]], frame: [[8, "8 cm"], [10, "10 cm"], [15, "15 cm"], [20, "20 cm"]] };
// the label on a wall (the object stands up, as the label) or on a floor/table (the object stands on it)
const MOUNTS = { wall: ["0", "0", "0"], floor: ["90", "0", "0"] };
const mountOf = (rot) => Object.keys(MOUNTS).find((k) => MOUNTS[k].every((v, i) => parseFloat(String(rot[i]).replace(",", ".")) === +v)) || null;
const num = (v, d = 0) => { const x = parseFloat(String(v).replace(",", ".")); return Number.isFinite(x) ? x : d; };

// the AR label: the QR in the middle, the 4 squares (ArUco markers 0-3) in the corners, the name above, the code below
async function printArLabel(q, cm) {
  const w = window.open("", "_blank", "width=520,height=680");
  if (!w) { toast.error("Il browser ha bloccato la finestra di stampa"); return; }
  const { default: aruco } = await import("js-aruco2");
  const dict = new aruco.AR.Dictionary("ARUCO_MIP_36h12");
  const esc = (s) => String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const svgUri = (svg) => `data:image/svg+xml;base64,${btoa(svg)}`;
  const at = [[0.01, 0.01], [0.79, 0.01], [0.79, 0.79], [0.01, 0.79]];
  const marks = at.map(([x, y], id) => `<img src="${svgUri(dict.generateSVG(id).replace("<svg ", '<svg shape-rendering="crispEdges" '))}" style="position:absolute;left:${x * cm}cm;top:${y * cm}cm;width:${0.2 * cm}cm;height:${0.2 * cm}cm">`).join("");
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(q.title)} · etichetta AR</title>
<style>@page{margin:10mm}body{margin:0;font-family:Poppins,Arial,sans-serif;color:#111}
.l{position:relative;width:${cm}cm;height:${cm}cm;border:0.2mm dashed #bbb;box-sizing:content-box}
.l img{image-rendering:pixelated}.t,.c{position:absolute;left:${0.22 * cm}cm;width:${0.56 * cm}cm;text-align:center;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.t{top:${0.06 * cm}cm;font-size:${Math.max(6, cm * 0.85)}pt;font-weight:600}.c{bottom:${0.07 * cm}cm;font-size:${Math.max(5, cm * 0.7)}pt;font-family:monospace;letter-spacing:.05em}
p{font-size:9pt;color:#555;max-width:${cm}cm}</style></head>
<body><div class="l">${marks}<img src="${q.images.svg}" style="position:absolute;left:${0.22 * cm}cm;top:${0.22 * cm}cm;width:${0.56 * cm}cm;height:${0.56 * cm}cm">
<div class="t">${esc(q.title)}</div><div class="c">${esc(q.code_label)}</div></div>
<p>Stampa al 100% (senza adattare alla pagina): il lato dell'etichetta deve misurare ${cm} cm, i 4 riquadri agli angoli servono alla realtà aumentata.</p>
<script>window.onload=function(){setTimeout(function(){window.print()},200)}</script></body></html>`);
  w.document.close();
}

/* The augmented reality of the QR: what appears on the label (a 3D model GLB or a photo among its files), which label
   (the plain QR, or the AR label with 4 squares in its corners: steadier), its printed size, and where the object
   stands on it (cm from the label's center: x right, y up along the label, z out of it) with its rotation. */
function QrAr({ q, onChanged }) {
  const ar0 = q.ar || {};
  const candidates = (q.files || []).filter((f) => f.kind === "model" || f.kind === "image");
  const [on, setOn] = useState(!!q.ar);
  const [fileId, setFileId] = useState(ar0.file_id || candidates[0]?.id || "");
  const [label, setLabel] = useState(ar0.label || "frame");
  const [labelCm, setLabelCm] = useState(ar0.label_cm || 10);
  const [off, setOff] = useState((ar0.offset_cm || [0, 0, 0]).map(String));
  const [rot, setRot] = useState((ar0.rot_deg || [0, 0, 0]).map(String));
  const [scale, setScale] = useState(String(ar0.scale || 1));
  const [width, setWidth] = useState(String(ar0.width_cm || 20));
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(false);
  const [fine, setFine] = useState(() => (ar0.offset_cm || []).some((v) => v) || !mountOf((ar0.rot_deg || [0, 0, 0]).map(String)));
  const file = candidates.find((f) => f.id === fileId);
  const mount = mountOf(rot);
  const save = async (enable = on) => {
    setBusy(true);
    try {
      const body = enable ? { on: true, file_id: fileId, label, label_cm: num(labelCm, 10), offset_cm: off.map((v) => num(v)), rot_deg: rot.map((v) => num(v)),
        scale: num(scale, 1), width_cm: num(width, 20) } : { on: false };
      onChanged((await api.patch(`/qr/${q.id}`, { ar: body })).data);
      toast.success(enable ? "Realtà aumentata salvata" : "Realtà aumentata tolta");
    } catch (e) { toast.error(e.response?.data?.detail || "Non salvato"); }
    finally { setBusy(false); }
  };
  const triple = (vals, set, names, testid) => (
    <div className="grid grid-cols-3 gap-2">
      {names.map((n, i) => (
        <Field key={n} label={<span className="text-white/60 font-normal">{n}</span>}>
          <Input inputMode="decimal" value={vals[i]} onChange={(e) => set(vals.map((v, j) => (j === i ? e.target.value : v)))} className="text-center px-2" data-testid={`${testid}-${i}`} />
        </Field>
      ))}
    </div>
  );
  return (
    <div className="card-soft p-5 flex flex-col gap-4" data-testid="qr-ar-settings">
      <span className="kicker">Realtà aumentata</span>
      {!candidates.length ? (
        <div className="text-xs text-white/65 leading-snug">Carica tra i file del QR un modello 3D (<b>GLB</b>, fino a 25 MB) o una foto: chi scansiona il QR lo vedrà appoggiato sull'etichetta, e lo seguirà se l'etichetta si sposta.</div>
      ) : (
        <>
          <Field label="Mostra un oggetto in AR">
            <Select icon={Box} value={on ? "on" : "off"} options={[["off", "No"], ["on", "Sì"]]} testid="qr-ar-on"
              onChange={(v) => { setOn(v === "on"); if (v === "off" && q.ar) save(false); }} />
          </Field>
          {on && (
            <>
              <Field label="Cosa mostrare">
                <Select icon={file?.kind === "image" ? ImageIcon : Box} value={fileId} onChange={setFileId} testid="qr-ar-file"
                  options={candidates.map((f) => [f.id, `${f.kind === "model" ? "Modello 3D" : "Foto"} · ${f.name}`])} />
              </Field>
              <Field label="Etichetta" hint={label === "frame"
                ? "QR con 4 riquadri agli angoli: più stabile, si aggancia anche da lontano. Stampala qui sotto."
                : "Il QR già stampato: meno stabile, va inquadrato da vicino."}>
                <Select icon={QrCode} value={label} options={[["frame", "Etichetta AR (consigliata)"], ["qr", "Solo il QR"]]} testid="qr-ar-label"
                  onChange={(v) => { setLabel(v); setLabelCm(v === "frame" ? 10 : 5); }} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Lato etichetta">
                  <Select icon={Maximize2} value={num(labelCm)} onChange={setLabelCm} options={AR_LABEL_SIZES[label]} testid="qr-ar-size" />
                </Field>
                {file?.kind === "image" ? (
                  <Field label="Larghezza foto (cm)">
                    <Input inputMode="decimal" value={width} onChange={(e) => setWidth(e.target.value)} data-testid="qr-ar-width" />
                  </Field>
                ) : (
                  <Field label="Scala (1 = reale)">
                    <Input inputMode="decimal" value={scale} onChange={(e) => setScale(e.target.value)} data-testid="qr-ar-scale" />
                  </Field>
                )}
              </div>
              <Field label="Etichetta appoggiata su">
                <Select icon={Layers} value={mount || "custom"} testid="qr-ar-mount"
                  options={[["wall", "Una parete"], ["floor", "Un piano (tavolo, pavimento)"], ...(mount ? [] : [["custom", "Rotazione personalizzata"]])]}
                  onChange={(v) => { if (MOUNTS[v]) setRot(MOUNTS[v]); }} />
              </Field>
              <button type="button" onClick={() => setFine((x) => !x)} onMouseDown={keepFocus} aria-expanded={fine} data-testid="qr-ar-fine"
                className="flex items-center gap-2 text-[13px] text-white/85 h-8 -mt-1">
                <SlidersHorizontal size={15} className="text-white/60" /> Regolazione fine
                <ChevronDown size={15} className={`ml-auto text-white/60 transition-transform ${fine ? "rotate-180" : ""}`} />
              </button>
              {fine && (
                <div className="flex flex-col gap-3 -mt-2">
                  <span className="text-[11px] text-white/55">Posizione dal centro dell'etichetta (cm)</span>
                  {triple(off, setOff, ["→ destra", "↑ su", "fuori"], "qr-ar-off")}
                  <span className="text-[11px] text-white/55">Rotazione (gradi)</span>
                  {triple(rot, setRot, ["X", "Y", "Z"], "qr-ar-rot")}
                </div>
              )}
              <button type="button" disabled={busy || !fileId} onMouseDown={keepFocus} onClick={() => save(true)} data-testid="qr-ar-save" className={PRIMARY}>
                {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Salva
              </button>
              {q.ar && (
                <div className={`grid gap-3 -mt-1 ${q.ar.label === "frame" ? "grid-cols-2" : "grid-cols-1"}`}>
                  <button type="button" onClick={() => setPreview(true)} data-testid="qr-ar-preview" className={SECONDARY}><Box size={15} /> Prova in AR</button>
                  {q.ar.label === "frame" && <button type="button" onClick={() => printArLabel(q, q.ar.label_cm)} data-testid="qr-ar-print" className={SECONDARY}>
                    <Printer size={15} /> Stampa {q.ar.label_cm} cm</button>}
                </div>
              )}
              <span className="text-[11px] text-white/55 leading-snug">Prova davanti all'etichetta stampata e correggi finché l'oggetto è al suo posto. Da SketchUp, Blender, Revit: esporta in .glb, misure in metri.</span>
            </>
          )}
        </>
      )}
      {preview && q.ar && (
        <React.Suspense fallback={<div className="fixed inset-0 z-[100] bg-black" />}>
          <QrArViewer ar={q.ar} onClose={() => setPreview(false)} />
        </React.Suspense>
      )}
    </div>
  );
}

function QrDetail({ id, commesse, onChanged, onDeleted }) {
  const [q, setQ] = useState(null);
  const [editing, setEditing] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [busy, setBusy] = useState(false);
  const load = async () => {
    try { const r = await api.get(`/qr/${id}`); setQ(r.data); }
    catch (e) { toast.error(e.response?.data?.detail || "QR non trovato"); }
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!q) return <div className="kicker">caricamento…</div>;
  const set = (data) => { setQ(data); onChanged(data); };
  const act = async (fn, ok) => {
    setBusy(true);
    try { const r = await fn(); set(r.data); if (ok) toast.success(ok); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };
  const confirm = (msg, label, fn) => toast(msg, { action: { label, onClick: fn }, cancel: { label: "Annulla", onClick: () => {} }, duration: 8000 });
  const newCode = () => confirm("Nuovo codice? L'etichetta già stampata smette di funzionare: andrà ristampata.", "Nuovo codice",
    () => act(() => api.post(`/qr/${q.id}/new-code`), "Nuovo codice: stampa la nuova etichetta"));
  const remove = () => confirm(`Eliminare «${q.title}»? L'etichetta stampata smette di funzionare.`, "Elimina", async () => {
    try { await api.delete(`/qr/${q.id}`); toast.success("QR eliminato"); onDeleted(q.id); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  });

  return (
    <div className="flex flex-col gap-4" data-testid="qr-detail">
      <div className="card-soft p-4 flex flex-col sm:flex-row gap-4 items-center sm:items-start">
        <div className="bg-white rounded-2xl p-2 shrink-0">
          <img src={q.images.svg} alt={`QR ${q.code_label}`} width={168} height={168} data-testid="qr-image" />
        </div>
        <div className="flex-1 min-w-0 flex flex-col gap-2 w-full">
          <div className="text-[11px] text-white/60">{q.kind_label}{q.visibility === "public" ? " · pubblico" : ""}{q.active ? "" : " · disattivato"}</div>
          <div className="font-mono text-base tracking-wider text-white" data-testid="qr-code-label">{q.code_label}</div>
          <div className="text-[11px] text-white/55 break-all">{q.url}</div>
          <div className="text-[11px] text-white/55">
            {q.scans ? `Scansionato ${q.scans} ${q.scans === 1 ? "volta" : "volte"}${q.last_scan_at ? ` · ultima ${when(q.last_scan_at)}${q.last_scan_by_name ? ` (${q.last_scan_by_name})` : ""}` : ""}` : "Non ancora scansionato"}
          </div>
          <div className="flex flex-wrap gap-2 mt-1">
            <button type="button" onClick={() => printLabel(q, 5)} data-testid="qr-print" className="h-9 px-3 rounded-full bg-white/15 text-xs font-medium inline-flex items-center gap-1.5"><Printer size={14} /> Stampa 5 cm</button>
            <button type="button" onClick={() => printLabel(q, 3)} className="h-9 px-3 rounded-full bg-white/15 text-xs font-medium inline-flex items-center gap-1.5"><Printer size={14} /> 3 cm</button>
            <a href={q.images.png} download={`QR-${q.code_label}.png`} data-testid="qr-download" className="h-9 px-3 rounded-full bg-white/15 text-xs font-medium inline-flex items-center gap-1.5"><Download size={14} /> PNG</a>
          </div>
        </div>
      </div>

      {editing ? (
        <QrEditor initial={q} commesse={commesse} onCancel={() => setEditing(false)} onSaved={(d) => { set(d); setEditing(false); }} />
      ) : (
        <div className="card-soft p-4 flex flex-col gap-3" data-testid="qr-content">
          <div className="flex items-center justify-between gap-2">
            <span className="kicker">Cosa mostra</span>
            <button type="button" onClick={() => setEditing(true)} data-testid="qr-edit" className="h-8 px-3 rounded-full bg-white/85 text-[#7A2A5C] text-xs font-semibold">Modifica</button>
          </div>
          {q.commessa && <div className="text-sm text-white/85">Commessa: <span className="font-semibold">{q.commessa.title}</span>{q.commessa.client_name ? ` · ${q.commessa.client_name}` : ""}</div>}
          <div className="text-sm text-white whitespace-pre-wrap break-words leading-relaxed" data-testid="qr-text-view">{q.text || <span className="text-white/50">Nessun testo</span>}</div>
          {q.links?.length > 0 && (
            <div className="flex flex-col gap-1">
              {q.links.map((l, i) => <a key={i} href={l.url} target="_blank" rel="noopener noreferrer" className="text-sm text-white underline underline-offset-2 break-all">{l.label}</a>)}
            </div>
          )}
          {q.place?.on && (
            <div className="text-xs text-white/80 inline-flex items-center gap-1.5 flex-wrap" data-testid="qr-place-view">
              <MapPin size={13} /> Si apre solo entro {radiusLabel(q.place.radius_m)} da {q.place.label || "questo punto"} ·
              <a href={mapLink(q.place)} target="_blank" rel="noopener noreferrer" className="underline">mappa</a>
            </div>
          )}
          <div className="text-[11px] text-white/55" data-testid="qr-visibility-view">{VISIBILITY_SHORT[q.visibility] || VISIBILITY_SHORT.org} · aggiornato {when(q.updated_at)}{q.updated_by_name ? ` da ${q.updated_by_name}` : ""}</div>
        </div>
      )}

      <QrFiles q={q} onChanged={set} />
      <QrAr key={`${q.id}-${(q.files || []).length}-${q.ar?.file_id || ""}`} q={q} onChanged={set} />

      <div className="card-soft p-4 flex flex-col gap-3">
        <button type="button" onClick={() => setShowHistory((v) => !v)} className="flex items-center justify-between text-left" data-testid="qr-history-toggle">
          <span className="kicker">Modifiche ({q.versions?.length || 0})</span>
          {showHistory ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>
        {showHistory && (q.versions?.length ? q.versions.map((v) => (
          <div key={v.id} className="text-xs text-white/75" data-testid="qr-version">
            {when(v.edited_at)}{v.edited_by_name ? ` · ${v.edited_by_name}` : ""} · {v.file_added ? `aggiunto «${v.file_added.name}»` : v.file_removed ? <>tolto <a href={`${API}/qr/${q.id}/files/${v.file_removed.id}`} target="_blank" rel="noopener noreferrer" className="underline">«{v.file_removed.name}»</a></> : (v.changed || []).map((c) => CHANGED[c] || c).join(", ")}
            {v.before?.text !== undefined && (v.changed || []).includes("text") && (
              <div className="mt-1 pl-2 border-l border-white/20 text-white/55 whitespace-pre-wrap break-words">{v.before.text || "(vuoto)"}</div>
            )}
          </div>
        )) : <div className="text-xs text-white/55">Nessuna modifica</div>)}
      </div>

      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={busy} onClick={() => act(() => api.patch(`/qr/${q.id}`, { active: !q.active }), q.active ? "QR disattivato" : "QR riattivato")}
          data-testid="qr-toggle-active" className="h-9 px-3 rounded-full bg-white/10 text-xs font-medium text-white/85">{q.active ? "Disattiva" : "Riattiva"}</button>
        <button type="button" disabled={busy} onClick={newCode} data-testid="qr-new-code" className="h-9 px-3 rounded-full bg-white/10 text-xs font-medium text-white/85 inline-flex items-center gap-1.5"><RefreshCw size={13} /> Nuovo codice</button>
        <button type="button" disabled={busy} onClick={remove} data-testid="qr-delete" className="h-9 px-3 rounded-full bg-white/10 text-xs font-medium text-white/85 inline-flex items-center gap-1.5"><Trash2 size={13} /> Elimina</button>
      </div>
    </div>
  );
}

export default function QrPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const openId = params.get("open");
  const creating = params.get("new") === "1";
  const [list, setList] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [commesse, setCommesse] = useState([]);
  const [typed, setTyped] = useState("");

  const load = async () => {
    try { const r = await api.get("/qr"); setList(r.data.qr || []); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore nel caricamento dei QR"); }
    finally { setLoaded(true); }
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (user?.business_vertical !== "artigiano") return;
    api.get("/jobs/commesse").then((r) => setCommesse(Array.isArray(r.data) ? r.data : [])).catch(() => {});
  }, [user?.business_vertical]);

  const replace = (d) => setList((xs) => [d, ...xs.filter((x) => x.id !== d.id)]);
  const goCode = (e) => {
    e.preventDefault();
    const c = typed.replace(/[\s\-./]/g, "").toUpperCase();
    if (c) navigate(`/q/${c}`);
  };

  if (creating || openId) {
    return (
      // (pb-20: room to scroll the last buttons above the bottom bar and the install banner)
      <div className="w-full settings-page pb-20" data-testid={creating ? "qr-new" : "qr-open"}>
        <button onClick={() => setParams({})} data-testid="qr-back" className="flex items-center gap-1.5 text-sm text-white/70 mb-4">
          <ArrowLeft size={16} /> QR
        </button>
        {creating ? (
          <QrEditor commesse={commesse} onCancel={() => setParams({})} onSaved={(d) => { replace(d); setParams({ open: d.id }, { replace: true }); }} />
        ) : (
          <QrDetail id={openId} commesse={commesse} onChanged={replace}
            onDeleted={(id) => { setList((xs) => xs.filter((x) => x.id !== id)); setParams({}); }} />
        )}
      </div>
    );
  }

  return (
    <div className="w-full settings-page" data-testid="qr-page">
      <div className="flex items-center gap-3 mb-5">
        <button data-testid="qr-new-btn" onClick={() => setParams({ new: "1" })} title="Nuovo QR" aria-label="Nuovo QR"
          className="lg-glass h-9 w-9 shrink-0 rounded-full flex items-center justify-center text-white active:scale-95 transition-transform">
          <Plus size={17} strokeWidth={1.7} />
        </button>
        {list.length > 0 && <span className="kicker">{list.length} QR</span>}
        <form onSubmit={goCode} className="ml-auto flex items-center gap-2">
          <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Codice stampato" data-testid="qr-type-code"
            className="h-9 w-[150px] rounded-full bg-white/10 px-3 text-xs text-white placeholder:text-white/40 outline-none font-mono" />
        </form>
      </div>
      {loaded && list.length === 0 ? (
        <div className="card-soft p-6" data-testid="qr-empty">
          <div className="font-semibold text-white">Nessun QR</div>
          <p className="mt-2 text-sm text-white/75 leading-relaxed">
            Crea un QR da attaccare in cantiere o su un attrezzo: scansionandolo, si vedono le informazioni che scrivi qui (referente, accessi,
            avvisi, link a planimetrie e schede). Le puoi cambiare quando vuoi senza ristampare l'etichetta. Scegli tu se è privato (solo chi è
            nella tua organizzazione) o pubblico (chiunque lo scansioni, per esempio un cartello per i clienti o i visitatori).
          </p>
          <button onClick={() => setParams({ new: "1" })} className="mt-5 inline-flex items-center gap-1.5 text-xs font-semibold px-3.5 py-2 rounded-full bg-white/85 text-[#7A2A5C]">
            <Plus size={14} /> Crea il primo QR
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-3" data-testid="qr-list">
          {list.map((q) => <QrTile key={q.id} q={q} onOpen={() => setParams({ open: q.id })} />)}
        </div>
      )}
    </div>
  );
}
