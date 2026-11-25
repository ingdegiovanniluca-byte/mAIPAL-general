import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { QrCode, Plus, ArrowLeft, ChevronRight, ChevronDown, Printer, Download, RefreshCw, Trash2, Link2, X, Check } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";

/* QR (administrator): the organization's labels for tools, sites and info points. The label holds only a link
   with a code: what it shows is written here and can be changed at any time without printing it again. Only who
   is in the organization opens it (see QrScanPage). */

const FIELD = "h-10 w-full min-w-0 rounded-xl bg-white/10 px-3 text-sm text-white placeholder:text-white/40 outline-none";
const KINDS = [["cantiere", "Cantiere"], ["attrezzo", "Attrezzo"], ["punto", "Punto informativo"], ["altro", "Altro"]];
const IT_MONTHS_SHORT = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const when = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getDate()} ${IT_MONTHS_SHORT[d.getMonth()]} ${d.getFullYear()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};
const CHANGED = { title: "nome", kind: "tipo", text: "testo", links: "link", commessa_id: "commessa", visibility: "chi lo vede", active: "attivo", code: "codice" };

function Chips({ options, value, onChange, testid }) {
  return (
    <div className="flex flex-wrap gap-2" data-testid={testid}>
      {options.map(([k, label]) => (
        <button key={k} type="button" onClick={() => onChange(k)} aria-pressed={value === k} data-testid={`${testid}-${k}`}
          className={`h-8 px-3 rounded-full text-xs font-medium transition-colors ${value === k ? "bg-white/55 text-[#7A2A5C]" : "bg-white/12 text-white/85 border border-white/15"}`}>
          {label}
        </button>
      ))}
    </div>
  );
}

