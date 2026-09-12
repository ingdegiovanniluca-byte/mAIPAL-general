import React, { useMemo, useRef, useEffect } from "react";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import { CalendarDays } from "lucide-react";

const IT_DAYS_SHORT = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];
const IT_MONTHS_LONG = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
const WEEKS_BEFORE = 26;
const WEEKS_AFTER = 26;

const DAY_LABEL_COL_WIDTH = 36; // px
const COL_WIDTH = 44; // px, per-week column
const COL_GAP = 20; // px
const COL_STRIDE = COL_WIDTH + COL_GAP;
const MONTH_ROW_HEIGHT = 18; // px

const NOW_ACCENT = "#FEA969"; // today's number + current week label
const SOFT_HIGHLIGHT = "#F2F2F2"; // rest of the current week's days + month-boundary week label
const MUTED_TEXT = "#ACA6A3";
const DOT_HAS = "#C3B0A5";
const DOT_FAV = "#FBBF24";
const DOT_OVERDUE = "#B16941";
const DOT_DONE = "#92D050";

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

export default function TaskCalendar({ tasks, collapsed, onToggleCollapse, selectedDate, onSelectDate, selectedWeekStart, onSelectWeek }) {
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

  // Every week where the month group changes (first week of a new month) -> used to color
  // that week's header, regardless of whether its label is actually drawn (see below).
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

  const monthBoundarySet = useMemo(() => new Set(monthBoundaries.map((b) => b.wi)), [monthBoundaries]);

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

  return (
    <TooltipProvider delayDuration={150}>
      <div className="mb-4 shrink-0">
        <div className="flex items-center gap-3 mb-2">
          <button
            data-testid="calendar-toggle"
            onClick={onToggleCollapse}
            className={`p-1.5 rounded-full transition-colors ${collapsed ? "text-white/40 hover:text-white/70" : "text-white/80 hover:text-white bg-white/10"}`}
            title={collapsed ? "Mostra calendario" : "Nascondi calendario"}
          >
            <CalendarDays size={16} />
          </button>
        </div>

        {!collapsed && (
          <div className="flex">
            <div className="flex flex-col shrink-0 pr-2.5" style={{ width: DAY_LABEL_COL_WIDTH, paddingTop: MONTH_ROW_HEIGHT + 24 }}>
              {IT_DAYS_SHORT.map((d) => (
                <div key={d} className="h-8 flex items-center text-[10px] uppercase tracking-wide" style={{ color: MUTED_TEXT }}>{d}</div>
              ))}
            </div>
            <div
              ref={scrollRef}
              onWheel={onWheel}
              onMouseDown={onMouseDown}
              className="flex-1 overflow-x-auto no-scrollbar select-none cursor-grab active:cursor-grabbing"
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
                    const isMonthChangeWeek = monthBoundarySet.has(wi);
                    const headerColor = isCurrentWeek ? NOW_ACCENT : isMonthChangeWeek ? SOFT_HIGHLIGHT : MUTED_TEXT;
                    const weekKey = isoDate(monday);
                    const isWeekSelected = selectedWeekStart === weekKey;
                    return (
                      <div key={wi} data-current-week={isCurrentWeek ? "true" : undefined} className="flex flex-col items-center shrink-0" style={{ width: COL_WIDTH }}>
                        <div
                          onClick={() => onSelectWeek && onSelectWeek(weekKey)}
                          className="h-6 flex items-center justify-center text-[10px] font-medium rounded-md cursor-pointer w-full"
                          style={{ color: headerColor, background: isWeekSelected ? "rgba(0, 176, 240, 0.22)" : "transparent" }}
                        >
                          W{isoWeekNumber(monday)}
                        </div>
                        {Array.from({ length: 7 }).map((_, di) => {
                          const day = new Date(monday);
                          day.setDate(day.getDate() + di);
                          const key = isoDate(day);
                          const isToday = key === todayStr;
                          const isSelected = selectedDate === key;
                          const stats = dayStats[key];
                          let dotColor = null;
                          if (stats) {
                            if (stats.overdue > 0) dotColor = DOT_OVERDUE;
                            else if (stats.fav > 0) dotColor = DOT_FAV;
                            else if (stats.doneCount === stats.count) dotColor = DOT_DONE;
                            else dotColor = DOT_HAS;
                          }
                          const textColor = isToday ? NOW_ACCENT : isCurrentWeek ? SOFT_HIGHLIGHT : MUTED_TEXT;
                          const cell = (
                            <div
                              onClick={() => onSelectDate && onSelectDate(key)}
                              className="h-8 w-full flex items-center justify-center rounded-md cursor-pointer"
                              style={{ background: isSelected ? "rgba(0, 176, 240, 0.22)" : "transparent" }}
                            >
                              <div className="relative h-6 w-6 flex items-center justify-center">
                                {dotColor && <span className="absolute rounded-full" style={{ background: dotColor, height: 18, width: 18 }} />}
                                <span className="relative text-[12px] font-medium" style={{ color: textColor }}>{day.getDate()}</span>
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
