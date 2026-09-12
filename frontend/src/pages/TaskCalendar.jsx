import React, { useEffect, useMemo, useRef, useState } from "react";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import { CalendarDays } from "lucide-react";

const IT_DAYS_SHORT = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];
const IT_MONTHS_LONG = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
const WEEKS_BEFORE = 26;
const WEEKS_AFTER = 26;

const DAY_LABEL_COL_WIDTH = 36; // px, kept in sync between header spacer and the day-label column
const COL_WIDTH = 44; // px, per-week column
const COL_GAP = 20; // px
const COL_STRIDE = COL_WIDTH + COL_GAP;

const CURRENT_TEXT = "#F2F2F2";
const MUTED_TEXT = "#ACA6A3";
const DOT_HAS = "#7F6D69";
const DOT_FAV = "#FBBF24";
const DOT_OVERDUE = "#B16941";
const DOT_DONE = "#85B98A";

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

// A week "belongs" to the month/year containing its Thursday (same convention as ISO week numbers),
// so a week spanning two months resolves unambiguously.
function weekMonthYear(monday) {
  const thu = new Date(monday);
  thu.setDate(thu.getDate() + 3);
  return `${IT_MONTHS_LONG[thu.getMonth()]} ${thu.getFullYear()}`;
}

export default function TaskCalendar({ tasks, collapsed, onToggleCollapse }) {
  const scrollRef = useRef(null);
  const draggingRef = useRef(false);
  const dragStartXRef = useRef(0);
  const dragStartScrollRef = useRef(0);
  const todayStr = isoDate(new Date());
  const thisMonday = useMemo(() => startOfWeek(new Date()), []);
  const [centerIdx, setCenterIdx] = useState(WEEKS_BEFORE);

  const weeks = useMemo(() => {
    const arr = [];
    for (let i = -WEEKS_BEFORE; i <= WEEKS_AFTER; i++) {
      const monday = new Date(thisMonday);
      monday.setDate(monday.getDate() + i * 7);
      arr.push(monday);
    }
    return arr;
  }, [thisMonday]);

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

  const updateCenterFromScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const contentX = el.scrollLeft + el.clientWidth / 2;
    const idx = Math.min(weeks.length - 1, Math.max(0, Math.floor(contentX / COL_STRIDE)));
    setCenterIdx(idx);
  };

  useEffect(() => {
    if (!collapsed && scrollRef.current) {
      const el = scrollRef.current.querySelector('[data-current-week="true"]');
      if (el) el.scrollIntoView({ inline: "center", block: "nearest" });
      requestAnimationFrame(updateCenterFromScroll);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collapsed]);

  const onWheel = (e) => {
    if (scrollRef.current && e.deltaY !== 0) {
      e.preventDefault();
      scrollRef.current.scrollLeft += e.deltaY;
      updateCenterFromScroll();
    }
  };

  const onScroll = () => {
    requestAnimationFrame(updateCenterFromScroll);
  };

  const onMouseDown = (e) => {
    e.preventDefault();
    draggingRef.current = true;
    dragStartXRef.current = e.pageX;
    dragStartScrollRef.current = scrollRef.current.scrollLeft;
  };

  useEffect(() => {
    const onMouseMove = (e) => {
      if (!draggingRef.current || !scrollRef.current) return;
      const dx = e.pageX - dragStartXRef.current;
      scrollRef.current.scrollLeft = dragStartScrollRef.current - dx;
      updateCenterFromScroll();
    };
    const onMouseUp = () => { draggingRef.current = false; };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weeks]);

  const monthYearLabel = weeks[centerIdx] ? weekMonthYear(weeks[centerIdx]) : "";

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
          {!collapsed && (
            <div style={{ marginLeft: DAY_LABEL_COL_WIDTH }} className="text-sm font-medium text-white/70 capitalize">
              {monthYearLabel}
            </div>
          )}
        </div>

        {!collapsed && (
          <div className="flex">
            <div className="flex flex-col shrink-0 pr-2.5 pt-6" style={{ width: DAY_LABEL_COL_WIDTH }}>
              {IT_DAYS_SHORT.map((d) => (
                <div key={d} className="h-8 flex items-center text-[10px] uppercase tracking-wide" style={{ color: MUTED_TEXT }}>{d}</div>
              ))}
            </div>
            <div
              ref={scrollRef}
              onWheel={onWheel}
              onScroll={onScroll}
              onMouseDown={onMouseDown}
              className="flex-1 overflow-x-auto no-scrollbar select-none cursor-grab active:cursor-grabbing"
            >
              <div className="flex" style={{ gap: COL_GAP }}>
                {weeks.map((monday, wi) => {
                  const isCurrentWeek = isoDate(monday) === isoDate(thisMonday);
                  const headerColor = isCurrentWeek ? CURRENT_TEXT : MUTED_TEXT;
                  return (
                    <div key={wi} data-current-week={isCurrentWeek ? "true" : undefined} className="flex flex-col items-center shrink-0" style={{ width: COL_WIDTH }}>
                      <div className="h-6 flex items-center justify-center text-[10px] font-medium" style={{ color: headerColor }}>
                        W{isoWeekNumber(monday)}
                      </div>
                      {Array.from({ length: 7 }).map((_, di) => {
                        const day = new Date(monday);
                        day.setDate(day.getDate() + di);
                        const key = isoDate(day);
                        const stats = dayStats[key];
                        let dotColor = null;
                        if (stats) {
                          if (stats.overdue > 0) dotColor = DOT_OVERDUE;
                          else if (stats.fav > 0) dotColor = DOT_FAV;
                          else if (stats.doneCount === stats.count) dotColor = DOT_DONE;
                          else dotColor = DOT_HAS;
                        }
                        const textColor = isCurrentWeek ? CURRENT_TEXT : MUTED_TEXT;
                        const cell = (
                          <div className="h-8 w-full flex items-center justify-center">
                            <div className="relative h-7 w-7 flex items-center justify-center">
                              {dotColor && <span className="absolute inset-0 rounded-full" style={{ background: dotColor }} />}
                              <span className="relative text-[12px]" style={{ color: textColor }}>{day.getDate()}</span>
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
        )}
      </div>
    </TooltipProvider>
  );
}
