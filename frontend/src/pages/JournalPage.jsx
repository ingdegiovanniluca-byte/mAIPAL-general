import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { BookOpen, Trash2, Search, Star } from "lucide-react";

const toISODate = (d) => d.toISOString().slice(0, 10);

const IT_WEEKDAYS_LONG = ["domenica", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato"];
const IT_MONTHS_LONG = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
const IT_MONTHS_ABBR = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"];
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

// Parses the "YYYY-MM-DD" date components directly (no Date(iso) UTC parsing) so the
// diary heading always shows the calendar date the entry was actually saved on.
const parseIsoDate = (iso) => {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return null;
  return { y, m, d };
};
const formatDiaryDate = (iso) => {
  const p = parseIsoDate(iso);
  if (!p) return "";
  const dt = new Date(p.y, p.m - 1, p.d);
  return `${cap(IT_WEEKDAYS_LONG[dt.getDay()])} ${p.d} ${cap(IT_MONTHS_LONG[p.m - 1])} ${p.y}`;
};
const formatBadge = (iso) => {
  const p = parseIsoDate(iso);
  if (!p) return { day: "", monYear: "" };
  return { day: p.d, monYear: `${IT_MONTHS_ABBR[p.m - 1]}, ${p.y}` };
};

// Layout for the expanded view's photo grid - simple and predictable rather than a full
// masonry, but still reads as "a grid of photos" for 1/2/3 images.
const imgGridClass = (n) => (n <= 1 ? "grid-cols-1" : n === 2 ? "grid-cols-2" : "grid-cols-3");

export default function JournalPage() {
  const [entries, setEntries] = useState([]);

  // Filters, in the same order as the chat page's history search bar: periodo, ricerca,
  // preferiti. `date` mirrors that bar's single date picker exactly - set it to look at
  // one specific day, leave it empty for the default "ultimo mese" window.
  const [date, setDate] = useState("");
  const [q, setQ] = useState("");
  const [favOnly, setFavOnly] = useState(false);

  const [expandedId, setExpandedId] = useState(null);

  const dateRange = useMemo(() => {
    if (date) return { date_from: date, date_to: date };
    const today = new Date();
    const from = new Date(today);
    from.setDate(from.getDate() - 29);
    return { date_from: toISODate(from), date_to: toISODate(today) };
  }, [date]);

  const load = async () => {
    const params = {};
    if (q.trim()) params.q = q.trim();
    if (favOnly) params.favorite = true;
    if (dateRange.date_from) params.date_from = dateRange.date_from;
    if (dateRange.date_to) params.date_to = dateRange.date_to;
    const r = await api.get("/journal", { params });
    setEntries(r.data);
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [q, favOnly, dateRange.date_from, dateRange.date_to]);

  const toggleFav = async (id, currentVal) => {
    setEntries((es) => es.map((e) => (e.id === id ? { ...e, favorite: !currentVal } : e)));
    try { await api.post(`/journal/${id}/favorite`); }
    catch {
      toast.error("Errore preferito");
      setEntries((es) => es.map((e) => (e.id === id ? { ...e, favorite: currentVal } : e)));
    }
  };

  const del = (id) => {
    toast("Eliminare questa voce di diario?", {
      action: {
        label: "Elimina",
        onClick: async () => {
          const prev = entries;
          setEntries((es) => es.filter((e) => e.id !== id));
          try { await api.delete(`/journal/${id}`); toast.success("Voce eliminata"); }
          catch { toast.error("Errore"); setEntries(prev); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  const expandedEntry = entries.find((e) => e.id === expandedId) || null;

  return (
    <div className="w-full">
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-2xl bg-white/10 flex items-center justify-center"><BookOpen size={18} /></div>
        <div>
          <div className="kicker">· diario</div>
          <h2 className="text-2xl font-bold tracking-tight">Le tue giornate</h2>
        </div>
      </div>

      {/* Filtri: periodo, ricerca, preferiti - stessa barra/stile della ricerca chat */}
      <div className="flex items-center gap-1.5 md:gap-2 flex-nowrap overflow-x-auto no-scrollbar p-3 md:p-3.5 rounded-2xl bg-white/5 backdrop-blur-xl shadow-sm shrink-0">
        <input
          data-testid="journal-date"
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="shrink-0 h-8 md:h-9 w-28 md:w-32 rounded-full bg-white/10 text-white px-2 text-[10px] md:text-[11px]"
        />
        <div className="relative shrink-0 w-32 md:w-40 lg:w-48">
          <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/60" />
          <Input
            data-testid="journal-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Cerca…"
            className="pl-8 h-8 md:h-9 text-xs md:text-sm rounded-full bg-white/10 text-white placeholder:text-white/60"
          />
        </div>
        <button
          data-testid="journal-fav-filter"
          onClick={() => setFavOnly((v) => !v)}
          title="Solo preferiti"
          aria-label="Solo preferiti"
          style={{
            backgroundColor: favOnly ? "#F5B942" : "transparent",
            color: favOnly ? "#403A3C" : "#CECAD0",
            opacity: favOnly ? 1 : 0.5,
            borderColor: favOnly ? "#F5B942" : "rgba(206,202,208,0.25)",
          }}
          className="shrink-0 h-8 w-8 md:h-9 md:w-9 rounded-full border shadow-sm flex items-center justify-center transition-all duration-200 hover:opacity-100"
        >
          <Star size={15} className={favOnly ? "fill-current" : ""} />
        </button>
        {date && (
          <button onClick={() => setDate("")} className="text-[10px] text-white/40 hover:text-white/70 px-1.5 shrink-0 whitespace-nowrap">
            ✕ torna all'ultimo mese
          </button>
        )}
      </div>

      {/* Giornate: solo i riquadri, nessun grafico/umore - la scrittura avviene dalla chat */}
      <div className="mt-6 space-y-3">
        {entries.length === 0 && <div className="text-white/60 text-sm">Nessuna voce trovata con questi filtri.</div>}
        {entries.map((e) => {
          const { day, monYear } = formatBadge(e.date);
          const images = (e.images || []).slice(0, 3);
          const subtitle = (e.tags || []).length > 0 ? `Argomenti: ${e.tags.join(", ")}` : "";
          return (
            <div key={e.id} className="flex items-stretch gap-3" data-testid="journal-entry">
              <div className="flex flex-col items-center justify-center gap-1.5 shrink-0 w-20 rounded-2xl bg-white/10 text-center py-2.5 px-1">
                <div className="text-2xl font-bold text-white leading-none">{day}</div>
                <div className="text-[10px] uppercase tracking-widest text-white/60">{monYear}</div>
                <button
                  data-testid="journal-fav"
                  onClick={() => toggleFav(e.id, !!e.favorite)}
                  title={e.favorite ? "Rimuovi dai preferiti" : "Segna come giornata memorabile"}
                  className={`liquid-glass-btn p-1.5 rounded-full transition-colors duration-150 mt-0.5 ${e.favorite ? "text-amber-400" : "text-white/50"}`}
                >
                  <Star size={15} className={e.favorite ? "fill-current" : ""} />
                </button>
              </div>
              <button
                onClick={() => setExpandedId(e.id)}
                className="flex-1 min-w-0 text-left p-4 rounded-2xl bg-white/5 backdrop-blur-xl shadow-sm hover:bg-white/10 transition-colors flex items-center gap-4"
              >
                <div className="min-w-0 flex-1">
                  <div className="font-semibold text-base text-white truncate">{e.title || "Diario"}</div>
                  {subtitle && <div className="text-xs text-white/50 truncate mt-0.5">{subtitle}</div>}
                  <div className="text-sm text-white/75 mt-1.5 line-clamp-3">{e.cleaned_text}</div>
                </div>
                {images.length > 0 && (
                  <div className="flex gap-1 shrink-0">
                    {images.map((src, i) => (
                      <img key={i} src={src} alt="" className="w-14 h-14 md:w-16 md:h-16 rounded-lg object-cover" />
                    ))}
                  </div>
                )}
              </button>
            </div>
          );
        })}
      </div>

      {/* Vista estesa di una giornata: foto in griglia + testo completo */}
      {expandedEntry && (
        <Dialog open={true} onOpenChange={() => setExpandedId(null)}>
          <DialogContent className="max-w-2xl bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="journal-expanded">
            <DialogHeader>
              <div className="flex items-center justify-between gap-2 pr-6">
                <DialogTitle>{expandedEntry.title || "Diario"}</DialogTitle>
                <button
                  data-testid="journal-delete"
                  onClick={() => { del(expandedEntry.id); setExpandedId(null); }}
                  className="liquid-glass-btn p-2 rounded-full text-white/60 hover:text-red-300 shrink-0"
                  title="Elimina voce"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </DialogHeader>

            {(expandedEntry.images || []).length > 0 && (
              <div className={`grid gap-1.5 rounded-2xl overflow-hidden ${imgGridClass(expandedEntry.images.length)}`}>
                {expandedEntry.images.map((src, i) => (
                  <img key={i} src={src} alt="" className="w-full h-48 md:h-56 object-cover" />
                ))}
              </div>
            )}

            <div className="font-serif-italic text-sm text-white/60 mt-1">{formatDiaryDate(expandedEntry.date)}</div>
            {(expandedEntry.tags || []).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {expandedEntry.tags.map((t, i) => (
                  <span key={i} className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-full bg-white/10 text-white/60">{t}</span>
                ))}
              </div>
            )}
            <div className="mt-3 pt-3 border-t border-white/15 prose-answer whitespace-pre-wrap text-[15px] text-white">
              {expandedEntry.cleaned_text}
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
