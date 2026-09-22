import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { BookOpen, Trash2, Star, Briefcase, PartyPopper, Palmtree, Home, HeartPulse, Users, Plane, X, Paperclip, Calendar } from "lucide-react";

// Diario theme colors (from the design spec). The card backgrounds now use the app's
// standard translucent "card-soft" glass style (same as Chat/News) instead of a custom
// color, so the preview text - originally tuned for a light #B28F8E card - is light too,
// to stay legible on the dark glass background.
const DIARY_TITLE_COLOR = "#D9D9D9";
const DIARY_TEXT_COLOR = "rgba(255,255,255,0.75)";
const DIARY_DAY_COLOR = "#AC6C41";
const DIARY_FAV_COLOR = "#FFC000";

// I 7 temi riconosciuti nelle giornate, mostrati come icone bianche sotto l'anteprima del
// testo - dedotti dai tag che l'AI assegna alla voce (nessuna scelta manuale per ora).
const TOPIC_ICONS = [
  { key: "lavoro", icon: Briefcase, match: ["lavoro", "lavorativo", "ufficio", "riunione", "meeting", "progetto", "collega", "clienti"] },
  { key: "tempo_libero", icon: PartyPopper, match: ["tempo libero", "svago", "hobby", "divertimento", "amici", "festa"] },
  { key: "vacanza", icon: Palmtree, match: ["vacanza", "vacanze", "ferie"] },
  { key: "vita_privata", icon: Home, match: ["vita privata", "privato", "personale", "casa"] },
  { key: "salute", icon: HeartPulse, match: ["salute", "medico", "malattia", "palestra", "sport", "benessere"] },
  { key: "famiglia", icon: Users, match: ["famiglia", "figli", "genitori", "moglie", "marito", "matrimonio"] },
  { key: "viaggi", icon: Plane, match: ["viaggio", "viaggi", "trasferta", "volo"] },
];
const topicsForEntry = (entry) => {
  const tags = (entry.tags || []).map((t) => (t || "").toLowerCase());
  if (tags.length === 0) return [];
  return TOPIC_ICONS.filter((t) => tags.some((tag) => t.match.some((kw) => tag.includes(kw))));
};

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

const pad2 = (n) => String(n).padStart(2, "0");

