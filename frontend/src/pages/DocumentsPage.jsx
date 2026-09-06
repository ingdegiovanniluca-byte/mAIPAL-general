import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import {
  FolderOpen, FileText, FileSpreadsheet, FileImage, FileType, File as FileIcon,
  Search, X, Trash2, ExternalLink, Sparkles, MessageSquareText
} from "lucide-react";

const CATEGORY_META = {
  lavoro:               { label: "Lavoro",             color: "#0EA5E9" },
  personale:            { label: "Personale",          color: "#8B5CF6" },
  finanza:              { label: "Finanza",            color: "#10B981" },
  salute:               { label: "Salute",             color: "#EF4444" },
  viaggi:               { label: "Viaggi",             color: "#F59E0B" },
  casa:                 { label: "Casa",               color: "#F97316" },
  ricevute:             { label: "Ricevute",           color: "#EAB308" },
  "documenti_identità": { label: "Documenti identità", color: "#6366F1" },
  istruzione:           { label: "Istruzione",         color: "#14B8A6" },
  note:                 { label: "Note",               color: "#64748B" },
  altro:                { label: "Altro",              color: "#94A3B8" },
};

function extIcon(ext, source_type) {
  const e = (ext || "").toLowerCase();
  if (source_type === "image_ocr" || ["jpg","jpeg","png","webp","heic","heif"].includes(e)) return <FileImage size={20} />;
  if (["pdf"].includes(e))                                                                   return <FileType  size={20} />;
  if (["xlsx","csv"].includes(e))                                                            return <FileSpreadsheet size={20} />;
  if (["docx","txt","md","markdown","html","htm","xml","yaml","yml","json","log"].includes(e)) return <FileText size={20} />;
  if (source_type === "chat")                                                                return <MessageSquareText size={20} />;
  return <FileIcon size={20} />;
}

function fmtSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024*1024) return `${(bytes/1024).toFixed(1)} KB`;
  return `${(bytes/1024/1024).toFixed(1)} MB`;
}

