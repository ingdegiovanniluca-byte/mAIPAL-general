import React, { useEffect, useMemo, useRef, useState } from "react";
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

// I 7 temi riconosciuti nelle giornate, mostrati come icone bianche accanto al titolo -
// dedotti dai tag che l'AI assegna alla voce (nessuna scelta manuale per ora).
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
const addDaysIso = (iso, delta) => {
  const p = parseIsoDate(iso);
  if (!p) return iso;
  const dt = new Date(p.y, p.m - 1, p.d + delta);
  return `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}-${pad2(dt.getDate())}`;
};
const buildDateWindow = (centerIso, radius) => {
  const out = [];
  for (let i = -radius; i <= radius; i++) out.push(addDaysIso(centerIso, i));
  return out;
};

// ===== Carosello "coverflow" per giorno =====
const CAROUSEL_RADIUS = 20;            // giorni renderizzati per lato (finestra scorrevole)
const CAROUSEL_EDGE_MARGIN = 6;        // a quanti giorni dal bordo della finestra si "ricentra" in silenzio
const CAROUSEL_FETCH_HALF_WINDOW = 40; // giorni di dati caricati per lato (margine oltre la finestra renderizzata)
const CAROUSEL_IMG_H = 64;             // px, altezza fissa dell'area immagini nella card

function DiaryDayCard({ iso, entry, isFocused, cardW, onClick, onToggleFav }) {
  const { day, monYear } = formatBadge(iso);
  if (!entry) {
    return (
      <div
        data-date={iso}
        onClick={onClick}
        className="card-soft flex flex-col p-5 cursor-pointer select-none h-full"
        data-testid="journal-day-card-empty"
      >
        <div className="text-4xl font-normal leading-none" style={{ color: DIARY_DAY_COLOR }}>{day}</div>
        <div className="text-[10px] uppercase tracking-widest mt-1" style={{ color: DIARY_TITLE_COLOR }}>{monYear}</div>
        <div className="text-xs mt-4 opacity-40" style={{ color: DIARY_TEXT_COLOR }}>Nessuna voce</div>
      </div>
    );
  }
  const images = (entry.images || []).slice(0, 3);
  const subtitle = (entry.tags || []).length > 0 ? `Argomenti: ${entry.tags.join(", ")}` : "";
  const topics = topicsForEntry(entry);
  return (
    <div
      data-date={iso}
      onClick={onClick}
      className={`card-soft flex flex-col p-5 cursor-pointer select-none h-full ${isFocused ? "card-hover" : ""}`}
      data-testid="journal-day-card"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-4xl font-normal leading-none" style={{ color: DIARY_DAY_COLOR }}>{day}</div>
          <div className="text-[10px] uppercase tracking-widest mt-1" style={{ color: DIARY_TITLE_COLOR }}>{monYear}</div>
        </div>
        <button
          data-testid="journal-fav"
          onClick={(ev) => { ev.stopPropagation(); onToggleFav(entry); }}
          title={entry.favorite ? "Rimuovi dai preferiti" : "Segna come giornata memorabile"}
          className="p-1.5 rounded-lg transition-colors duration-150 shrink-0"
          style={{ backgroundColor: entry.favorite ? DIARY_FAV_COLOR : "transparent" }}
        >
          <Star size={15} className={entry.favorite ? "text-white fill-current" : "text-white/50"} />
        </button>
      </div>

      <div className="flex items-start justify-between gap-2 mt-3">
        <div className="min-w-0">
          <div className="font-normal text-base truncate" style={{ color: DIARY_TITLE_COLOR }}>{entry.title || "Diario"}</div>
          {subtitle && <div className="text-xs truncate mt-0.5 opacity-80" style={{ color: DIARY_TITLE_COLOR }}>{subtitle}</div>}
        </div>
        {topics.length > 0 && (
          <div className="flex items-center gap-1.5 shrink-0 pt-0.5">
            {topics.map((t) => <t.icon key={t.key} size={14} className="text-white" title={t.key.replace("_", " ")} />)}
          </div>
        )}
      </div>

      <div className="text-xs mt-2 line-clamp-4" style={{ color: DIARY_TEXT_COLOR }}>{entry.cleaned_text}</div>

      {images.length > 0 && (
        <div className="flex items-end gap-1.5 mt-3 overflow-hidden" style={{ height: CAROUSEL_IMG_H }}>
          {images.map((src, i) => (
            <img key={i} src={src} alt="" className="rounded-md" style={{ height: CAROUSEL_IMG_H, width: "auto" }} />
          ))}
        </div>
      )}
    </div>
  );
}

