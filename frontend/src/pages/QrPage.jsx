import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { QrCode, Plus, ArrowLeft, ChevronRight, ChevronDown, Printer, Download, RefreshCw, Trash2, Link2, X, Check, FileText, Upload, Image as ImageIcon, Loader2, MapPin, Box, Crosshair, Search, Tag, Type, Briefcase, Eye, Palette, Maximize2, Pencil, History, Wrench } from "lucide-react";
import { api, API } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { phonePosition } from "@/pages/QrScanPage";
import { Field, Input, Select, PRIMARY, SECONDARY, GroupTitle } from "@/components/FormFields";
import IosSwitch from "@/components/IosSwitch";
import GlassBottomSheet from "@/components/GlassBottomSheet";
import { StatTiles, StatTile } from "@/components/StatTiles";

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
const CHANGED = { tool_item_id: "attrezzo", ar: "realtà aumentata", place: "luogo", files: "file", title: "nome", kind: "tipo", text: "testo", links: "link", commessa_id: "commessa", visibility: "chi lo vede", active: "attivo", code: "codice" };

// A button of the editor tapped while typing: the field keeps the focus, so the keyboard closing doesn't bring the
// bottom bar under the finger and swallow the tap (see "Crea QR").
const keepFocus = (e) => e.preventDefault();

function QrTile({ q, onOpen }) {
  return (
    <div role="button" tabIndex={0} data-testid="qr-tile" onClick={onOpen} onKeyDown={(e) => { if (e.key === "Enter") onOpen(); }}
      className={`w-full text-left rounded-[20px] px-3 h-[64px] flex items-center gap-3 backdrop-blur-xl cursor-pointer ${q.active ? "bg-white/[0.22] border border-white/30" : "bg-white/[0.07] border border-white/10"}`}>
      <span className="w-9 h-9 rounded-xl bg-white/[0.12] flex items-center justify-center shrink-0"><QrCode size={17} /></span>
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
  const [toolId, setToolId] = useState(initial?.tool?.item_id || "");
  const [tools, setTools] = useState(null);     // the Attrezzatura list: {list, items} (only for a tool's QR)
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (kind !== "attrezzo" || tools) return;
    api.get("/qr/tools").then((r) => setTools(r.data)).catch(() => setTools({ list: null, items: [] }));
  }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps
  const pickTool = (id) => {
    setToolId(id);
    const t = (tools?.items || []).find((x) => x.id === id);
    if (t && !title.trim()) setTitle(t.name);
  };
  const setLink = (i, k, v) => setLinks((xs) => xs.map((x, j) => (j === i ? { ...x, [k]: v } : x)));

  const save = async () => {
    if (place?.on && place.lat == null) { toast.error("Scegli il luogo in cui si apre il QR, o metti «Ovunque»"); return; }
    setBusy(true);
    const body = { title, kind, text, links: links.filter((l) => (l.url || "").trim()), commessa_id: commessaId, visibility,
      place: place?.on ? place : { on: false }, style, ...(kind === "attrezzo" && tools?.list ? { tool_item_id: toolId } : {}) };
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
      {kind === "attrezzo" && tools?.list && (
        <Field label="Attrezzo" testid="qr-tool-box"
          hint={toolId ? `Dalla lista ${tools.list.name}: chi scansiona il QR lo prende o lo restituisce.` : `Lo aggiungo alla lista ${tools.list.name} con il nome del QR.`}>
          <Select icon={Wrench} value={toolId} onChange={pickTool} testid="qr-tool"
            options={[["", "Nuovo (con il nome del QR)"], ...tools.items.map((t) => [t.id, t.name])]} />
        </Field>
      )}
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
        hint={`${style === "maipal" ? "Forma e colori del logo mAIPAL, con il logo al centro." : "Bianco e nero: si legge anche piccolo o sbiadito."}${initial?.id && initial.style !== style ? " Cambiando aspetto conviene ristampare l'etichetta." : ""}`}>
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
      {busy && <div className="flex items-center gap-2 text-[12px] text-white/70"><Loader2 size={15} className="animate-spin" /> Carico…</div>}
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
          <input ref={input} type="file" accept="image/*,application/pdf,.pdf" multiple hidden onChange={(e) => upload(e.target.files)} data-testid="qr-file-input" />
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
        Foto (JPG, PNG, HEIC) e PDF fino a 10 MB. Li vede chi può aprire il QR{q.visibility === "public" ? ": è pubblico, quindi chiunque lo scansioni" : ""}. Alle foto viene tolta la posizione GPS.
      </div>
    </div>
  );
}