export default function DocumentsPage() {
  const [docs, setDocs] = useState([]);
  const [categories, setCategories] = useState([]);
  const [category, setCategory] = useState("all");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const params = {};
      if (q.trim()) params.q = q.trim();
      if (category && category !== "all") params.category = category;
      const [d, c] = await Promise.all([
        api.get("/kb/documents", { params }),
        api.get("/kb/documents/categories"),
      ]);
      setDocs(d.data);
      setCategories(c.data);
    } catch { toast.error("Errore nel caricamento documenti"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [q, category]);

  const del = async (id) => {
    if (!confirm("Eliminare questo documento dalla knowledge base?")) return;
    const prev = docs;
    setDocs((ds) => ds.filter((d) => d.doc_id !== id));
    try { await api.delete(`/kb/documents/${id}`); toast.success("Documento rimosso"); }
    catch { toast.error("Errore"); setDocs(prev); }
  };

  const total = docs.length;
  const totalChars = useMemo(() => docs.reduce((s, d) => s + (d.chars || 0), 0), [docs]);

  return (
    <div className="max-w-6xl">
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-2xl bg-neutral-100 flex items-center justify-center"><FolderOpen size={18} /></div>
        <div>
          <div className="kicker">· documenti</div>
          <h2 className="text-2xl font-bold tracking-tight">La tua knowledge base</h2>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6" data-testid="docs-stats">
        <StatCard label="Totale" value={total} />
        <StatCard label="Categorie" value={categories.length} />
        <StatCard label="Caratteri indicizzati" value={new Intl.NumberFormat("it-IT").format(totalChars)} />
        <StatCard label="Google Drive" value="non collegato" muted />
      </div>

      {/* Toolbar */}
      <div className="p-4 rounded-2xl bg-white/60 border border-white/50 backdrop-blur-xl shadow-sm">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative flex-1 min-w-[220px]">
            <Search size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-neutral-400" />
            <Input
              data-testid="docs-search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Cerca per nome, parola chiave, anteprima…"
              className="pl-10 pr-10 h-10 rounded-full bg-white/80"
            />
            {q && (
              <button data-testid="docs-search-clear" onClick={() => setQ("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-neutral-700"><X size={14} /></button>
            )}
          </div>
          <div className="flex items-center gap-1 flex-wrap">
            <CatButton active={category === "all"} onClick={() => setCategory("all")} label="tutte" count={total} testid="cat-all" />
            {Object.entries(CATEGORY_META).map(([k, meta]) => {
              const found = categories.find((c) => c.category === k);
              if (!found) return null;
              return (
                <CatButton key={k} active={category === k} onClick={() => setCategory(k)} label={meta.label.toLowerCase()} color={meta.color} count={found.count} testid={`cat-${k}`} />
              );
            })}
          </div>
        </div>
      </div>

      {/* Grid */}
      <div className="mt-6">
        {loading && <div className="text-neutral-500 text-sm">Carico…</div>}
        {!loading && docs.length === 0 && (
          <div className="p-8 rounded-2xl bg-white/60 border border-white/50 backdrop-blur-xl shadow-sm text-neutral-500 text-sm" data-testid="docs-empty">
            Nessun documento ancora. Vai in <b>Chat → Caricamento informazioni</b> per aggiungere file (pdf, docx, xlsx, immagini con OCR, note…).
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {docs.map((d) => {
            const meta = CATEGORY_META[d.category] || CATEGORY_META.altro;
            return (
              <div key={d.doc_id} className="group p-5 rounded-2xl bg-white/70 border border-white/50 backdrop-blur-xl shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md" data-testid="doc-card">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-start gap-3 min-w-0 flex-1">
                    <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0" style={{ backgroundColor: meta.color + "22", color: meta.color }}>
                      {extIcon(d.ext, d.source_type)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="font-semibold text-neutral-800 truncate" title={d.name}>{d.name}</div>
                      <div className="kicker-p mt-0.5">
                        {new Date(d.created_at).toLocaleDateString("it-IT", { day: "2-digit", month: "short", year: "numeric" })}
                        {d.chars ? ` · ${new Intl.NumberFormat("it-IT").format(d.chars)} car.` : ""}
                        {d.size_bytes ? ` · ${fmtSize(d.size_bytes)}` : ""}
                      </div>
                    </div>
                  </div>
                  <button data-testid="doc-delete" onClick={() => del(d.doc_id)} title="Elimina" className="p-1.5 rounded-full text-neutral-400 hover:bg-red-50 hover:text-red-600 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Trash2 size={14} />
                  </button>
                </div>

                <div className="mt-3 flex items-center gap-1.5 flex-wrap">
                  <span className="text-[10px] font-mono-tight uppercase tracking-widest px-2 py-0.5 rounded-md text-white" style={{ backgroundColor: meta.color }}>
                    {meta.label}
                  </span>
                  {d.source_type === "image_ocr" && (
                    <span className="text-[10px] font-mono-tight uppercase tracking-widest px-2 py-0.5 rounded-md border border-neutral-300 text-neutral-500 bg-white inline-flex items-center gap-1"><Sparkles size={10} /> ocr</span>
                  )}
                  {d.source_type === "chat" && (
                    <span className="text-[10px] font-mono-tight uppercase tracking-widest px-2 py-0.5 rounded-md border border-neutral-300 text-neutral-500 bg-white">via chat</span>
                  )}
                  {(d.keywords || []).slice(0, 6).map((k, i) => (
                    <span key={i} className="text-[10px] font-mono-tight lowercase tracking-widest px-2 py-0.5 rounded-md bg-neutral-100 text-neutral-600 border border-neutral-200">
                      #{k}
                    </span>
                  ))}
                </div>

                {d.preview && (
                  <div className="mt-3 text-sm text-neutral-600 line-clamp-3 leading-relaxed">
                    {d.preview}
                  </div>
                )}

                <div className="mt-3 pt-3 border-t border-neutral-100 flex items-center justify-between">
                  <span className="kicker-p text-neutral-400">{d.chunks_count || 1} chunk indicizzati</span>
                  {d.drive_link ? (
                    <a href={d.drive_link} target="_blank" rel="noreferrer" data-testid="doc-drive-link" className="kicker-p text-blue-600 inline-flex items-center gap-1 hover:underline">
                      apri su drive <ExternalLink size={11} />
                    </a>
                  ) : (
                    <span className="kicker-p text-neutral-300 inline-flex items-center gap-1" title="Sarà attivo quando collegherai Google Drive dalle Impostazioni">
                      drive · presto <ExternalLink size={11} />
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, muted }) {
  return (
    <div className={`p-4 rounded-2xl bg-white/60 border border-white/50 backdrop-blur-xl shadow-sm ${muted ? "opacity-70" : ""}`}>
      <div className="kicker-p">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${muted ? "text-neutral-500" : ""}`}>{value}</div>
    </div>
  );
}

function CatButton({ active, onClick, label, color, count, testid }) {
  return (
    <button
      data-testid={testid}
      onClick={onClick}
      style={active ? { backgroundColor: color || "#6EB7EC", color: "#fff", border: "none" } : {}}
      className={`px-3 py-1.5 rounded-full text-[10px] font-mono-tight uppercase tracking-widest inline-flex items-center gap-1 ${active ? "" : "bg-white/70 border border-neutral-200 text-neutral-500 hover:border-neutral-400"}`}
    >
      {label} <span className={`ml-0.5 ${active ? "opacity-80" : "opacity-60"}`}>{count}</span>
    </button>
  );
}
