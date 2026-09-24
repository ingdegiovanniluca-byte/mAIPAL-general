import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Calendar, CalendarCheck, CalendarClock, Star, Trash2, CircleCheck, Archive, Bell, BellRing, Hourglass, Users, Send, StickyNote, Wand2, UserCheck, Share2 } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import TaskCalendar from "@/pages/TaskCalendar";
import { useIsMobile } from "@/hooks/use-is-mobile";

const COLS = [
  { key: "alta", label: "Alta priorità", tint: "column-tint-high", dot: "bg-[color:var(--high)]", side: "priority-high" },
  { key: "media", label: "Media priorità", tint: "column-tint-med", dot: "bg-[color:var(--med)]", side: "priority-med" },
  { key: "bassa", label: "Bassa priorità", tint: "column-tint-low", dot: "bg-[color:var(--low)]", side: "priority-low" },
];

// Mobile shows one chronological list instead of the three priority areas, so each card
// carries its own priority marker - these colors stay readable on the dark glass cards.
const PRIORITY_RANK = { alta: 0, media: 1, bassa: 2 };
const PRIORITY_META = {
  alta: { label: "Alta", color: "#E8663F" },
  media: { label: "Media", color: "#F2B640" },
  bassa: { label: "Bassa", color: "#8FB3C9" },
};

const IT_MONTHS_LONG = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];

const formatDayMonth = (iso, time) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const day = d.getDate();
  const month = IT_MONTHS_LONG[d.getMonth()];
  return time ? `${time}, ${day} ${month}` : `${day} ${month}`;
};

const isTaskOverdue = (t) => {
  const todayStr = new Date().toISOString().slice(0, 10);
  return !!t.due_date && !t.completed && t.due_date < todayStr;
};
// "Non scaduti": la scadenza non è ancora passata, compresi i task senza scadenza - il
// complemento diretto di isTaskOverdue.
const isTaskNotOverdue = (t) => !isTaskOverdue(t);