function DiaryCarousel({ dates, entriesByDate, focusDate, centerRequest, onSettle, onOpenEntry, onToggleFav }) {
  const scrollerRef = useRef(null);
  const rafRef = useRef(null);
  const settleTimerRef = useRef(null);
  const draggingRef = useRef(false);
  const dragStartRef = useRef({ x: 0, scrollLeft: 0 });

  const [cardW, setCardW] = useState(300);
  useEffect(() => {
    const calc = () => setCardW(Math.max(220, Math.min(320, window.innerWidth - 64)));
    calc();
    window.addEventListener("resize", calc);
    return () => window.removeEventListener("resize", calc);
  }, []);

  // Applica scala/opacità/rotazione 3D in base alla distanza dal centro, direttamente sul
  // DOM (niente re-render React per ogni frame di scroll) - e ritorna l'indice della card
  // più vicina al centro, usata sia per lo "snap" manuale sia per rilevare l'arresto dello
  // scroll (settle).
  const applyTransforms = () => {
    const scroller = scrollerRef.current;
    if (!scroller) return null;
    const children = scroller.children;
    const rects = [];
    for (let i = 0; i < children.length; i++) rects.push(children[i].getBoundingClientRect());
    const containerRect = scroller.getBoundingClientRect();
    const centerX = containerRect.left + containerRect.width / 2;
    const unit = rects.length > 1 ? Math.abs(rects[1].left - rects[0].left) || 300 : 300;
    let nearestIdx = 0, nearestDist = Infinity;
    rects.forEach((r, i) => {
      const elCenterX = r.left + r.width / 2;
      const dist = (elCenterX - centerX) / unit;
      const ad = Math.min(Math.abs(dist), 4);
      const scale = 1 - 0.14 * ad;
      const opacity = Math.max(0.3, 1 - 0.32 * ad);
      const rotate = Math.max(-28, Math.min(28, -dist * 20));
      const tz = -ad * 60;
      const el = children[i];
      el.style.transform = `perspective(1400px) translateZ(${tz}px) rotateY(${rotate}deg) scale(${scale})`;
      el.style.opacity = String(opacity);
      el.style.zIndex = String(1000 - Math.round(ad * 10));
      const adist = Math.abs(elCenterX - centerX);
      if (adist < nearestDist) { nearestDist = adist; nearestIdx = i; }
    });
    return nearestIdx;
  };

  const scheduleFrame = () => {
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      applyTransforms();
    });
  };

  const onScroll = () => {
    scheduleFrame();
    if (settleTimerRef.current) clearTimeout(settleTimerRef.current);
    settleTimerRef.current = setTimeout(() => {
      const idx = applyTransforms();
      if (idx != null && dates[idx]) onSettle(dates[idx], idx, dates.length);
    }, 130);
  };

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return undefined;
    scroller.addEventListener("scroll", onScroll, { passive: true });
    requestAnimationFrame(applyTransforms);
    return () => {
      scroller.removeEventListener("scroll", onScroll);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (settleTimerRef.current) clearTimeout(settleTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dates]);

  // Riposiziona il carosello quando il genitore chiede un salto esplicito (click su un
  // giorno nella striscia, cambio mese) o silenzioso (ricentraggio ai bordi della finestra).
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const mid = scroller.children[CAROUSEL_RADIUS];
    if (mid) mid.scrollIntoView({ inline: "center", block: "nearest", behavior: centerRequest.behavior });
    requestAnimationFrame(applyTransforms);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centerRequest.nonce]);

  // Drag-to-scroll per mouse desktop (il touch ha già lo scroll nativo fluido)
  const onPointerDown = (e) => {
    if (e.pointerType === "touch") return;
    const scroller = scrollerRef.current;
    if (!scroller) return;
    draggingRef.current = true;
    dragStartRef.current = { x: e.clientX, scrollLeft: scroller.scrollLeft };
    scroller.style.scrollSnapType = "none";
    scroller.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e) => {
    if (!draggingRef.current) return;
    const scroller = scrollerRef.current;
    const dx = e.clientX - dragStartRef.current.x;
    scroller.scrollLeft = dragStartRef.current.scrollLeft - dx;
    scheduleFrame();
  };
  const endDrag = () => {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    const scroller = scrollerRef.current;
    if (!scroller) return;
    scroller.style.scrollSnapType = "x mandatory";
    // Lo snap CSS non si riapplica retroattivamente dopo il drag: agganciamo esplicitamente
    // alla card più vicina.
    const idx = applyTransforms();
    if (idx != null && scroller.children[idx]) {
      scroller.children[idx].scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
    }
  };

  return (
    <div
      ref={scrollerRef}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      className="flex gap-4 overflow-x-auto no-scrollbar py-8 cursor-grab active:cursor-grabbing"
      style={{
        scrollSnapType: "x mandatory",
        WebkitOverflowScrolling: "touch",
        paddingLeft: `calc(50% - ${cardW / 2}px)`,
        paddingRight: `calc(50% - ${cardW / 2}px)`,
      }}
      data-testid="journal-carousel"
    >
      {dates.map((iso) => {
        const entry = entriesByDate[iso];
        const isFocused = iso === focusDate;
        return (
          <div key={iso} style={{ scrollSnapAlign: "center", width: cardW, flexShrink: 0 }}>
            <DiaryDayCard
              iso={iso}
              entry={entry}
              isFocused={isFocused}
              cardW={cardW}
              onToggleFav={onToggleFav}
              onClick={() => {
                if (!isFocused) {
                  scrollerRef.current?.querySelector(`[data-date="${iso}"]`)?.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
                  return;
                }
                if (entry) onOpenEntry(entry);
              }}
            />
          </div>
        );
      })}
    </div>
  );
}

