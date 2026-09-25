import React, { useMemo, useRef, useEffect, useState } from "react";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import { CalendarDays } from "lucide-react";
import { useIsMobile } from "@/hooks/use-is-mobile";
import { useSetMobileTitleSuffix } from "@/lib/mobile-title";

const IT_DAYS_SHORT = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];
const IT_MONTHS_LONG = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
const IT_MONTHS_SHORT = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"];
const WEEKS_BEFORE = 26;
const WEEKS_AFTER = 26;

// Desktop keeps its original horizontally-scrolling multi-week layout untouched. Mobile
// (below) uses a completely different single-week "day strip" layout instead, so none of
// this fixed column sizing applies there.
const DAY_LABEL_COL_WIDTH_DESKTOP = 36; // px
const COL_WIDTH_DESKTOP = 44; // px, per-week column
const COL_GAP_DESKTOP = 20; // px
const MONTH_ROW_HEIGHT = 18; // px

const DOT_HAS = "#826556";
const DOT_FAV = "#FBBF24";
const DOT_OVERDUE = "#B16941";
const DOT_DONE = "#8ED973";
const MUTED_TEXT = "#D9D9D9";
const ACCENT = "#00B0F0"; // same cyan used for the selected day/week everywhere in the app
// Mobile: days with open (not overdue) tasks get the same fill as the diary's days that have a
// written page.
const DIARY_DAY_FILL = "rgba(255,255,255,0.18)";

function withAlpha(hex, alpha) {
  const h = hex.replace("#", "");
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function startOfWeek(d) {
  const date = new Date(d);
  const day = date.getDay(); // 0 = domenica
  const diff = (day === 0 ? -6 : 1) - day;
  date.setDate(date.getDate() + diff);
  date.setHours(0, 0, 0, 0);
  return date;
}

const isoDate = (d) => {
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, "0"), dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
};

function isoWeekNumber(d) {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - dayNum + 3);
  const firstThursday = new Date(Date.UTC(date.getUTCFullYear(), 0, 4));
  const diff = date - firstThursday;
  return 1 + Math.round(diff / (7 * 24 * 3600 * 1000));
}

// A week "belongs" to the month/year containing its Thursday (same convention as ISO week
// numbers), so a week spanning two months resolves unambiguously to one month group.
function weekMonthKey(monday) {
  const thu = new Date(monday);
  thu.setDate(thu.getDate() + 3);
  return { month: thu.getMonth(), year: thu.getFullYear() };
}

const DRAG_THRESHOLD = 4; // px of movement before a mousedown counts as a drag, not a click