// a value of the QR shown (not edited): its label above, the value under it, rows split by thin lines
function InfoRow({ label, children, testid }) {
  return (
    <div className="py-3 border-t border-white/10 first:border-t-0 first:pt-0" data-testid={testid}>
      <div className="text-[12px] text-white/60">{label}</div>
      <div className="text-sm text-white mt-0.5 break-words">{children}</div>
    </div>
  );
}

// a round icon button of the detail (print, download, link; edit, new code, delete)
const ROUND = "h-11 w-11 shrink-0 rounded-full flex items-center justify-center transition-colors disabled:opacity-50";

/* Print: the side of the label is chosen in a small sheet, then the browser's print. */
function PrintSheet({ q, onClose }) {
  const [cm, setCm] = useState(5);
  return (
    <GlassBottomSheet onClose={onClose} testid="qr-print-sheet" className="max-h-[80vh] md:left-1/2 md:right-auto md:w-[420px] md:-translate-x-1/2 md:bottom-8">
      <div className="text-lg font-semibold text-white mb-4">Stampa l'etichetta</div>
      <div className="flex flex-col gap-4">
        <Field label="Lato del QR">
          <Select icon={Maximize2} value={cm} onChange={setCm} testid="qr-print-size" options={[[3, "3 cm"], [5, "5 cm"], [8, "8 cm"]]} />
        </Field>
        <button type="button" onClick={() => { printLabel(q, cm); onClose(); }} data-testid="qr-print-go" className={`${PRIMARY} w-full`}>
          <Printer size={15} /> Stampa
        </button>
      </div>
    </GlassBottomSheet>
  );
}