export default function JournalPage() {
  const today = new Date();
  const initialIso = `${today.getFullYear()}-${pad2(today.getMonth() + 1)}-01`;

  // Un'unica sorgente di verità per la navigazione: la data attualmente al centro del
  // carosello. centerRequest è il "comando" esplicito che sposta il carosello (click su un
  // giorno, cambio mese, oppure il ricentraggio silenzioso quando si scorre vicino al bordo
  // della finestra renderizzata) - focusDate segue lo scroll effettivo (anche durante un
  // trascinamento libero) per tenere sincronizzata l'intestazione (mese/striscia giorni).
  const [centerRequest, setCenterRequest] = useState({ date: initialIso, behavior: "auto", nonce: 0 });
  const [focusDate, setFocusDate] = useState(initialIso);
  const [entriesByDate, setEntriesByDate] = useState({});
  const [loadedRange, setLoadedRange] = useState(null);
  const [monthPickerOpen, setMonthPickerOpen] = useState(false);
  const [expandedEntry, setExpandedEntry] = useState(null);

  const dates = useMemo(() => buildDateWindow(centerRequest.date, CAROUSEL_RADIUS), [centerRequest.date]);

  const focusParts = parseIsoDate(focusDate) || parseIsoDate(initialIso);
  const daysInMonth = useMemo(() => new Date(focusParts.y, focusParts.m, 0).getDate(), [focusParts.y, focusParts.m]);

  // Carica le voci in una finestra di giorni attorno al centro (non solo il mese mostrato,
  // dato che il carosello può scorrere oltre i confini del mese) - rifà la richiesta solo
  // quando ci si avvicina al bordo di quanto già caricato.
  useEffect(() => {
    const from = addDaysIso(centerRequest.date, -CAROUSEL_FETCH_HALF_WINDOW);
    const to = addDaysIso(centerRequest.date, CAROUSEL_FETCH_HALF_WINDOW);
    if (loadedRange && from >= loadedRange.from && to <= loadedRange.to) return;
    (async () => {
      const r = await api.get("/journal", { params: { date_from: from, date_to: to } });
      const map = {};
      // Più voci nello stesso giorno (raro, ma non impedito): la card del giorno mostra la
      // più recente; le altre restano comunque nel DB e nella lista completa.
      r.data.forEach((e) => {
        const existing = map[e.date];
        if (!existing || (e.created_at || "") > (existing.created_at || "")) map[e.date] = e;
      });
      setEntriesByDate(map);
      setLoadedRange({ from, to });
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centerRequest.date]);

  const goTo = (iso, behavior = "smooth") => {
    setFocusDate(iso);
    setCenterRequest((r) => ({ date: iso, behavior, nonce: r.nonce + 1 }));
  };

  const onCarouselSettle = (iso, idx, len) => {
    setFocusDate(iso);
    if (idx <= CAROUSEL_EDGE_MARGIN || idx >= len - 1 - CAROUSEL_EDGE_MARGIN) {
      setCenterRequest((r) => ({ date: iso, behavior: "auto", nonce: r.nonce + 1 }));
    }
  };

  const onMonthPick = (e) => {
    const [y, m] = (e.target.value || "").split("-").map(Number);
    if (y && m) goTo(`${y}-${pad2(m)}-01`);
    setMonthPickerOpen(false);
  };

  const toggleFav = async (entry) => {
    const prevVal = !!entry.favorite;
    setEntriesByDate((mp) => ({ ...mp, [entry.date]: { ...mp[entry.date], favorite: !prevVal } }));
    if (expandedEntry?.id === entry.id) setExpandedEntry((e) => (e ? { ...e, favorite: !prevVal } : e));
    try { await api.post(`/journal/${entry.id}/favorite`); }
    catch {
      toast.error("Errore preferito");
      setEntriesByDate((mp) => ({ ...mp, [entry.date]: { ...mp[entry.date], favorite: prevVal } }));
      if (expandedEntry?.id === entry.id) setExpandedEntry((e) => (e ? { ...e, favorite: prevVal } : e));
    }
  };

  const del = (entry) => {
    toast("Eliminare questa voce di diario?", {
      action: {
        label: "Elimina",
        onClick: async () => {
          const prev = entriesByDate;
          setEntriesByDate((mp) => { const n = { ...mp }; delete n[entry.date]; return n; });
          try { await api.delete(`/journal/${entry.id}`); toast.success("Voce eliminata"); }
          catch { toast.error("Errore"); setEntriesByDate(prev); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  const delImage = async (entry, index) => {
    const prevImgs = entry.images || [];
    const newImgs = prevImgs.filter((_, i) => i !== index);
    setEntriesByDate((mp) => ({ ...mp, [entry.date]: { ...mp[entry.date], images: newImgs } }));
    setExpandedEntry((e) => (e && e.id === entry.id ? { ...e, images: newImgs } : e));
    try { await api.delete(`/journal/${entry.id}/images/${index}`); }
    catch {
      toast.error("Errore nell'eliminare l'immagine");
      setEntriesByDate((mp) => ({ ...mp, [entry.date]: { ...mp[entry.date], images: prevImgs } }));
      setExpandedEntry((e) => (e && e.id === entry.id ? { ...e, images: prevImgs } : e));
    }
  };

  const daysWithEntries = useMemo(() => {
    const s = new Set();
    const prefix = `${focusParts.y}-${pad2(focusParts.m)}-`;
    Object.keys(entriesByDate).forEach((iso) => { if (iso.startsWith(prefix)) s.add(Number(iso.slice(8, 10))); });
    return s;
  }, [entriesByDate, focusParts.y, focusParts.m]);

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
          colorati se c'è una voce di diario quel giorno. Cliccando un giorno il carosello
          sotto scorre fino a portarlo al centro. */}
      <div className="flex flex-col items-center gap-3 mb-2">
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
                value={`${focusParts.y}-${pad2(focusParts.m)}`}
                onChange={onMonthPick}
                onBlur={() => setMonthPickerOpen(false)}
                className="absolute z-10 top-full left-0 mt-1 rounded-lg bg-[#403A3C] text-white px-2 py-1 text-xs shadow-lg"
              />
            )}
          </div>
          <button
            data-testid="journal-month-label"
            onClick={() => goTo(`${focusParts.y}-${pad2(focusParts.m)}-01`)}
            title="Torna al primo del mese"
            className="text-xl font-semibold tracking-tight hover:opacity-80 transition-opacity"
            style={{ color: DIARY_TITLE_COLOR }}
          >
            {cap(IT_MONTHS_LONG[focusParts.m - 1])} {focusParts.y}
          </button>
        </div>
        <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar max-w-full px-1 py-1">
          {Array.from({ length: daysInMonth }, (_, i) => i + 1).map((d) => {
            const has = daysWithEntries.has(d);
            const isSelected = focusParts.d === d;
            return (
              <button
                key={d}
                data-testid={`journal-day-${d}`}
                onClick={() => goTo(`${focusParts.y}-${pad2(focusParts.m)}-${pad2(d)}`)}
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

      {/* Carosello "coverflow": il giorno al centro in primo piano, gli altri sfumati in
          prospettiva - scorrimento fluido (trascinamento o rotellina/touch), niente
          grafico/umore, la scrittura avviene dalla chat. */}
      <DiaryCarousel
        dates={dates}
        entriesByDate={entriesByDate}
        focusDate={focusDate}
        centerRequest={centerRequest}
        onSettle={onCarouselSettle}
        onOpenEntry={setExpandedEntry}
        onToggleFav={toggleFav}
      />

      {/* Vista estesa di una giornata: foto in griglia + testo completo */}
      {expandedEntry && (
        <Dialog open={true} onOpenChange={() => setExpandedEntry(null)}>
          <DialogContent className="max-w-2xl bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="journal-expanded">
            <DialogHeader>
              <div className="flex items-center justify-between gap-2 pr-6">
                <DialogTitle style={{ color: DIARY_TITLE_COLOR }}>{expandedEntry.title || "Diario"}</DialogTitle>
                <button
                  data-testid="journal-delete"
                  onClick={() => { del(expandedEntry); setExpandedEntry(null); }}
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
                      onClick={() => delImage(expandedEntry, i)}
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