// mobileBelowStrip: content the Task page shows right under the mobile day strip (the active
// day/week filter). onVisibleMonthChange: called on mobile with { month, year } of the week
// shown, so the list below can default to that month.
export default function TaskCalendar({ tasks, collapsed, onToggleCollapse, selectedDate, onSelectDate, selectedWeekStart, onSelectWeek, mobileBelowStrip = null, onVisibleMonthChange = null }) {
  const isMobile = useIsMobile();
  const DAY_LABEL_COL_WIDTH = DAY_LABEL_COL_WIDTH_DESKTOP;
  const COL_WIDTH = COL_WIDTH_DESKTOP;
  const COL_GAP = COL_GAP_DESKTOP;
  const COL_STRIDE = COL_WIDTH + COL_GAP;

  const scrollRef = useRef(null);
  const draggingRef = useRef(false);
  const dragMovedRef = useRef(false);
  const dragStartXRef = useRef(0);
  const dragStartScrollRef = useRef(0);
  const todayStr = isoDate(new Date());
  const thisMonday = useMemo(() => startOfWeek(new Date()), []);

  const weeks = useMemo(() => {
    const arr = [];
    for (let i = -WEEKS_BEFORE; i <= WEEKS_AFTER; i++) {
      const monday = new Date(thisMonday);
      monday.setDate(monday.getDate() + i * 7);
      arr.push(monday);
    }
    return arr;
  }, [thisMonday]);

  // Every week where the month group changes (first week of a new month).
  const monthBoundaries = useMemo(() => {
    const out = [];
    let prevKey = null;
    weeks.forEach((monday, wi) => {
      const { month, year } = weekMonthKey(monday);
      const key = `${year}-${month}`;
      if (key !== prevKey) {
        out.push({ wi, month, year });
        prevKey = key;
      }
    });
    return out;
  }, [weeks]);

  // Only every other month boundary gets a visible text label, to avoid crowding.
  const monthLabels = useMemo(
    () => monthBoundaries
      .filter((_, idx) => idx % 2 === 0)
      .map((b) => ({ wi: b.wi, label: `${IT_MONTHS_LONG[b.month]} ${b.year}` })),
    [monthBoundaries]
  );

  const dayStats = useMemo(() => {
    const map = {};
    for (const t of tasks) {
      if (!t.due_date) continue;
      const key = t.due_date;
      if (!map[key]) map[key] = { count: 0, fav: 0, overdue: 0, doneCount: 0 };
      map[key].count += 1;
      if (t.favorite) map[key].fav += 1;
      if (t.completed) map[key].doneCount += 1;
      if (!t.completed && t.due_date < todayStr) map[key].overdue += 1;
    }
    return map;
  }, [tasks, todayStr]);

  // ===== Vista mobile: una sola settimana alla volta (invece dello scroll multi-settimana
  // desktop), indice nell'array `weeks` - thisMonday e' sempre all'indice WEEKS_BEFORE per
  // come e' costruito l'array sopra. =====
  const [mobileWeekIdx, setMobileWeekIdx] = useState(WEEKS_BEFORE);
  useEffect(() => {
    if (!isMobile || !selectedDate) return;
    const idx = weeks.findIndex((monday) => {
      const start = isoDate(monday);
      const endDate = new Date(monday);
      endDate.setDate(endDate.getDate() + 6);
      const end = isoDate(endDate);
      return selectedDate >= start && selectedDate <= end;
    });
    if (idx >= 0) setMobileWeekIdx(idx);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDate, isMobile]);
  const goMobileWeek = (delta) => setMobileWeekIdx((i) => Math.max(0, Math.min(weeks.length - 1, i + delta)));
  const mobileMonday = weeks[mobileWeekIdx] || thisMonday;
  const mobileDays = useMemo(
    () => Array.from({ length: 7 }, (_, di) => { const d = new Date(mobileMonday); d.setDate(d.getDate() + di); return d; }),
    [mobileMonday]
  );
  const mobileMonthYear = weekMonthKey(mobileMonday);

  // The mobile top bar reads "Task <year>", following the week currently shown (the year of
  // its Thursday, same rule as the month label) - cleared again when leaving the page.
  const setTitleSuffix = useSetMobileTitleSuffix();
  const shownYear = mobileMonthYear.year;
  const shownMonth = mobileMonthYear.month;
  useEffect(() => {
    if (!isMobile) return undefined;
    setTitleSuffix(String(shownYear));
    return () => setTitleSuffix("");
  }, [isMobile, shownYear, setTitleSuffix]);
  useEffect(() => {
    if (isMobile && onVisibleMonthChange) onVisibleMonthChange({ month: shownMonth, year: shownYear });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMobile, shownMonth, shownYear]);

  // Mobile: the calendar stays pinned under the top bar while the task list scrolls; its
  // frosted backing (same as the top bar) only appears once something scrolls beneath it.
  const [pageScrolled, setPageScrolled] = useState(false);
  useEffect(() => {
    if (!isMobile) return undefined;
    const onScroll = () => setPageScrolled(window.scrollY > 4);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [isMobile]);

  // Swipe col dito sulla riga dei giorni per cambiare settimana (niente frecce) - stesso
  // schema del carosello del diario: la cattura/il cambio settimana scatta solo oltre una
  // soglia di movimento reale, e un listener "click" in fase di cattura sopprime il click
  // nativo che altrimenti aprirebbe a caso il giorno sotto il dito al rilascio dello swipe.
  const weekGridRef = useRef(null);
  const weekDragRef = useRef(null);
  const weekDragMovedRef = useRef(false);
  const SWIPE_MOVE_THRESHOLD = 8;
  const SWIPE_CHANGE_THRESHOLD = 40;

  // Re-run when the grid remounts (calendar collapsed/reopened, or the mobile/desktop switch):
  // the listener lives on that specific DOM node, so a one-shot [] effect lost it after the
  // first collapse.
  useEffect(() => {
    const el = weekGridRef.current;
    if (!el) return undefined;
    const suppressClickAfterSwipe = (e) => {
      if (weekDragMovedRef.current) { e.preventDefault(); e.stopPropagation(); }
    };
    el.addEventListener("click", suppressClickAfterSwipe, true);
    return () => el.removeEventListener("click", suppressClickAfterSwipe, true);
  }, [collapsed, isMobile]);

  const onWeekPointerDown = (e) => {
    weekDragMovedRef.current = false;
    weekDragRef.current = { x: e.clientX };
  };
  const onWeekPointerMove = (e) => {
    const start = weekDragRef.current;
    if (!start) return;
    if (!weekDragMovedRef.current && Math.abs(e.clientX - start.x) > SWIPE_MOVE_THRESHOLD) weekDragMovedRef.current = true;
  };
  const onWeekPointerUp = (e) => {
    const start = weekDragRef.current;
    weekDragRef.current = null;
    if (!start) return;
    const dx = e.clientX - start.x;
    if (Math.abs(dx) > SWIPE_CHANGE_THRESHOLD) goMobileWeek(dx < 0 ? 1 : -1);
    setTimeout(() => { weekDragMovedRef.current = false; }, 0);
  };

  useEffect(() => {
    if (!collapsed && scrollRef.current) {
      const el = scrollRef.current.querySelector('[data-current-week="true"]');
      if (el) el.scrollIntoView({ inline: "center", block: "nearest" });
    }
  }, [collapsed]);

  const onWheel = (e) => {
    if (scrollRef.current && e.deltaY !== 0) {
      e.preventDefault();
      scrollRef.current.scrollLeft += e.deltaY;
    }
  };

  const onMouseDown = (e) => {
    draggingRef.current = true;
    dragMovedRef.current = false;
    dragStartXRef.current = e.pageX;
    dragStartScrollRef.current = scrollRef.current.scrollLeft;
  };

  useEffect(() => {
    const onMouseMove = (e) => {
      if (!draggingRef.current || !scrollRef.current) return;
      const dx = e.pageX - dragStartXRef.current;
      // Below the threshold, treat it as a click in progress and don't touch scroll at
      // all - otherwise the tiny hand-tremor movement in every real click can make the
      // browser cancel the click event once we start mutating scrollLeft mid-gesture.
      if (!dragMovedRef.current && Math.abs(dx) < DRAG_THRESHOLD) return;
      dragMovedRef.current = true;
      scrollRef.current.scrollLeft = dragStartScrollRef.current - dx;
    };
    const onMouseUp = () => { draggingRef.current = false; };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  const totalWidth = weeks.length * COL_STRIDE - COL_GAP;

  // ===== Mobile: stessa struttura del riferimento grafico - in alto a sinistra le prime tre
  // lettere del mese (grande, con il punto colorato), a destra il numero della settimana;
  // sotto i sette giorni, con l'evidenziazione solo attorno al numero. Il calendario è sempre
  // aperto; si cambia settimana scorrendo col dito sui giorni. =====
  if (isMobile) {
    const weekKey = isoDate(mobileMonday);
    const isWeekSelected = selectedWeekStart === weekKey;
    return (
      <TooltipProvider delayDuration={150}>
        <div
          data-testid="calendar-mobile-week"
          className={`shrink-0 sticky top-14 z-30 -mx-4 px-4 pt-4 pb-5 mb-7 transition-colors duration-200 ${pageScrolled ? "bg-white/5 backdrop-blur-xl" : ""}`}
        >
          <div className="flex items-end justify-between px-1 mb-3">
            <div className="text-[44px] font-bold leading-none tracking-tight text-white" data-testid="calendar-mobile-month">
              {IT_MONTHS_SHORT[mobileMonthYear.month]}<span style={{ color: ACCENT }}>.</span>
            </div>
            <button
              data-testid="calendar-mobile-weeknum"
              onClick={() => onSelectWeek && onSelectWeek(weekKey)}
              title={isWeekSelected ? "Mostra tutti i task" : "Mostra solo i task di questa settimana"}
              className="text-[44px] font-light leading-none tabular-nums transition-colors"
              style={{ color: isWeekSelected ? ACCENT : MUTED_TEXT }}
            >
              {isoWeekNumber(mobileMonday)}
            </button>
          </div>
          {/* Scorrimento a dito per cambiare settimana - touch-pan-y lascia lo swipe orizzontale
              al gesto e lo scroll verticale alla pagina. */}
          <div
            ref={weekGridRef}
            onPointerDown={onWeekPointerDown}
            onPointerMove={onWeekPointerMove}
            onPointerUp={onWeekPointerUp}
            onPointerCancel={onWeekPointerUp}
            className="grid grid-cols-7 touch-pan-y"
          >
            {mobileDays.map((day, di) => {
              const key = isoDate(day);
              const isSelected = selectedDate === key;
              const isToday = key === todayStr;
              const stats = dayStats[key];
              let cellFill = "transparent";
              if (stats) {
                if (stats.overdue > 0) cellFill = withAlpha(DOT_OVERDUE, 0.9);
                else if (stats.doneCount === stats.count) cellFill = withAlpha(DOT_DONE, 0.9);
                else cellFill = DIARY_DAY_FILL;
              }
              const cellBg = isSelected ? withAlpha(ACCENT, 0.9) : cellFill;
              const cell = (
                <div key={di} className="flex flex-col items-center gap-1.5">
                  <div
                    onClick={() => onSelectDate && onSelectDate(key)}
                    className="h-8 w-8 flex items-center justify-center rounded-full cursor-pointer text-[13px] font-semibold text-white"
                    style={{ background: cellBg }}
                  >
                    {day.getDate()}
                  </div>
                  <span
                    className="text-[9px] font-semibold uppercase tracking-wide"
                    style={{ color: isSelected ? ACCENT : isToday ? "#FFFFFF" : "rgba(255,255,255,0.45)" }}
                  >
                    {IT_DAYS_SHORT[di]}
                  </span>
                </div>
              );
              if (!stats) return cell;
              const parts = [`${stats.count} task`];
              if (stats.fav) parts.push(`${stats.fav} preferit${stats.fav !== 1 ? "i" : "o"}`);
              if (stats.overdue) parts.push(`${stats.overdue} scadut${stats.overdue !== 1 ? "i" : "o"}`);
              return (
                <Tooltip key={di}>
                  <TooltipTrigger asChild>{cell}</TooltipTrigger>
                  <TooltipContent side="top">{parts.join(" · ")}</TooltipContent>
                </Tooltip>
              );
            })}
          </div>
          {mobileBelowStrip}
        </div>
      </TooltipProvider>
    );
  }

  return (
    <TooltipProvider delayDuration={150}>
      <div className="shrink-0 mb-8">
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <button
            data-testid="calendar-toggle"
            onClick={onToggleCollapse}
            className={`rounded-full transition-colors p-1.5 ${collapsed ? "text-white/40 hover:text-white/70" : "text-white/80 hover:text-white bg-white/10"}`}
            title={collapsed ? "Mostra calendario" : "Nascondi calendario"}
          >
            <CalendarDays size={16} />
          </button>
          {!collapsed && (
            <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px] md:flex md:items-center md:gap-3 md:text-[11px] text-white/60 ml-2 md:ml-6">
              <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: DOT_FAV }} />preferiti</span>
              <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: DOT_OVERDUE }} />scaduti</span>
              <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: DOT_DONE }} />tutti conclusi</span>
              <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: DOT_HAS }} />task presenti</span>
            </div>
          )}
        </div>

        {!collapsed && (
          <div className="flex">
            <div className="flex flex-col shrink-0 pr-2.5" style={{ width: DAY_LABEL_COL_WIDTH, paddingTop: MONTH_ROW_HEIGHT + 24 }}>
              {IT_DAYS_SHORT.map((d) => (
                <div key={d} className="h-8 flex items-center text-[10px] uppercase tracking-wide text-white">{d}</div>
              ))}
            </div>
            <div
              ref={scrollRef}
              onWheel={onWheel}
              onMouseDown={onMouseDown}
              className="flex-1 min-w-0 overflow-x-auto no-scrollbar select-none cursor-grab active:cursor-grabbing"
            >
              <div style={{ position: "relative", width: totalWidth }}>
                <div style={{ position: "relative", height: MONTH_ROW_HEIGHT }}>
                  {monthLabels.map(({ wi, label }) => (
                    <div
                      key={wi}
                      style={{ position: "absolute", left: wi * COL_STRIDE, whiteSpace: "nowrap", color: "rgba(255,255,255,0.7)" }}
                      className="text-[11px] font-medium capitalize"
                    >
                      {label}
                    </div>
                  ))}
                </div>
                <div className="flex" style={{ gap: COL_GAP }}>
                  {weeks.map((monday, wi) => {
                    const isCurrentWeek = isoDate(monday) === isoDate(thisMonday);
                    const headerColor = "#FFFFFF";
                    const weekKey = isoDate(monday);
                    const isWeekSelected = selectedWeekStart === weekKey;
                    return (
                      <div key={wi} data-current-week={isCurrentWeek ? "true" : undefined} className="flex flex-col items-center shrink-0" style={{ width: COL_WIDTH }}>
                        <div
                          onClick={() => onSelectWeek && onSelectWeek(weekKey)}
                          className={`h-6 flex items-center justify-center text-[10px] rounded-md cursor-pointer w-full ${isCurrentWeek ? "font-bold" : "font-medium"}`}
                          style={{ color: headerColor, background: isWeekSelected ? "rgba(0, 176, 240, 0.22)" : "transparent" }}
                        >
                          W{isoWeekNumber(monday)}
                        </div>
                        {Array.from({ length: 7 }).map((_, di) => {
                          const day = new Date(monday);
                          day.setDate(day.getDate() + di);
                          const key = isoDate(day);
                          const isSelected = selectedDate === key;
                          const stats = dayStats[key];
                          let dotColor = null;
                          if (stats) {
                            if (stats.overdue > 0) dotColor = DOT_OVERDUE;
                            else if (stats.fav > 0) dotColor = DOT_FAV;
                            else if (stats.doneCount === stats.count) dotColor = DOT_DONE;
                            else dotColor = DOT_HAS;
                          }
                          const textColor = isCurrentWeek ? "#FFFFFF" : MUTED_TEXT;
                          const hasBg = isSelected || !!dotColor;
                          const cellBg = isSelected
                            ? withAlpha("#00B0F0", 0.9)
                            : dotColor
                              ? withAlpha(dotColor, 0.9)
                              : "transparent";
                          const cell = (
                            <div
                              onClick={() => onSelectDate && onSelectDate(key)}
                              className="h-8 w-full flex items-center justify-center cursor-pointer"
                            >
                              <div
                                className="h-6 w-full flex items-center justify-center rounded-md"
                                style={{
                                  background: cellBg,
                                  backdropFilter: hasBg ? "blur(6px) saturate(160%)" : "none",
                                  WebkitBackdropFilter: hasBg ? "blur(6px) saturate(160%)" : "none",
                                  boxShadow: hasBg ? "inset 0 1px 1px rgba(255, 255, 255, 0.3), 0 2px 6px rgba(0, 0, 0, 0.15)" : "none",
                                }}
                              >
                                <span className="text-[12px] font-medium" style={{ color: textColor }}>{day.getDate()}</span>
                              </div>
                            </div>
                          );
                          if (!stats) return <div key={di}>{cell}</div>;
                          const parts = [`${stats.count} task`];
                          if (stats.fav) parts.push(`${stats.fav} preferit${stats.fav !== 1 ? "i" : "o"}`);
                          if (stats.overdue) parts.push(`${stats.overdue} scadut${stats.overdue !== 1 ? "i" : "o"}`);
                          return (
                            <Tooltip key={di}>
                              <TooltipTrigger asChild>{cell}</TooltipTrigger>
                              <TooltipContent side="top">{parts.join(" · ")}</TooltipContent>
                            </Tooltip>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </TooltipProvider>
  );
}
