import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Building2, ExternalLink, FileText, LayoutGrid, MessageSquareText, Plus, Rows3, Search, Sparkles, Trash2, Type, X } from "lucide-react";
import GlassBottomSheet from "@/components/GlassBottomSheet";
import InfoCard from "@/components/InfoCard";
import { ClipDefs, Folder } from "@/components/TodoFolders";

/* Documenti on the phone: one folder per topic (category), two per row - the To-Do's folders,
   with their gestures, in the topic's colour; files and the information saved through Salva
   together. The newest peek out of the folder: a finger on them fans them out, slid up they stay
   up (then sideways it scrolls through all of them, down puts them back, a tap opens one); a tap
   on the folder opens the list of all of them. The page scrolls from the folders' lower part and
   the gaps. On top, always, the totals: documents, characters, categories. */

const day = (iso) => (iso ? new Date(iso).toLocaleDateString("it-IT", { day: "numeric", month: "short" }) : "");
const longDay = (iso) => (iso ? new Date(iso).toLocaleDateString("it-IT", { day: "numeric", month: "long" }) : "");
const num = (n) => new Intl.NumberFormat("it-IT").format(n || 0);
const isInfo = (d) => d.source_type === "chat";
const kind = (d) => (isInfo(d) ? "Info" : d.source_type === "image_ocr" ? "Foto" : (d.ext || "file").toUpperCase());

function useScrolled() {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const f = () => setOn(window.scrollY > 4);
    f();
    window.addEventListener("scroll", f, { passive: true });
    return () => window.removeEventListener("scroll", f);
  }, []);
  return on;
}

