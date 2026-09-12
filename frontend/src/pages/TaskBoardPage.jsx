import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Calendar, CalendarCheck, Star, Trash2, CircleCheck, Archive, Bell, BellRing, Hourglass, Users, Send } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import TaskCalendar from "@/pages/TaskCalendar";

const COLS = [
  { key: "alta", label: "Alta priorità", tint: "column-tint-high", dot: "bg-[color:var(--high)]", side: "priority-high" },
  { key: "media", label: "Media priorità", tint: "column-tint-med", dot: "bg-[color:var(--med)]", side: "priority-med" },
  { key: "bassa", label: "Bassa priorità", tint: "column-tint-low", dot: "bg-[color:var(--low)]", side: "priority-low" },
];

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

export default function TaskBoardPage() {
  const [tasks, setTasks] = useState([]);
  const [selected, setSelected] = useState(null);
  const [showCompleted, setShowCompleted] = useState(false);
  const [dragOverCol, setDragOverCol] = useState(null);
  const [filters, setFilters] = useState({});
  const [calendarCollapsed, setCalendarCollapsed] = useState(false);
  const [calendarFilter, setCalendarFilter] = useState(null); // { type: "day", date } | { type: "week", start, end }
  const [tagFilters, setTagFilters] = useState([]);

  const load = async () => {
    const r = await api.get("/tasks");
    setTasks(r.data);
  };
  useEffect(() => { load(); }, []);

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

  const toggleFilter = (colKey, kind) => {
    setFilters((f) => {
      const cur = f[colKey] || { fav: false, overdue: false };
      return { ...f, [colKey]: { ...cur, [kind]: !cur[kind] } };
    });
  };

  const grouped = COLS.map((c) => {
    const colTasks = visible.filter((t) => t.priority === c.key);
    const totalCount = colTasks.length;
    const overdueCount = colTasks.filter(isTaskOverdue).length;
    const favCount = colTasks.filter((t) => !!t.favorite).length;
    const f = filters[c.key] || { fav: false, overdue: false };
    let filtered = colTasks;
    if (f.fav && f.overdue) filtered = colTasks.filter((t) => !!t.favorite && isTaskOverdue(t));
    else if (f.fav) filtered = colTasks.filter((t) => !!t.favorite);
    else if (f.overdue) filtered = colTasks.filter(isTaskOverdue);
    if (calendarFilter?.type === "day") filtered = filtered.filter((t) => t.due_date === calendarFilter.date);
    else if (calendarFilter?.type === "week") filtered = filtered.filter((t) => t.due_date && t.due_date >= calendarFilter.start && t.due_date <= calendarFilter.end);
    if (tagFilters.length > 0) filtered = filtered.filter((t) => (t.tags || []).some((tag) => tagFilters.includes(tag)));
    return { ...c, items: sortTasks(filtered), totalCount, overdueCount, favCount, filterState: f };
  });

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

  return (
    <div className="flex flex-col h-[calc(100vh-17rem)]">
      <TaskCalendar
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
          <div className="flex items-center gap-1.5 flex-wrap ml-4">
            {allTags.map((tag) => (
              <button
                key={tag}
                data-testid={`tag-filter-${tag}`}
                onClick={() => setTagFilters((v) => (v.includes(tag) ? v.filter((x) => x !== tag) : [...v, tag]))}
                className={`text-[11px] px-2.5 py-1 rounded-full transition-colors ${tagFilters.includes(tag) ? "bg-[#00B0F0] text-white" : "bg-white/10 text-white/60 hover:text-white/90"}`}
              >
                #{tag}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-2 flex-1 min-h-0">
        {grouped.map((c) => (
          <div
            key={c.key}
            className={`rounded-2xl p-5 ${c.tint} transition-[filter] flex flex-col min-h-0 ${dragOverCol === c.key ? "brightness-125" : ""}`}
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
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${c.dot}`} />
                <div className="kicker">{c.label}</div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  data-testid={`filter-overdue-${c.key}`}
                  onClick={() => toggleFilter(c.key, "overdue")}
                  title="Filtra scaduti"
                  className={`h-7 px-2 rounded-full flex items-center gap-1 text-[11px] font-bold transition-colors ${c.filterState.overdue ? "bg-[#76280E] text-white" : "bg-white/10 text-white/55 hover:bg-white/15"}`}
                >
                  <Hourglass size={12} /> {c.overdueCount}
                </button>
                <button
                  data-testid={`filter-fav-${c.key}`}
                  onClick={() => toggleFilter(c.key, "fav")}
                  title="Filtra preferiti"
                  className={`h-7 px-2 rounded-full flex items-center gap-1 text-[11px] font-bold transition-colors ${c.filterState.fav ? "bg-amber-400 text-white" : "bg-white/10 text-white/55 hover:bg-white/15"}`}
                >
                  <Star size={12} className={c.filterState.fav ? "fill-current" : ""} /> {c.favCount}
                </button>
                <div className="h-7 w-7 rounded-full bg-white/15 flex items-center justify-center text-sm font-bold">{c.totalCount}</div>
              </div>
            </div>
            <div className="mt-5 space-y-3 flex-1 min-h-0 overflow-y-auto pr-1">
              {c.items.length === 0 && <div className="text-center text-white/40 py-16 kicker">vuoto</div>}
              {c.items.map((t) => (
                <TaskCard
                  key={t.id}
                  task={t}
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
        ))}
      </div>

      {selectedTask && (
        <TaskDialog task={selectedTask} onClose={() => setSelected(null)} onUpdated={async () => { await load(); }} />
      )}
    </div>
  );
}

function TaskCard({ task, onClick, onToggleFav, onToggleDone, onToggleCal, onToggleReminder, onDelete }) {
  const stop = (fn) => (e) => { e.stopPropagation(); e.preventDefault(); fn(); };
  const isFav = !!task.favorite;
  const isDone = !!task.completed;
  const isCal = !!task.calendar_synced;
  const isReminder = !!task.reminder_enabled;
  const overdue = isTaskOverdue(task);
  const bg = overdue ? "rgba(118, 40, 14, 0.3)" : "rgba(131, 108, 96, 0.3)";

  return (
    <div
      data-testid={`task-${task.id}`}
      draggable
      onDragStart={(e) => e.dataTransfer.setData("text/plain", task.id)}
      className={`w-full flex items-stretch rounded-2xl overflow-hidden cursor-grab active:cursor-grabbing ${isDone ? "opacity-60" : ""}`}
      style={{ background: bg }}
    >
      <button
        data-testid="task-fav"
        onClick={stop(onToggleFav)}
        className={`shrink-0 w-12 flex items-center justify-center transition-colors ${isFav ? "bg-amber-400" : "bg-white/10 hover:bg-white/15"}`}
        title={isFav ? "Rimuovi dai preferiti" : "Aggiungi ai preferiti"}
      >
        <Star size={18} className={isFav ? "text-white fill-white" : "text-white/50"} />
      </button>

      <button onClick={onClick} className="flex-1 min-w-0 text-left px-4 py-3">
        <div className={`font-semibold text-sm truncate flex items-center gap-1.5 ${isDone ? "line-through" : ""}`}>
          {task.title}
          {task.visibility === "org" && <Users size={11} className="text-white/45 shrink-0" title="Condiviso col team" />}
        </div>
        {task.due_date && (
          <div className="text-[11px] text-white/60 mt-1">{formatDayMonth(task.due_date, task.due_time)}</div>
        )}
      </button>

      <div className="shrink-0 flex items-center gap-1 pr-3">
        <button data-testid="task-reminder" onClick={stop(onToggleReminder)} className={`p-1.5 rounded-full ${isReminder ? "text-purple-300" : "text-white/40 hover:text-white/70"}`} title={isReminder ? "Disattiva promemoria" : "Attiva promemoria"}>
          {isReminder ? <BellRing size={14} /> : <Bell size={14} />}
        </button>
        <button data-testid="task-calendar" onClick={stop(onToggleCal)} className={`p-1.5 rounded-full ${isCal ? "text-[#4E95D9]" : "text-white/40 hover:text-white/70"}`} title={isCal ? "Rimuovi da Calendar" : "Aggiungi a Calendar"}>
          <CalendarCheck size={14} className={isCal ? "fill-current" : ""} />
        </button>
        <button data-testid="task-complete" onClick={stop(onToggleDone)} className={`p-1.5 rounded-full ${isDone ? "text-[#92D050]" : "text-white/40 hover:text-white/70"}`} title={isDone ? "Riapri" : "Segna come fatto"}>
          <CircleCheck size={14} className={isDone ? "fill-current" : ""} />
        </button>
        <button data-testid="task-delete" onClick={stop(onDelete)} className="p-1.5 rounded-full text-white/40 hover:text-red-400" title="Elimina">
          <Trash2 size={14} />
        </button>
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

function TaskDialog({ task, onClose, onUpdated }) {
  const { user } = useAuth();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [thread, setThread] = useState([]);
  const [notes, setNotes] = useState(task.notes || "");
  const [savingNotes, setSavingNotes] = useState(false);
  const [orgMembers, setOrgMembers] = useState([]);

  useEffect(() => {
    if (user?.org_id) {
      api.get("/org").then((r) => setOrgMembers(r.data?.members || [])).catch(() => {});
    }
  }, [user?.org_id]);

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
  const sharedWith = task.visibility === "org" ? "Organizzazione" : "Solo io";

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent
        className="max-w-2xl max-h-[90vh] overflow-y-auto border-0 rounded-2xl bg-gradient-to-r from-[#575155] via-[#6A5D59] to-[#887166]"
        data-testid="task-dialog"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <DialogHeader>
              <DialogTitle className="text-xl font-bold text-white truncate">{task.title}</DialogTitle>
            </DialogHeader>
            {task.due_date && (
              <div className="flex items-center gap-1.5 mt-1.5 text-sm" style={{ color: "#D9D9D9" }}>
                <Calendar size={14} />
                {formatDayMonth(task.due_date, task.due_time)}
              </div>
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0 pt-1">
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
          </div>
        </div>

        {(task.tags || []).length > 0 && (
          <div className="flex flex-wrap gap-2">
            {task.tags.map((t, i) => (
              <span key={i} className="text-xs px-2.5 py-1 rounded-md text-white/90" style={{ background: TAG_BG }}>#{t}</span>
            ))}
          </div>
        )}

        <div className="grid grid-cols-3 gap-4 mt-6">
          <div>
            <div className="text-[11px] uppercase tracking-wide" style={{ color: "#ACA6A3" }}>Data Creazione</div>
            <div className="text-sm text-white mt-1">{formatCreatedAt(task.created_at)}</div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wide" style={{ color: "#ACA6A3" }}>Owner</div>
            <div className="text-sm text-white mt-1">{owner}</div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wide" style={{ color: "#ACA6A3" }}>Shared With</div>
            {user?.org_id ? (
              <button data-testid="toggle-visibility" onClick={toggleVisibility} className="text-sm text-white mt-1 hover:underline">{sharedWith}</button>
            ) : (
              <div className="text-sm text-white mt-1">{sharedWith}</div>
            )}
          </div>
        </div>

        {/* NOTES */}
        <div className="mt-7">
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
      </DialogContent>
    </Dialog>
  );
}