export default function TaskBoardPage() {
  const { user } = useAuth();
  const isMobile = useIsMobile();
  const [tasks, setTasks] = useState([]);
  const [selected, setSelected] = useState(null);
  const [showCompleted, setShowCompleted] = useState(false);
  const [dragOverCol, setDragOverCol] = useState(null);
  const [filters, setFilters] = useState({});
  const [calendarCollapsed, setCalendarCollapsed] = useState(false);
  const [calendarFilter, setCalendarFilter] = useState(null); // { type: "day", date } | { type: "week", start, end }
  const [tagFilters, setTagFilters] = useState([]);
  const [orgMembers, setOrgMembers] = useState([]);

  const load = async () => {
    const r = await api.get("/tasks");
    setTasks(r.data);
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (user?.org_id) api.get("/org").then((r) => setOrgMembers(r.data?.members || [])).catch(() => {});
    else setOrgMembers([]);
  }, [user?.org_id]);

  const sortTasks = (arr) => [...arr].sort((a, b) => {
    if (showCompleted) {
      const ca = a.completed_at || a.created_at || "";
      const cb = b.completed_at || b.created_at || "";
      return cb.localeCompare(ca);
    }
    const da = a.due_date || "9999-12-31";
    const db_ = b.due_date || "9999-12-31";
    if (da !== db_) return da.localeCompare(db_);
    return (b.created_at || "").localeCompare(a.created_at || "");
  });

  const visible = tasks.filter((t) => showCompleted ? !!t.completed : !t.completed);

  const allTags = Array.from(new Set(tasks.flatMap((t) => t.tags || []))).sort((a, b) => a.localeCompare(b));

  // "scaduti" e "non scaduti" si escludono a vicenda dentro la stessa colonna: attivandone
  // uno si disattiva automaticamente l'altro.
  const toggleFilter = (colKey, kind) => {
    setFilters((f) => {
      const cur = f[colKey] || { fav: false, overdue: false, notOverdue: false };
      const next = { ...cur, [kind]: !cur[kind] };
      if (kind === "overdue" && next.overdue) next.notOverdue = false;
      if (kind === "notOverdue" && next.notOverdue) next.overdue = false;
      return { ...f, [colKey]: next };
    });
  };


  const grouped = COLS.map((c) => {
    const colTasks = visible.filter((t) => t.priority === c.key);
    const f = filters[c.key] || { fav: false, overdue: false, notOverdue: false };
    let filtered = colTasks;
    if (f.overdue) filtered = filtered.filter(isTaskOverdue);
    else if (f.notOverdue) filtered = filtered.filter(isTaskNotOverdue);
    if (f.fav) filtered = filtered.filter((t) => !!t.favorite);
    if (calendarFilter?.type === "day") filtered = filtered.filter((t) => t.due_date === calendarFilter.date);
    else if (calendarFilter?.type === "week") filtered = filtered.filter((t) => t.due_date && t.due_date >= calendarFilter.start && t.due_date <= calendarFilter.end);
    if (tagFilters.length > 0) filtered = filtered.filter((t) => (t.tags || []).some((tag) => tagFilters.includes(tag)));
    return { ...c, items: sortTasks(filtered), filterState: f };
  });

  // ===== Mobile: niente aree di priorità - un'unica lista in ordine cronologico (per data di
  // scadenza, quelli senza data in fondo); a parità di data prima la priorità più alta, poi
  // l'ora. Un solo gruppo di filtri (stato "all") vale per tutta la lista. =====
  const mobileFilterState = filters.all || { fav: false, overdue: false, notOverdue: false };
  const mobileList = (() => {
    let list = visible;
    const f = mobileFilterState;
    if (f.overdue) list = list.filter(isTaskOverdue);
    else if (f.notOverdue) list = list.filter(isTaskNotOverdue);
    if (f.fav) list = list.filter((t) => !!t.favorite);
    if (calendarFilter?.type === "day") list = list.filter((t) => t.due_date === calendarFilter.date);
    else if (calendarFilter?.type === "week") list = list.filter((t) => t.due_date && t.due_date >= calendarFilter.start && t.due_date <= calendarFilter.end);
    return [...list].sort((a, b) => {
      const da = a.due_date || "9999-12-31";
      const db_ = b.due_date || "9999-12-31";
      if (da !== db_) return da.localeCompare(db_);
      const pa = PRIORITY_RANK[a.priority] ?? 3;
      const pb = PRIORITY_RANK[b.priority] ?? 3;
      if (pa !== pb) return pa - pb;
      const ta = a.due_time || "99:99";
      const tb = b.due_time || "99:99";
      if (ta !== tb) return ta.localeCompare(tb);
      return (b.created_at || "").localeCompare(a.created_at || "");
    });
  })();

  const toggleFav = async (id, cur) => {
    setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, favorite: !cur } : t)));
    try { await api.post(`/tasks/${id}/favorite`); }
    catch { toast.error("Errore"); setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, favorite: cur } : t))); }
  };

  const toggleDone = async (id, cur) => {
    setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, completed: !cur } : t)));
    try {
      await api.post(`/tasks/${id}/complete`);
      toast.success(cur ? "Riaperto" : "Task completato ✓");
    } catch { toast.error("Errore"); setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, completed: cur } : t))); }
  };

  const toggleCal = async (id, cur) => {
    setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, calendar_synced: !cur } : t)));
    try {
      await api.patch(`/tasks/${id}`, { calendar_synced: !cur });
      toast.success(cur ? "Rimosso da Calendar" : "Aggiunto a Calendar");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
      setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, calendar_synced: cur } : t)));
    }
  };

  const toggleReminder = async (id, cur) => {
    setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, reminder_enabled: !cur } : t)));
    try {
      await api.patch(`/tasks/${id}`, { reminder_enabled: !cur });
      toast.success(cur ? "Promemoria disattivato" : "Promemoria attivato");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
      setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, reminder_enabled: cur } : t)));
    }
  };

  const del = async (id) => {
    toast("Eliminare questo task?", {
      action: {
        label: "Elimina",
        onClick: async () => {
          const prev = tasks;
          setTasks((ts) => ts.filter((t) => t.id !== id));
          try { await api.delete(`/tasks/${id}`); toast.success("Task eliminato"); }
          catch { toast.error("Errore"); setTasks(prev); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  const changePriority = async (id, newPriority) => {
    const cur = tasks.find((t) => t.id === id);
    if (!cur || cur.priority === newPriority) return;
    const prevPriority = cur.priority;
    setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, priority: newPriority } : t)));
    try { await api.patch(`/tasks/${id}`, { priority: newPriority }); }
    catch {
      toast.error("Errore nello spostamento");
      setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, priority: prevPriority } : t)));
    }
  };

  const activeCount = tasks.filter((t) => !t.completed).length;
  const completedCount = tasks.filter((t) => !!t.completed).length;
  const selectedTask = tasks.find((t) => t.id === selected) || null;

  // Mobile: sotto la striscia dei giorni compare solo il filtro giorno/settimana attivo (un
  // tocco lo toglie). Niente altri controlli sopra i riquadri, come nel riferimento grafico:
  // archiviati e ricerca per hashtag restano sul desktop.
  const mobileBelowStrip = isMobile && calendarFilter ? (
    <button
      data-testid="calendar-filter-pill"
      onClick={() => setCalendarFilter(null)}
      className="mt-4 rounded-full inline-flex items-center gap-1.5 px-3 py-2 text-xs bg-[#00B0F0]/20 text-[#00B0F0]"
    >
      {calendarFilter.type === "day"
        ? formatDayMonth(calendarFilter.date)
        : `${formatDayMonth(calendarFilter.start)} – ${formatDayMonth(calendarFilter.end)}`} ✕
    </button>
  ) : null;

  return (
    <div className="flex flex-col md:h-[calc(100vh-17rem)]">
      <TaskCalendar
        mobileBelowStrip={mobileBelowStrip}
        tasks={tasks}
        collapsed={calendarCollapsed}
        onToggleCollapse={() => setCalendarCollapsed((v) => !v)}
        selectedDate={calendarFilter?.type === "day" ? calendarFilter.date : null}
        onSelectDate={(d) => setCalendarFilter((v) => (v?.type === "day" && v.date === d ? null : { type: "day", date: d }))}
        selectedWeekStart={calendarFilter?.type === "week" ? calendarFilter.start : null}
        onSelectWeek={(mondayIso) => {
          setCalendarFilter((v) => {
            if (v?.type === "week" && v.start === mondayIso) return null;
            const [y, m, d] = mondayIso.split("-").map(Number);
            const end = new Date(y, m - 1, d + 6);
            const endIso = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, "0")}-${String(end.getDate()).padStart(2, "0")}`;
            return { type: "week", start: mondayIso, end: endIso };
          });
        }}
      />
      {/* ===== Desktop (>=768px): barra filtri invariata ===== */}
      {!isMobile && (
        <div className="flex items-center gap-2 mb-2 shrink-0 flex-wrap">
          {calendarFilter && (
            <button
              data-testid="calendar-filter-pill"
              onClick={() => setCalendarFilter(null)}
              className="rounded-full inline-flex items-center gap-1.5 px-3 py-2 text-xs bg-[#00B0F0]/20 text-[#00B0F0]"
            >
              {calendarFilter.type === "day"
                ? formatDayMonth(calendarFilter.date)
                : `${formatDayMonth(calendarFilter.start)} – ${formatDayMonth(calendarFilter.end)}`} ✕
            </button>
          )}
          <button
            data-testid="filter-active"
            onClick={() => setShowCompleted(false)}
            title="Attivi"
            className={`rounded-full inline-flex items-center transition-all duration-200 ${!showCompleted ? "gap-1.5 px-4 py-2 bg-[#CECAD0] text-[#403A3C]" : "gap-1 px-2.5 py-2 bg-white/10 text-white/50 hover:text-white/80"}`}
          >
            {!showCompleted ? (
              <>
                <CircleCheck size={14} />
                <span className="text-xs font-mono-tight uppercase tracking-widest">attivi</span>
                <span className="ml-0.5 text-[10px] font-bold bg-black/10 rounded-full px-1.5 py-0.5">{activeCount}</span>
              </>
            ) : (
              <>
                <span className="w-1.5 h-1.5 rounded-full bg-current" />
                <CircleCheck size={13} />
              </>
            )}
          </button>
          <button
            data-testid="filter-completed"
            onClick={() => setShowCompleted(true)}
            title="Completati"
            className={`rounded-full inline-flex items-center transition-all duration-200 ${showCompleted ? "gap-1.5 px-4 py-2 bg-[#CECAD0] text-[#403A3C]" : "gap-1 px-2.5 py-2 bg-white/10 text-white/50 hover:text-white/80"}`}
          >
            {showCompleted ? (
              <>
                <Archive size={14} />
                <span className="text-xs font-mono-tight uppercase tracking-widest">completati</span>
                <span className="ml-0.5 text-[10px] font-bold bg-black/10 rounded-full px-1.5 py-0.5">{completedCount}</span>
              </>
            ) : (
              <>
                <span className="w-1.5 h-1.5 rounded-full bg-current" />
                <Archive size={13} />
              </>
            )}
          </button>
          {allTags.length > 0 && (
            <div className="flex items-center gap-1.5 flex-nowrap overflow-x-auto no-scrollbar md:flex-wrap md:overflow-visible ml-2 md:ml-4 max-w-full">
              {allTags.map((tag) => (
                <button
                  key={tag}
                  data-testid={`tag-filter-${tag}`}
                  onClick={() => setTagFilters((v) => (v.includes(tag) ? v.filter((x) => x !== tag) : [...v, tag]))}
                  className={`shrink-0 text-[11px] px-2.5 py-1 rounded-full transition-colors ${tagFilters.includes(tag) ? "bg-[#00B0F0] text-white" : "bg-white/10 text-white/60 hover:text-white/90"}`}
                >
                  #{tag}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {isMobile && (
        <div data-testid="mobile-task-list">
          {/* Un solo menu di filtro, all'altezza dove prima c'era "Alta priorità". */}
          <div className="flex items-center justify-between px-1 mb-4">
            <div className="kicker whitespace-nowrap">tutti i task</div>
            <div className="flex items-center gap-1 shrink-0">
              <button
                data-testid="filter-overdue-all"
                onClick={() => toggleFilter("all", "overdue")}
                title="Filtra scaduti"
                aria-pressed={!!mobileFilterState.overdue}
                className={`p-1 transition-colors ${mobileFilterState.overdue ? "text-[#E0703A]" : "text-white/50"}`}
              >
                <Hourglass size={13} strokeWidth={mobileFilterState.overdue ? 2.5 : 2} />
              </button>
              <button
                data-testid="filter-not-overdue-all"
                onClick={() => toggleFilter("all", "notOverdue")}
                title="Filtra non scaduti"
                aria-pressed={!!mobileFilterState.notOverdue}
                className={`p-1 transition-colors ${mobileFilterState.notOverdue ? "text-[#4E95D9]" : "text-white/50"}`}
              >
                <CalendarClock size={13} strokeWidth={mobileFilterState.notOverdue ? 2.5 : 2} />
              </button>
              <button
                data-testid="filter-fav-all"
                onClick={() => toggleFilter("all", "fav")}
                title="Filtra preferiti"
                aria-pressed={!!mobileFilterState.fav}
                className={`p-1 transition-colors ${mobileFilterState.fav ? "text-amber-400" : "text-white/50"}`}
              >
                <Star size={13} className={mobileFilterState.fav ? "fill-current" : ""} />
              </button>
              <div data-testid="count-all" className="liquid-glass-panel h-7 min-w-[1.75rem] px-1 ml-1 rounded-full flex items-center justify-center text-sm font-bold">{mobileList.length}</div>
            </div>
          </div>
          <div className="space-y-3">
            {mobileList.length === 0 && <div className="text-center text-white/40 py-16 kicker">vuoto</div>}
            {mobileList.map((t) => (
              <TaskCard
                key={t.id}
                task={t}
                orgMembers={orgMembers}
                onClick={() => setSelected(t.id)}
                onToggleFav={() => toggleFav(t.id, !!t.favorite)}
                onToggleDone={() => toggleDone(t.id, !!t.completed)}
                onToggleCal={() => toggleCal(t.id, !!t.calendar_synced)}
                onToggleReminder={() => toggleReminder(t.id, !!t.reminder_enabled)}
                onDelete={() => del(t.id)}
              />
            ))}
          </div>
        </div>
      )}

      {!isMobile && (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-6 mt-2 md:flex-1 md:min-h-0">
        {grouped.map((c) => {
          return (
          <div
            key={c.key}
            className={`rounded-2xl p-4 md:p-5 ${c.tint} transition-[filter] flex flex-col min-h-0 ${dragOverCol === c.key ? "brightness-125" : ""}`}
            data-testid={`col-${c.key}`}
            onDragOver={(e) => { e.preventDefault(); setDragOverCol(c.key); }}
            onDragLeave={() => setDragOverCol((v) => (v === c.key ? null : v))}
            onDrop={(e) => {
              e.preventDefault();
              setDragOverCol(null);
              const id = e.dataTransfer.getData("text/plain");
              if (id) changePriority(id, c.key);
            }}
          >
            <div className="flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <span className={`w-2 h-2 rounded-full shrink-0 ${c.dot}`} />
                <div className="kicker whitespace-nowrap">{c.label}</div>
              </div>
              {/* Filtri come sole icone, senza area né numero: lo stato attivo si riconosce dal
                  colore. Il numero a destra conta i task effettivamente mostrati nel riquadro,
                  quindi cambia con filtri, tag, ricerca e giorno/settimana selezionati. */}
              <div className="flex items-center gap-1 md:gap-1.5 shrink-0">
                <button
                  data-testid={`filter-overdue-${c.key}`}
                  onClick={() => toggleFilter(c.key, "overdue")}
                  title="Filtra scaduti"
                  aria-pressed={!!c.filterState.overdue}
                  className={`p-1 transition-colors ${c.filterState.overdue ? "text-[#E0703A]" : "text-white/50 hover:text-white/80"}`}
                >
                  <Hourglass size={13} strokeWidth={c.filterState.overdue ? 2.5 : 2} />
                </button>
                <button
                  data-testid={`filter-not-overdue-${c.key}`}
                  onClick={() => toggleFilter(c.key, "notOverdue")}
                  title="Filtra non scaduti"
                  aria-pressed={!!c.filterState.notOverdue}
                  className={`p-1 transition-colors ${c.filterState.notOverdue ? "text-[#4E95D9]" : "text-white/50 hover:text-white/80"}`}
                >
                  <CalendarClock size={13} strokeWidth={c.filterState.notOverdue ? 2.5 : 2} />
                </button>
                <button
                  data-testid={`filter-fav-${c.key}`}
                  onClick={() => toggleFilter(c.key, "fav")}
                  title="Filtra preferiti"
                  aria-pressed={!!c.filterState.fav}
                  className={`p-1 transition-colors ${c.filterState.fav ? "text-amber-400" : "text-white/50 hover:text-white/80"}`}
                >
                  <Star size={13} className={c.filterState.fav ? "fill-current" : ""} />
                </button>
                {/* liquid-glass-panel invece di liquid-glass-btn: stesso effetto vetro,
                    ma senza l'onda di colore animata (contatore fermo). */}
                <div data-testid={`col-count-${c.key}`} className="liquid-glass-panel h-7 min-w-[1.75rem] px-1 ml-1 rounded-full flex items-center justify-center text-sm font-bold">{c.items.length}</div>
              </div>
            </div>
            <div className="mt-4 md:mt-5 space-y-3 md:flex-1 md:min-h-0 md:overflow-y-auto md:pr-1">
              {c.items.length === 0 && <div className="text-center text-white/40 py-16 kicker">vuoto</div>}
              {c.items.map((t) => (
                <TaskCard
                  key={t.id}
                  task={t}
                  orgMembers={orgMembers}
                  onClick={() => setSelected(t.id)}
                  onToggleFav={() => toggleFav(t.id, !!t.favorite)}
                  onToggleDone={() => toggleDone(t.id, !!t.completed)}
                  onToggleCal={() => toggleCal(t.id, !!t.calendar_synced)}
                  onToggleReminder={() => toggleReminder(t.id, !!t.reminder_enabled)}
                  onDelete={() => del(t.id)}
                />
              ))}
            </div>
          </div>
          );
        })}
      </div>
      )}

      {selectedTask && (
        <TaskDialog task={selectedTask} orgMembers={orgMembers} onClose={() => setSelected(null)} onUpdated={async () => { await load(); }} />
      )}
    </div>
  );
}

function TaskCard({ task, orgMembers, onClick, onToggleFav, onToggleDone, onToggleCal, onToggleReminder, onDelete }) {
  const isMobile = useIsMobile();
  const stop = (fn) => (e) => { e.stopPropagation(); e.preventDefault(); fn(); };
  const isFav = !!task.favorite;
  const isDone = !!task.completed;
  const isCal = !!task.calendar_synced;
  const isReminder = !!task.reminder_enabled;
  const overdue = isTaskOverdue(task);
  // Overdue: dark red. Otherwise desktop uses a light #DADDD6 (30% transparent) card with dark
  // ink, while mobile uses the same glass as the diary's day cards (card-soft) with white ink.
  const glass = !overdue && isMobile;
  const bg = overdue ? "rgba(118, 40, 14, 0.9)" : glass ? undefined : "rgba(218, 221, 214, 0.7)";
  const light = !overdue && !glass;
  const prio = PRIORITY_META[task.priority];
  const ink = light ? "text-[#2B2A2E]" : "text-white";
  const inkMuted = light ? "text-[#2B2A2E]/60" : "text-white/60";
  const iconIdle = light ? "text-[#2B2A2E]/45 hover:text-[#2B2A2E]/80" : "text-white/40 hover:text-white/70";
  const assigneeName = task.assigned_to ? (orgMembers || []).find((m) => m.user_id === task.assigned_to)?.name : null;

  const favBand = (
    <button
      data-testid="task-fav"
      onClick={stop(onToggleFav)}
      className={`shrink-0 w-12 flex items-center justify-center transition-colors ${isFav ? "bg-amber-400" : light ? "bg-black/5 hover:bg-black/10" : "bg-white/10 hover:bg-white/15"}`}
      title={isFav ? "Rimuovi dai preferiti" : "Aggiungi ai preferiti"}
    >
      <Star size={18} className={isFav ? "text-white fill-white" : light ? "text-[#2B2A2E]/40" : "text-white/50"} />
    </button>
  );

  const titleBlock = (
    <button onClick={onClick} className="flex-1 min-w-0 text-left px-4 py-3">
      <div className={`font-semibold text-sm break-words md:truncate flex items-center gap-1.5 ${ink} ${isDone ? "line-through" : ""}`}>
        {task.title}
        {task.visibility === "org" && <Users size={11} className={`${light ? "text-[#2B2A2E]/45" : "text-white/45"} shrink-0`} title="Condiviso col team" />}
        {assigneeName && <UserCheck size={11} className="text-[#4E95D9] shrink-0" title={`Assegnato a ${assigneeName}`} />}
      </div>
      {isMobile ? (
        (prio || task.due_date) && (
          <div className={`text-[11px] ${inkMuted} mt-1 flex items-center gap-1.5`}>
            {prio && <span className="w-2 h-2 rounded-full shrink-0" style={{ background: prio.color }} />}
            {prio && <span>{prio.label}</span>}
            {prio && task.due_date && <span>·</span>}
            {task.due_date && <span>{formatDayMonth(task.due_date, task.due_time)}</span>}
          </div>
        )
      ) : task.due_date && (
        <div className={`text-[11px] ${inkMuted} mt-1`}>{formatDayMonth(task.due_date, task.due_time)}</div>
      )}
      {assigneeName && (
        <div className="text-[11px] text-[#4E95D9]/80 mt-0.5 truncate">→ {assigneeName}</div>
      )}
    </button>
  );

  const actionIcons = (
    <>
      {!!task.notes && (
        <span className={`p-1.5 ${light ? "text-[#2B2A2E]/45" : "text-white/40"}`} title="Questo task ha delle note">
          <StickyNote size={14} />
        </span>
      )}
      <button data-testid="task-reminder" onClick={stop(onToggleReminder)} className={`p-1.5 rounded-full ${isReminder ? (light ? "text-purple-600" : "text-purple-300") : iconIdle}`} title={isReminder ? "Disattiva promemoria" : "Attiva promemoria"}>
        {isReminder ? <BellRing size={14} /> : <Bell size={14} />}
      </button>
      <button data-testid="task-calendar" onClick={stop(onToggleCal)} className={`p-1.5 rounded-full ${isCal ? (light ? "text-[#2F6FB0]" : "text-[#4E95D9]") : iconIdle}`} title={isCal ? "Rimuovi da Calendar" : "Aggiungi a Calendar"}>
        <CalendarCheck size={14} className={isCal ? "fill-current" : ""} />
      </button>
      <button data-testid="task-complete" onClick={stop(onToggleDone)} className={`p-1.5 rounded-full ${isDone ? (light ? "text-[#4E8A22]" : "text-[#92D050]") : iconIdle}`} title={isDone ? "Riapri" : "Segna come fatto"}>
        <CircleCheck size={14} className={isDone ? "fill-current" : ""} />
      </button>
      <button data-testid="task-delete" onClick={stop(onDelete)} className={`p-1.5 rounded-full ${light ? "text-[#2B2A2E]/45 hover:text-red-600" : "text-white/40 hover:text-red-400"}`} title="Elimina">
        <Trash2 size={14} />
      </button>
    </>
  );

  const rootProps = {
    "data-testid": `task-${task.id}`,
    draggable: true,
    onDragStart: (e) => e.dataTransfer.setData("text/plain", task.id),
    style: { background: bg },
  };

  if (isMobile) {
    // Spec v2 §2.6: la fascia della stellina copre tutta l'altezza della scheda (titolo,
    // data E riga delle azioni) - per questo titolo e azioni stanno in una colonna a parte
    // accanto alla fascia, invece di essere tre elementi fratelli in una riga che va a capo
    // (in quel caso la fascia si fermava all'altezza della prima riga). Le icone partono da
    // sinistra: pl-2.5 del contenitore + p-1.5 di ogni pulsante = 16px, lo stesso px-4 del
    // titolo, così il primo glifo è esattamente in linea con l'inizio del testo.
    return (
      <div {...rootProps} className={`w-full flex items-stretch rounded-2xl overflow-hidden cursor-grab active:cursor-grabbing ${glass ? "card-soft" : ""} ${isDone ? "opacity-60" : ""}`}>
        {favBand}
        <div className="flex-1 min-w-0 flex flex-col">
          {titleBlock}
          <div className="flex items-center justify-start gap-1 pl-2.5 pr-3 pb-2 -mt-1">
            {actionIcons}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div {...rootProps} className={`w-full flex items-stretch rounded-2xl overflow-hidden cursor-grab active:cursor-grabbing ${isDone ? "opacity-60" : ""}`}>
      {favBand}
      {titleBlock}
      <div className="shrink-0 flex items-center justify-end gap-1 px-3">
        {actionIcons}
      </div>
    </div>
  );
}

const TAG_BG = "rgba(131, 108, 96, 0.3)";

const formatCreatedAt = (iso) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${d.getDate()} ${IT_MONTHS_LONG[d.getMonth()]}, ${hh}:${mm}`;
};

function TaskDialog({ task, orgMembers, onClose, onUpdated }) {
  const { user } = useAuth();
  const isMobile = useIsMobile();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [thread, setThread] = useState([]);
  const [notes, setNotes] = useState(task.notes || "");
  const [savingNotes, setSavingNotes] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [editingDate, setEditingDate] = useState(false);
  const [dateDraft, setDateDraft] = useState("");
  const [timeDraft, setTimeDraft] = useState("");
  const [savingDate, setSavingDate] = useState(false);

  const openDateEdit = () => {
    setDateDraft(task.due_date || "");
    setTimeDraft(task.due_time || "");
    setEditingDate(true);
  };

  const saveDueDate = async () => {
    setSavingDate(true);
    try {
      await api.patch(`/tasks/${task.id}`, { due_date: dateDraft || null, due_time: timeDraft || null });
      onUpdated();
      toast.success("Data aggiornata");
      setEditingDate(false);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore aggiornamento data"); }
    finally { setSavingDate(false); }
  };

  const send = async () => {
    if (!msg.trim()) return;
    setBusy(true);
    try {
      const r = await api.post(`/tasks/${task.id}/chat`, { message: msg });
      setThread((t) => [...t, { user: msg, agent: r.data.answer }]);
      setMsg("");
      onUpdated();
      toast.success("Task aggiornato");
    } catch (e) { toast.error("Errore aggiornamento"); }
    finally { setBusy(false); }
  };

  const saveNotes = async () => {
    setSavingNotes(true);
    try {
      await api.patch(`/tasks/${task.id}`, { notes });
      onUpdated();
      toast.success("Note salvate");
    } catch (e) { toast.error("Errore salvataggio note"); }
    finally { setSavingNotes(false); }
  };

  const toggleFav = async () => {
    try {
      await api.post(`/tasks/${task.id}/favorite`);
      onUpdated();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const toggleDone = async () => {
    try {
      await api.post(`/tasks/${task.id}/complete`);
      onUpdated();
      toast.success(task.completed ? "Riaperto" : "Task completato ✓");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const toggleCal = async () => {
    try {
      await api.patch(`/tasks/${task.id}`, { calendar_synced: !task.calendar_synced });
      onUpdated();
      toast.success(task.calendar_synced ? "Rimosso da Calendar" : "Aggiunto a Calendar");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const toggleReminder = async () => {
    try {
      await api.patch(`/tasks/${task.id}`, { reminder_enabled: !task.reminder_enabled });
      onUpdated();
      toast.success(task.reminder_enabled ? "Promemoria disattivato" : "Promemoria attivato");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const toggleVisibility = async () => {
    const next = task.visibility === "org" ? "private" : "org";
    try {
      await api.patch(`/tasks/${task.id}`, { visibility: next });
      onUpdated();
      toast.success(next === "org" ? "Condiviso con il team" : "Reso privato");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const assignTo = async (memberId) => {
    setAssigning(true);
    try {
      const r = await api.post(`/tasks/${task.id}/assign`, { assigned_to: memberId || null });
      onUpdated();
      if (memberId) {
        const member = orgMembers.find((m) => m.user_id === memberId);
        toast.success(
          member?.has_telegram
            ? `Assegnato a ${member?.name || "membro"} · notifica inviata su Telegram`
            : `Assegnato a ${member?.name || "membro"}`
        );
      } else {
        toast.success("Assegnazione rimossa");
      }
      return r.data;
    } catch (e) { toast.error(e.response?.data?.detail || "Errore assegnazione"); }
    finally { setAssigning(false); }
  };

  const del = async () => {
    toast("Eliminare questo task?", {
      action: {
        label: "Elimina",
        onClick: async () => {
          await api.delete(`/tasks/${task.id}`);
          onUpdated();
          onClose();
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  const isFav = !!task.favorite;
  const isDone = !!task.completed;
  const isCal = !!task.calendar_synced;
  const isReminder = !!task.reminder_enabled;

  const owner = task.user_id === user?.user_id
    ? (user?.name || "Tu")
    : (orgMembers.find((m) => m.user_id === task.user_id)?.name || "Team");
  const assignee = task.assigned_to ? orgMembers.find((m) => m.user_id === task.assigned_to) : null;
  const sharedWith = assignee
    ? `Assegnato a ${assignee.name}${assignee.user_id === user?.user_id ? " (io)" : ""}`
    : task.visibility === "org" ? "Organizzazione" : "Solo io";

  const dateBlock = editingDate ? (
    <div className="flex items-center gap-1.5 mt-1.5 text-sm flex-wrap" style={{ color: "#D9D9D9" }}>
      <Calendar size={14} />
      <input
        type="date"
        data-testid="task-due-date-input"
        value={dateDraft}
        onChange={(e) => setDateDraft(e.target.value)}
        className="bg-white/10 rounded-lg px-1.5 py-0.5 text-white text-xs border-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/30"
      />
      <input
        type="time"
        data-testid="task-due-time-input"
        value={timeDraft}
        onChange={(e) => setTimeDraft(e.target.value)}
        disabled={!dateDraft}
        className="bg-white/10 rounded-lg px-1.5 py-0.5 text-white text-xs border-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/30 disabled:opacity-40"
      />
      <button data-testid="task-due-date-save" onClick={saveDueDate} disabled={savingDate} className="text-xs px-2 py-0.5 rounded-full bg-white/15 hover:bg-white/25 text-white disabled:opacity-50">
        {savingDate ? "…" : "Salva"}
      </button>
      <button onClick={() => setEditingDate(false)} className="text-xs px-1.5 py-0.5 rounded-full text-white/50 hover:text-white/80">
        Annulla
      </button>
    </div>
  ) : (
    <button
      onClick={openDateEdit}
      data-testid="task-due-date-display"
      className="flex items-center gap-1.5 mt-1.5 text-sm hover:underline decoration-dotted underline-offset-2"
      style={{ color: "#D9D9D9" }}
      title="Modifica la data"
    >
      <Calendar size={14} />
      {task.due_date ? formatDayMonth(task.due_date, task.due_time) : "Aggiungi data"}
    </button>
  );

  const actionButtons = (
    <>
      <button data-testid="task-fav" onClick={toggleFav} className={`p-1.5 rounded-full ${isFav ? "text-amber-400" : "text-white/40 hover:text-white/70"}`} title={isFav ? "Rimuovi dai preferiti" : "Aggiungi ai preferiti"}>
        <Star size={16} className={isFav ? "fill-current" : ""} />
      </button>
      <button data-testid="task-reminder" onClick={toggleReminder} className={`p-1.5 rounded-full ${isReminder ? "text-purple-300" : "text-white/40 hover:text-white/70"}`} title={isReminder ? "Disattiva promemoria" : "Attiva promemoria"}>
        {isReminder ? <BellRing size={16} /> : <Bell size={16} />}
      </button>
      <button data-testid="toggle-calendar" onClick={toggleCal} className={`p-1.5 rounded-full ${isCal ? "text-[#4E95D9]" : "text-white/40 hover:text-white/70"}`} title={isCal ? "Rimuovi da Calendar" : "Aggiungi a Calendar"}>
        <CalendarCheck size={16} className={isCal ? "fill-current" : ""} />
      </button>
      <button data-testid="task-complete" onClick={toggleDone} className={`p-1.5 rounded-full ${isDone ? "text-[#92D050]" : "text-white/40 hover:text-white/70"}`} title={isDone ? "Riapri" : "Segna come fatto"}>
        <CircleCheck size={16} className={isDone ? "fill-current" : ""} />
      </button>
      <button data-testid="delete-task" onClick={del} className="p-1.5 rounded-full text-white/40 hover:text-red-400" title="Elimina">
        <Trash2 size={16} />
      </button>
    </>
  );

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent
        className="max-w-2xl max-h-[90vh] overflow-hidden border-0 rounded-2xl liquid-glass-panel wobble-glass text-white"
        data-testid="task-dialog"
      >
        <div className="max-h-full overflow-y-auto pr-1">
        {isMobile ? (
          // Spec v2 §2.7: su smartphone le icone stanno nella prima riga in alto, allineate
          // a sinistra (-ml-1.5 compensa il p-1.5 del primo pulsante, così il glifo parte
          // esattamente dal bordo del testo sotto), e il titolo va a capo invece di essere
          // troncato. La "x" di chiusura resta quella del Dialog, in alto a destra.
          <div>
            <div className="flex items-center gap-1 -ml-1.5 pr-8" data-testid="task-dialog-actions">
              {actionButtons}
            </div>
            <div className="mt-2 min-w-0">
              <DialogHeader>
                <DialogTitle className="text-xl font-bold text-white break-words text-left leading-snug">{task.title}</DialogTitle>
              </DialogHeader>
              {dateBlock}
            </div>
          </div>
        ) : (
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <DialogHeader>
                <DialogTitle className="text-xl font-bold text-white truncate">{task.title}</DialogTitle>
              </DialogHeader>
              {dateBlock}
            </div>
            <div className="flex items-center gap-1 shrink-0 pt-1">
              {actionButtons}
            </div>
          </div>
        )}

        {(task.tags || []).length > 0 && (
          <div className="flex flex-wrap gap-2 mt-4">
            {task.tags.map((t, i) => (
              <span key={i} className="text-xs px-2.5 py-1 rounded-md text-white/90" style={{ background: TAG_BG }}>#{t}</span>
            ))}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-6">
          <div>
            <div className="text-[11px] uppercase tracking-wide" style={{ color: "#ACA6A3" }}>Data Creazione</div>
            <div className="text-sm text-white mt-1">{formatCreatedAt(task.created_at)}</div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wide" style={{ color: "#ACA6A3" }}>Owner</div>
            <div className="text-sm text-white mt-1">{owner}</div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wide flex items-center gap-1" style={{ color: "#ACA6A3" }}>
              Shared With
              <Popover>
                <PopoverTrigger asChild>
                  <button
                    data-testid="share-assign-btn"
                    className="p-0.5 rounded-full text-white/50 hover:text-white hover:bg-white/10 transition-colors"
                    title="Condividi o assegna questo task"
                  >
                    <Share2 size={12} />
                  </button>
                </PopoverTrigger>
                <PopoverContent align="start" className="w-72 bg-[#2A2429] border-white/10 text-white rounded-2xl shadow-xl">
                  {user?.org_id ? (
                    <div className="space-y-4">
                      <div>
                        <div className="text-[11px] uppercase tracking-widest text-white/50 mb-2">Condividi</div>
                        <button
                          data-testid="toggle-visibility"
                          onClick={toggleVisibility}
                          className={`w-full text-left text-sm px-3 py-2 rounded-xl transition-colors ${task.visibility === "org" ? "bg-[#00B0F0]/20 text-[#00B0F0]" : "bg-white/10 text-white hover:bg-white/15"}`}
                        >
                          {task.visibility === "org" ? "✓ Condiviso con il team" : "Condividi con il team"}
                        </button>
                      </div>
                      <div>
                        <div className="text-[11px] uppercase tracking-widest text-white/50 mb-2">Assegna a</div>
                        <select
                          data-testid="task-assign-select"
                          value={task.assigned_to || ""}
                          disabled={assigning}
                          onChange={(e) => assignTo(e.target.value)}
                          className="w-full text-sm text-white bg-white/10 rounded-xl px-3 py-2 outline-none disabled:opacity-50 cursor-pointer"
                          style={{ colorScheme: "dark" }}
                        >
                          <option value="" className="text-black">Nessuno</option>
                          {orgMembers.map((m) => (
                            <option key={m.user_id} value={m.user_id} className="text-black">
                              {m.name}{m.user_id === user?.user_id ? " (io)" : ""}{m.has_telegram ? "" : " · no Telegram"}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  ) : (
                    <div className="text-sm text-white/60">
                      Non fai ancora parte di un team: vai in <span className="text-white font-medium">Impostazioni → Team</span> per unirti, poi qui potrai condividere o assegnare questo task.
                    </div>
                  )}
                </PopoverContent>
              </Popover>
            </div>
            <div className="text-sm text-white mt-1">{sharedWith}</div>
          </div>
        </div>

        {/* NOTES */}
        <div className="mt-7">
          <div
            className="flex items-center gap-1.5 mb-1.5 text-[11px] uppercase tracking-widest text-white/50"
            title="Appunti liberi su questo task: non vengono interpretati da mAIPAL, restano solo un promemoria per te"
          >
            <StickyNote size={13} /> Note
          </div>
          <div className="relative">
            <Textarea
              data-testid="task-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Note"
              className="border-0 rounded-2xl min-h-[80px] pr-12 text-white placeholder:text-white/50"
              style={{ background: TAG_BG }}
            />
            <button
              data-testid="task-notes-save"
              onClick={saveNotes}
              disabled={savingNotes || notes === (task.notes || "")}
              className="absolute bottom-2.5 right-2.5 p-2 rounded-full bg-white/15 text-white hover:bg-white/25 disabled:opacity-30"
              title="Salva note"
            >
              <Send size={14} />
            </button>
          </div>
        </div>

        <div className="mt-2 space-y-3 max-h-60 overflow-y-auto">
          {thread.map((t, i) => (
            <div key={i} className="space-y-2">
              <div className="rounded-xl p-3 text-sm text-white" style={{ background: TAG_BG }}>{t.user}</div>
              <div className="prose-answer text-sm whitespace-pre-wrap">{t.agent}</div>
            </div>
          ))}
        </div>

        <div className="mt-3">
          <div
            className="flex items-center gap-1.5 mb-1.5 text-[11px] uppercase tracking-widest text-white/50"
            title="Scrivi in linguaggio naturale per far modificare il task a mAIPAL: data, priorità, titolo e altro"
          >
            <Wand2 size={13} /> Modifica con mAIPAL
          </div>
          <div className="relative">
            <Textarea
              data-testid="task-chat-input"
              value={msg}
              onChange={(e) => setMsg(e.target.value)}
              placeholder="Modifica il task scrivendo in linguaggio naturale"
              className="border-0 rounded-2xl min-h-[80px] pr-12 text-white placeholder:text-white/50"
              style={{ background: TAG_BG }}
            />
            <button
              data-testid="task-chat-send"
              onClick={send}
              disabled={busy}
              className="absolute bottom-2.5 right-2.5 p-2 rounded-full bg-white/15 text-white hover:bg-white/25 disabled:opacity-30"
              title="Invia a mAIPAL"
            >
              <Send size={14} />
            </button>
          </div>
        </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