function QrDetail({ id, commesse, onChanged, onDeleted, onBack }) {
  const [q, setQ] = useState(null);
  const [editing, setEditing] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [busy, setBusy] = useState(false);
  const [printing, setPrinting] = useState(false);
  const load = async () => {
    try { const r = await api.get(`/qr/${id}`); setQ(r.data); }
    catch (e) { toast.error(e.response?.data?.detail || "QR non trovato"); }
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const back = (
    <button onClick={onBack} data-testid="qr-back" className="flex items-center gap-1.5 text-sm text-white/70 h-11">
      <ArrowLeft size={16} /> QR
    </button>
  );
  if (!q) return <>{back}<div className="kicker">caricamento…</div></>;
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
  const setActive = (on) => act(() => api.patch(`/qr/${q.id}`, { active: on }), on ? "QR riattivato" : "QR disattivato: chi lo scansiona non vede niente");
  const copyLink = () => { navigator.clipboard?.writeText(q.url); toast.success("Link copiato"); };
  const versions = q.versions || [];
  const t = q.tool;

  return (
    <div className="flex flex-col gap-3" data-testid="qr-detail">
      {/* on top: back, and what changes the QR - on/off, edit, new code, delete */}
      <div className="flex items-center gap-2" data-testid="qr-toolbar">
        {back}
        <div className="ml-auto flex items-center gap-2">
          <IosSwitch checked={!!q.active} onChange={setActive} disabled={busy} label={q.active ? "Attivo: tocca per disattivarlo" : "Disattivato: tocca per riattivarlo"} testid="qr-toggle-active" />
          <button type="button" onClick={() => setEditing((v) => !v)} aria-pressed={editing} data-testid="qr-edit" title="Modifica" aria-label="Modifica"
            className={`${ROUND} ${editing ? "bg-white/85 text-[#7A2A5C]" : "bg-white/15 text-white"}`}><Pencil size={17} /></button>
          <button type="button" onClick={newCode} disabled={busy} data-testid="qr-new-code" title="Nuovo codice" aria-label="Nuovo codice"
            className={`${ROUND} bg-white/15 text-white`}><RefreshCw size={17} /></button>
          <button type="button" onClick={remove} disabled={busy} data-testid="qr-delete" title="Elimina" aria-label="Elimina"
            className={`${ROUND} bg-white/90 text-[#C0262D]`}><Trash2 size={17} /></button>
        </div>
      </div>

      {/* the QR, with what identifies it and the three ways to take it out */}
      <div className="card-soft p-5 flex flex-col gap-4">
        <div className="flex flex-col items-center gap-3">
          <div className={`bg-white rounded-2xl p-2.5 shadow-sm ${q.active ? "" : "opacity-50"}`}>
            <img src={q.images.svg} alt={`QR ${q.code_label}`} width={196} height={196} data-testid="qr-image" />
          </div>
          <div className="text-center min-w-0 w-full">
            <div className="text-lg font-semibold text-white leading-tight break-words" data-testid="qr-title-view">{q.title}</div>
            <div className="font-mono text-[15px] tracking-wider text-white/85 mt-1" data-testid="qr-code-label">{q.code_label}</div>
            <div className="flex flex-wrap justify-center gap-1.5 mt-2">
              <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/10 border border-white/15 text-white/80">{q.kind_label}</span>
              <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/10 border border-white/15 text-white/80">{q.visibility === "public" ? "Pubblico" : q.visibility === "admins" ? "Solo amministratori" : "Organizzazione"}</span>
              {q.place?.on && <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/10 border border-white/15 text-white/80">Solo sul posto</span>}
              {!q.active && <span className="text-[11px] px-2.5 py-1 rounded-full bg-amber-300/15 border border-amber-300/30 text-amber-100" data-testid="qr-inactive">Disattivato</span>}
            </div>
          </div>
        </div>
        <div className="flex justify-center gap-4">
          <button type="button" onClick={() => setPrinting(true)} data-testid="qr-print" title="Stampa l'etichetta" aria-label="Stampa l'etichetta"
            className={`${ROUND} bg-white/90 text-[#7A2A5C]`}><Printer size={18} /></button>
          <a href={q.images.png} download={`QR-${q.code_label}.png`} data-testid="qr-download" title="Scarica il PNG" aria-label="Scarica il PNG"
            className={`${ROUND} bg-white/15 text-white`}><Download size={18} /></a>
          <button type="button" onClick={copyLink} data-testid="qr-copy-link" title={`Copia il link: ${q.url}`} aria-label="Copia il link"
            className={`${ROUND} bg-white/15 text-white`}><Link2 size={18} /></button>
        </div>
        <div className="border-t border-white/10 pt-4">
          <StatTiles testid="qr-stats">
            <StatTile label="Scansioni" value={q.scans || 0} testid="qr-stat-scans" />
            <StatTile label="Foto e PDF" value={(q.files || []).length} testid="qr-stat-files" />
            <StatTile label="Modifiche" value={versions.length} testid="qr-stat-versions" />
          </StatTiles>
          <div className="text-[11px] text-white/55 mt-3" data-testid="qr-last-scan">
            {q.last_scan_at ? `Ultima scansione ${when(q.last_scan_at)}${q.last_scan_by_name ? ` · ${q.last_scan_by_name}` : ""}` : "Non ancora scansionato"}
          </div>
        </div>
      </div>

      <div className="pt-2"><GroupTitle>Contenuto</GroupTitle></div>
      {editing ? (
        <QrEditor initial={q} commesse={commesse} onCancel={() => setEditing(false)} onSaved={(d) => { set(d); setEditing(false); }} />
      ) : (
        <div className="card-soft p-5" data-testid="qr-content">
          {t && (
            <InfoRow label="Attrezzo" testid="qr-tool-view">
              {t.name || q.title}
              <div className="text-[12px] text-white/70 mt-0.5">{t.holder ? `Ce l'ha ${t.holder.name} dal ${when(t.holder.since)}` : "Disponibile"}</div>
            </InfoRow>
          )}
          <InfoRow label="Cosa mostra" testid="qr-text-view">
            {q.text ? <span className="whitespace-pre-wrap leading-relaxed">{q.text}</span> : <span className="text-white/50">Nessun testo</span>}
          </InfoRow>
          {q.links?.length > 0 && (
            <InfoRow label="Link">
              <div className="flex flex-col gap-1">
                {q.links.map((l, i) => <a key={i} href={l.url} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 break-all">{l.label}</a>)}
              </div>
            </InfoRow>
          )}
          {q.commessa && <InfoRow label="Commessa">{q.commessa.title}{q.commessa.client_name ? ` · ${q.commessa.client_name}` : ""}</InfoRow>}
          <InfoRow label="Chi lo vede" testid="qr-visibility-view">{VISIBILITY_SHORT[q.visibility] || VISIBILITY_SHORT.org}</InfoRow>
          <InfoRow label="Dove si apre" testid="qr-place-view">
            {q.place?.on ? <>Solo entro {radiusLabel(q.place.radius_m)} da {q.place.label || "questo punto"} · <a href={mapLink(q.place)} target="_blank" rel="noopener noreferrer" className="underline">mappa</a></> : "Ovunque"}
          </InfoRow>
          <InfoRow label="Aspetto">{q.style === "maipal" ? "mAIPAL" : "Classico"}</InfoRow>
          <div className="text-[11px] text-white/55 pt-3 border-t border-white/10">Aggiornato {when(q.updated_at)}{q.updated_by_name ? ` da ${q.updated_by_name}` : ""}</div>
        </div>
      )}

      <div className="pt-2"><GroupTitle>Foto e PDF ({(q.files || []).length}/{MAX_FILES})</GroupTitle></div>
      <QrFiles q={q} onChanged={set} />

      <div className="pt-2"><GroupTitle>Storico</GroupTitle></div>
      <div className="card-soft p-5 flex flex-col gap-4">
        {t && (q.tool_moves || []).length > 0 && (
          <div data-testid="qr-tool-moves">
            <div className="text-sm font-medium text-white mb-1">Chi l'ha preso</div>
            {q.tool_moves.map((m) => (
              <div key={m.id} className="py-2 border-t border-white/10 first:border-t-0 text-[13px] text-white/85">
                <span className="text-white/55">{when(m.at)} · </span>
                {m.name} {m.action === "take" ? (m.from_name ? `l'ha preso da ${m.from_name}` : "l'ha preso") : "l'ha restituito"}
              </div>
            ))}
          </div>
        )}
        <button type="button" onClick={() => setShowHistory((v) => !v)} aria-expanded={showHistory} className="w-full flex items-center gap-3 text-left" data-testid="qr-history-toggle">
          <History size={17} className="shrink-0 text-white/60" />
          <span className="flex-1 min-w-0">
            <span className="block text-sm font-medium text-white">Modifiche ({versions.length})</span>
            <span className="block text-[12px] text-white/55 mt-0.5">Chi ha cambiato cosa, con il testo di prima.</span>
          </span>
          <ChevronDown size={17} className={`shrink-0 text-white/60 transition-transform ${showHistory ? "rotate-180" : ""}`} />
        </button>
        {showHistory && (versions.length ? (
          <div className="-mt-1">
            {versions.map((v) => (
              <div key={v.id} className="py-2.5 border-t border-white/10 first:border-t-0 text-[13px] text-white/85" data-testid="qr-version">
                <div className="text-[11px] text-white/55">{when(v.edited_at)}{v.edited_by_name ? ` · ${v.edited_by_name}` : ""}</div>
                {v.file_added ? `Aggiunto «${v.file_added.name}»` : v.file_removed ? <>Tolto <a href={`${API}/qr/${q.id}/files/${v.file_removed.id}`} target="_blank" rel="noopener noreferrer" className="underline">«{v.file_removed.name}»</a></> : capFirst((v.changed || []).map((c) => (c === "active" && v.before?.active !== undefined ? (v.before.active ? "disattivato" : "riattivato") : CHANGED[c] || c)).join(", "))}
                {v.before?.text !== undefined && (v.changed || []).includes("text") && (
                  <div className="mt-1 pl-2 border-l border-white/20 text-white/55 whitespace-pre-wrap break-words">{v.before.text || "(vuoto)"}</div>
                )}
              </div>
            ))}
          </div>
        ) : <div className="text-[12px] text-white/55 -mt-1">Nessuna modifica</div>)}
      </div>
      {printing && <PrintSheet q={q} onClose={() => setPrinting(false)} />}
    </div>
  );
}

const capFirst = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);

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
        {creating && (
          <button onClick={() => setParams({})} data-testid="qr-back" className="flex items-center gap-1.5 text-sm text-white/70 mb-4">
            <ArrowLeft size={16} /> QR
          </button>
        )}
        {creating ? (
          <QrEditor commesse={commesse} onCancel={() => setParams({})} onSaved={(d) => { replace(d); setParams({ open: d.id }, { replace: true }); }} />
        ) : (
          <QrDetail id={openId} commesse={commesse} onChanged={replace} onBack={() => setParams({})}
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
        {/* the code printed under the QR on the label (when it can't be scanned): opens that QR */}
        <form onSubmit={goCode} className="ml-auto relative" role="search">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/50 pointer-events-none" />
          <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Cerca per codice" data-testid="qr-type-code"
            aria-label="Cerca un QR per codice (es. K7P3-XQ9M-2TRA)" enterKeyHint="search" autoCapitalize="characters"
            className="h-9 w-[170px] rounded-full bg-white/10 border border-white/15 pl-8 pr-3 text-xs text-white placeholder:text-white/45 outline-none focus:border-white/45 uppercase placeholder:normal-case" />
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
