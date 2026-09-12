import React, { useEffect, useMemo, useRef } from "react";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import { ChevronUp, ChevronDown, CalendarDays } from "lucide-react";

const IT_DAYS_SHORT = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];
const WEEKS_BEFORE = 26;
const WEEKS_AFTER = 26;

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

export default function TaskCalendar({ tasks, collapsed, onToggleCollapse }) {
  const scrollRef = useRef(null);
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

  if (collapsed) {
    return (
      <button
        data-testid="calendar-expand"
        onClick={onToggleCollapse}
        className="flex items-center gap-1.5 text-xs text-white/50 hover:text-white mb-3 shrink-0"
      >
        <CalendarDays size={13} /> Mostra calendario <ChevronDown size={13} />
      </button>
    );
  }

  return (
    <TooltipProvider delayDuration={150}>
      <div className="card-soft rounded-2xl px-4 py-3 mb-4 shrink-0">
        <div className="flex items-center justify-between mb-2">
          <div className="kicker">calendario</div>
          <button data-testid="calendar-collapse" onClick={onToggleCollapse} className="flex items-center gap-1.5 text-xs text-white/50 hover:text-white">
            Nascondi <ChevronUp size={13} />
          </button>
        </div>
        <div className="flex">
          <div className="flex flex-col shrink-0 pr-2.5 pt-6">
            {IT_DAYS_SHORT.map((d) => (
              <div key={d} className="h-7 flex items-center text-[10px] uppercase tracking-wide" style={{ color: MUTED_TEXT }}>{d}</div>
            ))}
          </div>
          <div ref={scrollRef} onWheel={onWheel} className="flex-1 overflow-x-auto no-scrollbar">
            <div className="flex gap-1">
              {weeks.map((monday, wi) => {
                const isCurrentWeek = isoDate(monday) === isoDate(thisMonday);
                const headerColor = isCurrentWeek ? CURRENT_TEXT : MUTED_TEXT;
                return (
                  <div key={wi} data-current-week={isCurrentWeek ? "true" : undefined} className="flex flex-col items-center shrink-0" style={{ width: 30 }}>
                    <div className="h-6 flex items-center justify-center text-[9px]" style={{ color: headerColor }}>
                      {isoWeekNumber(monday)}
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
                        <div className="h-7 w-full flex flex-col items-center justify-center gap-0.5">
                          <span className="text-[11px]" style={{ color: textColor }}>{day.getDate()}</span>
                          <span className="h-1.5 w-1.5 rounded-full" style={{ background: dotColor || "transparent" }} />
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
    </TooltipProvider>
  );
}