export default function JournalPage() {
  const [entries, setEntries] = useState([]);

  // Navigazione a calendario: mese mostrato (default il mese corrente) + giorno
  // selezionato dentro quel mese (null = mostra tutto il mese, il default).
  const today = new Date();
  const [viewYear, setViewYear] = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth() + 1); // 1-indexato
  const [selectedDay, setSelectedDay] = useState(null);
  const [monthPickerOpen, setMonthPickerOpen] = useState(false);

  const [expandedId, setExpandedId] = useState(null);

  const daysInMonth = useMemo(() => new Date(viewYear, viewMonth, 0).getDate(), [viewYear, viewMonth]);
  const monthRange = useMemo(() => ({
    date_from: `${viewYear}-${pad2(viewMonth)}-01`,
    date_to: `${viewYear}-${pad2(viewMonth)}-${pad2(daysInMonth)}`,
  }), [viewYear, viewMonth, daysInMonth]);

  const load = async () => {
    const r = await api.get("/journal", { params: monthRange });
    setEntries(r.data);
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [monthRange.date_from, monthRange.date_to]);

  const daysWithEntries = useMemo(() => {
    const s = new Set();
    entries.forEach((e) => { const p = parseIsoDate(e.date); if (p) s.add(p.d); });
    return s;
  }, [entries]);
  const visibleEntries = useMemo(
    () => (selectedDay ? entries.filter((e) => parseIsoDate(e.date)?.d === selectedDay) : entries),
    [entries, selectedDay]
  );

  const onMonthPick = (e) => {
    const [y, m] = (e.target.value || "").split("-").map(Number);
    if (y && m) { setViewYear(y); setViewMonth(m); setSelectedDay(null); }
    setMonthPickerOpen(false);
  };

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

  const delImage = async (id, index) => {
    const prev = entries;
    setEntries((es) => es.map((e) => (e.id === id ? { ...e, images: (e.images || []).filter((_, i) => i !== index) } : e)));
    try { await api.delete(`/journal/${id}/images/${index}`); }
    catch { toast.error("Errore nell'eliminare l'immagine"); setEntries(prev); }
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

      {/* Navigazione: mese al centro in alto, sotto tutti i giorni del mese in una riga -
          colorati se c'è una voce di diario quel giorno. Il mese mostra tutte le voci del
          mese (default); un giorno specifico filtra solo quello. */}
      <div className="flex flex-col items-center gap-3 mb-6">
        <div className="flex items-center gap-2">
          <div className="relative">
            <button
              data-testid="journal-month-picker-toggle"
              onClick={() => setMonthPickerOpen((v) => !v)}
              title="Cambia mese"
              className="p-1.5 text-white/70 hover:text-white transition-colors"
            >
              <Calendar size={16} />
            </button>
            {monthPickerOpen && (
              <input
                data-testid="journal-month-picker"
                type="month"
                autoFocus
                value={`${viewYear}-${pad2(viewMonth)}`}
                onChange={onMonthPick}
                onBlur={() => setMonthPickerOpen(false)}
                className="absolute z-10 top-full left-0 mt-1 rounded-lg bg-[#403A3C] text-white px-2 py-1 text-xs shadow-lg"
              />
            )}
          </div>
          <button
            data-testid="journal-month-label"
            onClick={() => setSelectedDay(null)}
            title="Mostra tutto il mese"
            className="text-xl font-semibold tracking-tight hover:opacity-80 transition-opacity"
            style={{ color: DIARY_TITLE_COLOR }}
          >
            {cap(IT_MONTHS_LONG[viewMonth - 1])} {viewYear}
          </button>
        </div>
        <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar max-w-full px-1 py-1">
          {Array.from({ length: daysInMonth }, (_, i) => i + 1).map((d) => {
            const has = daysWithEntries.has(d);
            const isSelected = selectedDay === d;
            return (
              <button
                key={d}
                data-testid={`journal-day-${d}`}
                onClick={() => setSelectedDay(d)}
                title={has ? "Apri questa giornata" : undefined}
                className={`shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-xs transition-all ${isSelected ? "ring-2 ring-white" : ""}`}
                style={{ backgroundColor: has ? "rgba(255,255,255,0.18)" : "rgba(255,255,255,0.06)", color: has ? "#FFFFFF" : "rgba(255,255,255,0.4)" }}
              >
                {d}
              </button>
            );
          })}
        </div>
      </div>

      {/* Giornate: solo i riquadri, nessun grafico/umore - la scrittura avviene dalla chat */}
      <div className="mt-6 space-y-3">
        {visibleEntries.length === 0 && (
          <div className="text-white/60 text-sm text-center">
            {selectedDay ? "Nessuna voce in questo giorno." : "Nessuna voce in questo mese."}
          </div>
        )}
        {visibleEntries.map((e) => {
          const { day, monYear } = formatBadge(e.date);
          const images = (e.images || []).slice(0, 3);
          const subtitle = (e.tags || []).length > 0 ? `Argomenti: ${e.tags.join(", ")}` : "";
          const topics = topicsForEntry(e);
          return (
            <div key={e.id} className="flex items-stretch gap-3" data-testid="journal-entry">
              <div className="card-soft flex flex-col items-center justify-center gap-1.5 shrink-0 w-20 text-center py-2.5 px-1">
                <div className="text-2xl font-normal leading-none" style={{ color: DIARY_DAY_COLOR }}>{day}</div>
                <div className="text-[10px] uppercase tracking-widest font-normal" style={{ color: DIARY_TITLE_COLOR }}>{monYear}</div>
                <button
                  data-testid="journal-fav"
                  onClick={() => toggleFav(e.id, !!e.favorite)}
                  title={e.favorite ? "Rimuovi dai preferiti" : "Segna come giornata memorabile"}
                  className="p-1.5 rounded-lg transition-colors duration-150 mt-0.5"
                  style={{ backgroundColor: e.favorite ? DIARY_FAV_COLOR : "transparent" }}
                >
                  <Star size={15} className={e.favorite ? "text-white fill-current" : "text-white/50"} />
                </button>
              </div>
              <button
                onClick={() => setExpandedId(e.id)}
                className="card-soft card-hover flex-1 min-w-0 text-left p-4 flex items-center gap-4"
              >
                <div className="min-w-0 flex-1">
                  <div className="font-normal text-base truncate" style={{ color: DIARY_TITLE_COLOR }}>{e.title || "Diario"}</div>
                  {subtitle && <div className="text-xs truncate mt-0.5 opacity-80" style={{ color: DIARY_TITLE_COLOR }}>{subtitle}</div>}
                  <div className="text-xs mt-1.5 line-clamp-3" style={{ color: DIARY_TEXT_COLOR }}>{e.cleaned_text}</div>
                  {topics.length > 0 && (
                    <div className="flex items-center gap-2 mt-2">
                      {topics.map((t) => (
                        <t.icon key={t.key} size={15} className="text-white" title={t.key.replace("_", " ")} />
                      ))}
                    </div>
                  )}
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
                <DialogTitle style={{ color: DIARY_TITLE_COLOR }}>{expandedEntry.title || "Diario"}</DialogTitle>
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
                  <div key={i} className="relative group">
                    <img src={src} alt="" className="w-full h-48 md:h-56 object-cover" />
                    <button
                      data-testid="journal-image-delete"
                      onClick={() => delImage(expandedEntry.id, i)}
                      title="Elimina immagine"
                      className="absolute top-1.5 right-1.5 p-1 rounded-full bg-black/60 text-white opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <X size={13} />
                    </button>
                  </div>
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
            {(expandedEntry.documents || []).length > 0 && (
              <div className="mt-3 pt-3 border-t border-white/15 space-y-1.5">
                {expandedEntry.documents.map((d, i) => (
                  <a key={i} href={d.url} target="_blank" rel="noreferrer" className="flex items-center gap-2 text-sm text-white/80 hover:text-white">
                    <Paperclip size={13} className="shrink-0" /> <span className="truncate">{d.name}</span>
                  </a>
                ))}
              </div>
            )}
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