function QrTile({ q, onOpen }) {
  return (
    <div role="button" tabIndex={0} data-testid="qr-tile" onClick={onOpen} onKeyDown={(e) => { if (e.key === "Enter") onOpen(); }}
      className={`w-full text-left rounded-[20px] px-3 h-[64px] flex items-center gap-3 backdrop-blur-xl cursor-pointer ${q.active ? "bg-white/[0.22] border border-white/30" : "bg-white/[0.07] border border-white/10"}`}>
      <span className="w-9 h-9 rounded-xl bg-white/12 flex items-center justify-center shrink-0"><QrCode size={17} /></span>
      <span className="flex-1 min-w-0">
        <span className="block text-[13px] font-semibold text-white leading-tight truncate" data-testid="qr-tile-title">{q.title}</span>
        <span className="block text-[11px] text-white/60 leading-tight mt-0.5 truncate">
          {q.kind_label}{q.commessa ? ` · ${q.commessa.title}` : ""} · {q.code_label}{q.active ? "" : " · disattivato"}
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

function QrEditor({ initial, commesse, onSaved, onCancel }) {
  const [title, setTitle] = useState(initial?.title || "");
  const [kind, setKind] = useState(initial?.kind || "cantiere");
  const [text, setText] = useState(initial?.text || "");
  const [links, setLinks] = useState(initial?.links?.length ? initial.links : []);
  const [commessaId, setCommessaId] = useState(initial?.commessa_id || "");
  const [visibility, setVisibility] = useState(initial?.visibility || "org");
  const [busy, setBusy] = useState(false);
  const setLink = (i, k, v) => setLinks((xs) => xs.map((x, j) => (j === i ? { ...x, [k]: v } : x)));

  const save = async () => {
    setBusy(true);
    const body = { title, kind, text, links: links.filter((l) => (l.url || "").trim()), commessa_id: commessaId, visibility };
    try {
      const r = initial?.id ? await api.patch(`/qr/${initial.id}`, body) : await api.post("/qr", body);
      toast.success(initial?.id ? "Contenuto aggiornato: l'etichetta stampata resta la stessa" : "QR creato");
      onSaved(r.data);
    } catch (e) { toast.error(e.response?.data?.detail || "Non salvato"); }
    finally { setBusy(false); }
  };

  return (
    <div className="card-soft p-4 flex flex-col gap-4" data-testid="qr-editor">
      <label className="flex flex-col gap-1.5">
        <span className="kicker">Nome</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} placeholder="Es. Cantiere Rossi · ingresso, Trapano Hilti 2"
          className={FIELD} data-testid="qr-title" />
      </label>
      <div className="flex flex-col gap-1.5">
        <span className="kicker">Tipo</span>
        <Chips options={KINDS} value={kind} onChange={setKind} testid="qr-kind" />
      </div>
      {commesse.length > 0 && (
        <label className="flex flex-col gap-1.5">
          <span className="kicker">Commessa (facoltativa)</span>
          <select value={commessaId} onChange={(e) => setCommessaId(e.target.value)} className={FIELD} data-testid="qr-commessa">
            <option value="">Nessuna</option>
            {commesse.map((c) => <option key={c.id} value={c.id}>{c.title}{c.client_name ? ` · ${c.client_name}` : ""}</option>)}
          </select>
        </label>
      )}
      <label className="flex flex-col gap-1.5">
        <span className="kicker">Cosa mostra</span>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} maxLength={5000} data-testid="qr-text"
          placeholder={"Es. Referente: Marco 333 1234567\nCancello: codice 4521\nAcqua chiusa al piano 2 fino a venerdì"}
          className="w-full min-w-0 rounded-xl bg-white/10 px-3 py-2.5 text-sm text-white placeholder:text-white/40 outline-none leading-relaxed" />
      </label>
      <div className="flex flex-col gap-2">
        <span className="kicker">Link (planimetrie, schede, cartella Drive…)</span>
        {links.map((l, i) => (
          <div key={i} className="flex gap-2 items-center" data-testid="qr-link-row">
            <input value={l.label || ""} onChange={(e) => setLink(i, "label", e.target.value)} placeholder="Nome" className={`${FIELD} basis-1/3`} />
            <input value={l.url || ""} onChange={(e) => setLink(i, "url", e.target.value)} placeholder="https://…" className={FIELD} data-testid="qr-link-url" />
            <button type="button" onClick={() => setLinks((xs) => xs.filter((_, j) => j !== i))} aria-label="Togli il link"
              className="h-9 w-9 shrink-0 rounded-full bg-white/10 flex items-center justify-center text-white/80"><X size={15} /></button>
          </div>
        ))}
        {links.length < 10 && (
          <button type="button" onClick={() => setLinks((xs) => [...xs, { label: "", url: "" }])} data-testid="qr-add-link"
            className="self-start inline-flex items-center gap-1.5 text-xs font-medium text-white/85 px-3 h-8 rounded-full bg-white/10">
            <Link2 size={13} /> Aggiungi un link
          </button>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <span className="kicker">Chi lo vede quando lo scansiona</span>
        <Chips options={[["org", "Tutta l'organizzazione"], ["admins", "Solo amministratori"]]} value={visibility} onChange={setVisibility} testid="qr-visibility" />
      </div>
      <div className="flex gap-2 justify-end">
        {onCancel && <button type="button" onClick={onCancel} onMouseDown={(e) => e.preventDefault()} className="h-10 px-4 rounded-full text-sm text-white/80 bg-white/10">Annulla</button>}
        {/* (onMouseDown: the field keeps the focus, so the keyboard closing doesn't bring the bottom bar under the finger
            and swallow the tap) */}
        <button type="button" onClick={save} onMouseDown={(e) => e.preventDefault()} disabled={busy} data-testid="qr-save"
          className="h-10 px-5 rounded-full text-sm font-semibold bg-white/85 text-[#7A2A5C] disabled:opacity-60 inline-flex items-center gap-1.5">
          <Check size={15} /> {initial?.id ? "Salva" : "Crea QR"}
        </button>
      </div>
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
    // (pb-20: room to scroll the last buttons above the bottom bar and the install banner)
    <div className="flex flex-col gap-4 pb-20" data-testid="qr-detail">
      <div className="card-soft p-4 flex flex-col sm:flex-row gap-4 items-center sm:items-start">
        <div className="bg-white rounded-2xl p-2 shrink-0">
          <img src={q.images.svg} alt={`QR ${q.code_label}`} width={168} height={168} data-testid="qr-image" />
        </div>
        <div className="flex-1 min-w-0 flex flex-col gap-2 w-full">
          <div className="text-[11px] text-white/60">{q.kind_label}{q.active ? "" : " · disattivato"}</div>
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
          <div className="text-[11px] text-white/55">{q.visibility === "admins" ? "Lo vedono solo gli amministratori" : "Lo vede tutta l'organizzazione"} · aggiornato {when(q.updated_at)}{q.updated_by_name ? ` da ${q.updated_by_name}` : ""}</div>
        </div>
      )}

      <div className="card-soft p-4 flex flex-col gap-3">
        <button type="button" onClick={() => setShowHistory((v) => !v)} className="flex items-center justify-between text-left" data-testid="qr-history-toggle">
          <span className="kicker">Modifiche ({q.versions?.length || 0})</span>
          {showHistory ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>
        {showHistory && (q.versions?.length ? q.versions.map((v) => (
          <div key={v.id} className="text-xs text-white/75" data-testid="qr-version">
            {when(v.edited_at)}{v.edited_by_name ? ` · ${v.edited_by_name}` : ""} · {(v.changed || []).map((c) => CHANGED[c] || c).join(", ")}
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
      <div className="w-full settings-page" data-testid={creating ? "qr-new" : "qr-open"}>
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
            Crea un QR da attaccare in cantiere o su un attrezzo: scansionandolo, chi è nella tua organizzazione vede le informazioni che scrivi qui
            (referente, accessi, avvisi, link a planimetrie e schede). Le puoi cambiare quando vuoi senza ristampare l'etichetta; per chi non è
            dell'organizzazione il QR non mostra niente.
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