// the folders' size: two per row, with the gap between them
function useScale() {
  const calc = () => (typeof window === "undefined" ? 0.53 : Math.max(0.42, Math.min(0.62, (window.innerWidth - 32 - 22) / 2 / 318)));
  const [k, setK] = useState(calc);
  useEffect(() => {
    const on = () => setK(calc());
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return k;
}

function Totals({ docs, groups }) {
  const scrolled = useScrolled();
  const infos = docs.filter(isInfo).length;
  const chars = docs.reduce((t, d) => t + (d.chars || 0), 0);
  return (
    <div data-testid="docs-stats" style={{ top: "calc(3.5rem + env(safe-area-inset-top, 0px))" }}
      className={`docs-totals sticky z-30 -mx-4 px-4 pt-2 pb-3 transition-colors duration-200 ${scrolled ? "scrolled" : ""}`}>
      <div className="-mx-4 px-4 flex gap-7 overflow-x-auto no-scrollbar snap-x snap-mandatory scroll-px-4">
        <InfoCard icon={FileText} label="Documenti" value={num(docs.length)} note={infos ? `di cui ${infos} info` : ""} testid="docs-stat-total" />
        <InfoCard icon={Type} label="Caratteri" value={num(chars)} testid="docs-stat-chars" />
        <InfoCard icon={LayoutGrid} label="Categorie" value={num(groups.length)} testid="docs-stat-categories" />
      </div>
    </div>
  );
}

// a document's card: what the list on the computer shows, in the app's sheet
function DocSheet({ d, meta, icon, onClose, onDelete, orgKb }) {
  const mine = d.mine !== false;
  return (
    <GlassBottomSheet onClose={onClose} testid="doc-sheet" className="max-h-[86vh]">
      <div className="flex items-start gap-3">
        <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0" style={{ backgroundColor: meta.color + "33", color: meta.color }}>
          {isInfo(d) ? <MessageSquareText size={20} /> : icon(d.ext, d.source_type)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[19px] font-bold text-white break-words leading-tight">{d.name}</div>
          <div className="text-[12px] text-white/60 mt-1">
            {kind(d)} · {longDay(d.created_at)}{d.chars ? ` · ${num(d.chars)} caratteri` : ""}
          </div>
        </div>
      </div>
      <div className="mt-4 flex items-center gap-1.5 flex-wrap">
        <span className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-md text-white" style={{ backgroundColor: meta.color }}>{meta.label}</span>
        {d.source_type === "image_ocr" && <span className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-md text-white/70 bg-white/10 inline-flex items-center gap-1"><Sparkles size={10} /> ocr</span>}
        {isInfo(d) && <span className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-md text-white/70 bg-white/10">via chat</span>}
        {d.org_kb && <span data-testid="doc-org-badge" className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-md text-white bg-white/20 inline-flex items-center gap-1"><Building2 size={10} /> organizzazione</span>}
        {d.shared_by?.name && <span className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-md text-white bg-[#4E7FA8]">condivisa da {d.shared_by.name}</span>}
        {(d.shared_with || []).length > 0 && <span className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-md text-white/70 bg-white/10">condivisa con {d.shared_with.length}</span>}
        {(d.keywords || []).slice(0, 8).map((x, i) => <span key={i} className="text-[10px] lowercase tracking-widest px-2 py-0.5 rounded-md bg-white/10 text-white/70">#{x}</span>)}
      </div>
      {(d.preview || d.summary) && <div className="mt-4 text-[14px] text-white/80 leading-relaxed whitespace-pre-wrap">{d.preview || d.summary}</div>}
      {mine && orgKb?.can && !d.legacy && (
        <button type="button" data-testid="doc-org-kb" onClick={() => orgKb.toggle(d)} aria-pressed={!!d.org_kb}
          className="mt-4 w-full flex items-start gap-3 text-left text-[14px] text-white">
          <span className={`mt-0.5 h-5 w-5 shrink-0 rounded-full flex items-center justify-center backdrop-blur-md ${d.org_kb ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
            {d.org_kb && <Building2 size={11} strokeWidth={2.6} />}
          </span>
          <span>Nella KB dell'organizzazione<span className="block text-[12px] text-white/55">Gli utenti lo trovano e gli agenti lo usano nelle risposte; solo tu lo modifichi.</span></span>
        </button>
      )}
      <div className="mt-5 flex items-center gap-2">
        {d.drive_link && (
          <a href={d.drive_link} target="_blank" rel="noreferrer" data-testid="doc-drive-link"
            className="flex-1 h-11 rounded-full bg-white text-[#403A3C] text-[13px] font-semibold inline-flex items-center justify-center gap-1.5">
            Apri su Drive <ExternalLink size={14} />
          </a>
        )}
        {mine && (
          <button type="button" data-testid="doc-delete" onClick={onDelete}
            className={`h-11 rounded-full lg-glass text-[13px] text-white inline-flex items-center justify-center gap-1.5 ${d.drive_link ? "px-5" : "flex-1"}`}>
            <Trash2 size={14} /> Elimina
          </button>
        )}
      </div>
    </GlassBottomSheet>
  );
}

export default function DocFolders({ docs, loading, meta, q, setQ, onDelete, icon, orgKb }) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [fan, setFan] = useState(null);           // {key, hot}
  const [pinned, setPinned] = useState(null);     // the folder whose cards stay up
  const [card, setCard] = useState(null);
  const k = useScale();
  // a folder per topic that has something, the fullest first; inside, the newest first
  const groups = Object.entries(meta)
    .map(([key, m]) => ({ key, meta: m, items: docs.filter((d) => (meta[d.category] ? d.category : "altro") === key)
      .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""))
      .map((d) => ({ ...d, id: d.doc_id, title: d.name })) }))
    .filter((g) => g.items.length)
    .sort((a, b) => b.items.length - a.items.length || (b.items[0].created_at || "").localeCompare(a.items[0].created_at || ""));
  const openKey = params.get("cartella");
  const open = groups.find((g) => g.key === openKey);
  const openFolder = (key) => setParams((p) => { const n = new URLSearchParams(p); n.set("cartella", key); return n; });
  const closeFolder = () => setParams((p) => { const n = new URLSearchParams(p); n.delete("cartella"); return n; });
  const add = () => navigate("/dashboard/chat", { state: { action: "info_upload", nonce: Date.now() } });
  const sheet = card && (
    <DocSheet d={docs.find((x) => x.doc_id === card.doc_id) || card} meta={meta[card.category] || meta.altro} icon={icon} orgKb={orgKb} onClose={() => setCard(null)}
      onDelete={() => { setCard(null); onDelete(card.doc_id); }} />
  );

  if (openKey && open) {
    return (
      <div data-testid={`doc-folder-list-${open.key}`}>
        <Totals docs={docs} groups={groups} />
        <button onClick={closeFolder} data-testid="doc-folder-back" aria-label="Torna alle cartelle"
          className="lg-glass h-9 w-9 rounded-full flex items-center justify-center text-white active:scale-95 transition-transform">
          <ArrowLeft size={17} />
        </button>
        <div className="flex items-end justify-between px-1 mt-5 mb-6">
          <div className="text-[40px] font-bold leading-none tracking-tight text-white truncate">{open.meta.label}<span style={{ color: "#00B0F0" }}>.</span></div>
          <div className="text-[44px] font-light leading-none tabular-nums text-white/60 pl-3">{open.items.length}</div>
        </div>
        <div className="flex items-center justify-between px-1 mb-4">
          <div className="kicker">aggiornato il {longDay(open.items[0].created_at)}</div>
          <button onClick={add} aria-label="Aggiungi un documento" data-testid="doc-folder-list-add"
            className="lg-glass h-11 w-11 rounded-full flex items-center justify-center text-white active:scale-95 transition-transform">
            <Plus size={20} />
          </button>
        </div>
        <div className="space-y-3">
          {open.items.map((d) => (
            <div key={d.doc_id} data-testid="doc-card" className="w-full flex items-stretch rounded-2xl overflow-hidden card-soft">
              <button type="button" onClick={() => setCard(d)} className="flex-1 min-w-0 flex items-stretch text-left">
                <span className="shrink-0 w-12 flex items-center justify-center bg-white/10 text-white/75">
                  {isInfo(d) ? <MessageSquareText size={18} /> : icon(d.ext, d.source_type)}
                </span>
                <span className="flex-1 min-w-0 px-4 py-3">
                  <span className="block font-semibold text-sm text-white truncate">{d.name}</span>
                  <span className="block text-[11px] text-white/60 mt-1 truncate">{kind(d)} · {day(d.created_at)}{d.chars ? ` · ${num(d.chars)} car.` : ""}</span>
                </span>
              </button>
              {d.mine !== false && <button type="button" onClick={() => onDelete(d.doc_id)} aria-label="Elimina" className="px-3 text-white/40 active:text-red-300"><Trash2 size={15} /></button>}
            </div>
          ))}
        </div>
        {sheet}
      </div>
    );
  }

  return (
    <div className="doc-folders" data-testid="doc-folders">
      <ClipDefs />
      <Totals docs={docs} groups={groups} />
      <div className="relative">
        <Search size={15} className="absolute left-4 top-1/2 -translate-y-1/2 text-white/50" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cerca nei documenti" data-testid="docs-search"
          className="w-full h-11 rounded-full lg-glass pl-10 pr-10 text-sm text-white placeholder:text-white/50 outline-none" />
        {q && <button onClick={() => setQ("")} data-testid="docs-search-clear" aria-label="Cancella" className="absolute right-3 top-1/2 -translate-y-1/2 text-white/50"><X size={14} /></button>}
      </div>
      {!loading && groups.length === 0 && (
        <div className="mt-10 text-center text-white/60 text-sm px-6" data-testid="docs-empty">
          {q ? "Nessun documento trovato." : <>Nessun documento ancora. Con il <b>+</b> o dalla chat con <b>Salva</b> aggiungi file, foto e informazioni.</>}
          {!q && <button onClick={add} className="mt-4 mx-auto lg-glass h-11 w-11 rounded-full flex items-center justify-center text-white"><Plus size={20} /></button>}
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-[22px] gap-y-[54px] mt-[70px] pb-6 justify-items-center">
        {groups.map((g) => (
          <Folder key={g.key} folder={{ key: g.key, label: g.meta.label, tone: `linear-gradient(160deg, ${g.meta.color}40, ${g.meta.color}0d)` }}
            items={g.items} k={k} unit="doc" nameClass="doc-folder-name"
            cardMeta={(d) => `${kind(d)} · ${day(d.created_at)}`} cardDot={() => g.meta.color}
            fan={fan?.key === g.key} hot={fan?.key === g.key ? fan.hot : -1} pinned={pinned === g.key}
            onFan={(hot) => { if (pinned && pinned !== g.key) setPinned(null); setFan((cur) => (cur?.key === g.key && cur.hot === hot ? cur : { key: g.key, hot })); }}
            onUnfan={() => setFan((cur) => (cur?.key === g.key ? null : cur))}
            onPin={() => { setFan(null); setPinned(g.key); }}
            onUnpin={() => setPinned((cur) => (cur === g.key ? null : cur))}
            onOpen={() => { setPinned(null); setFan(null); openFolder(g.key); }} onOpenTodo={(d) => setCard(d)} onAdd={add} />
        ))}
      </div>
      {sheet}
    </div>
  );
}
