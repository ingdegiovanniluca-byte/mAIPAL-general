import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { CalendarCheck, Star, Trash2, CircleCheck, Archive, Bell, BellRing, Hourglass, Users, Lock } from "lucide-react";
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

  const load = async () => {
    const r = await api.get("/tasks");
    setTasks(r.data);
  };
  useEffect(() => { load(); }, []);

  const sortTasks = (arr) => [...arr].sort((a, b) => {
    const da = a.due_date || "9999-12-31";
    const db_ = b.due_date || "9999-12-31";
    if (da !== db_) return da.localeCompare(db_);
    return (b.created_at || "").localeCompare(a.created_at || "");
  });

  const visible = tasks.filter((t) => showCompleted ? !!t.completed : !t.completed);

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
            const end = new Date(mondayIso);
            end.setDate(end.getDate() + 6);
            return { type: "week", start: mondayIso, end: end.toISOString().slice(0, 10) };
          });
        }}
      />
      <div className="flex items-center gap-2 mb-4 shrink-0 flex-wrap">
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
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-4 flex-1 min-h-0">
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
                  onClick={() => setSelected(t)}
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

      {selected && (
        <TaskDialog task={selected} onClose={() => setSelected(null)} onUpdated={async () => { await load(); }} />
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
        <button data-testid="task-calendar" onClick={stop(onToggleCal)} className={`p-1.5 rounded-full ${isCal ? "text-blue-300" : "text-white/40 hover:text-white/70"}`} title={isCal ? "Rimuovi da Calendar" : "Aggiungi a Calendar"}>
          <CalendarCheck size={14} className={isCal ? "fill-current" : ""} />
        </button>
        <button data-testid="task-complete" onClick={stop(onToggleDone)} className={`p-1.5 rounded-full ${isDone ? "text-green-300" : "text-white/40 hover:text-white/70"}`} title={isDone ? "Riapri" : "Segna come fatto"}>
          <CircleCheck size={14} className={isDone ? "fill-current" : ""} />
        </button>
        <button data-testid="task-delete" onClick={stop(onDelete)} className="p-1.5 rounded-full text-white/40 hover:text-red-400" title="Elimina">
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  );
}

function TaskDialog({ task, onClose, onUpdated }) {
  const { user } = useAuth();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [thread, setThread] = useState([]);
  const [notes, setNotes] = useState(task.notes || "");
  const [savingNotes, setSavingNotes] = useState(false);

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

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="task-dialog">
        <DialogHeader>
          <DialogTitle className="text-2xl font-bold">{task.title}</DialogTitle>
        </DialogHeader>
        <div className="text-white/70 text-sm">{task.description}</div>
        <div className="flex flex-wrap gap-2">
          {task.due_date && <span className="text-xs px-2 py-1 rounded-md bg-white/10">📅 {task.due_date}{task.due_time ? ` · ${task.due_time}` : ""}</span>}
          <span className={`text-xs px-2 py-1 rounded-md ${task.priority === "alta" ? "bg-red-50 text-red-700" : task.priority === "media" ? "bg-orange-50 text-orange-700" : "bg-white/10"}`}>priorità {task.priority}</span>
          {(task.tags || []).map((t, i) => <span key={i} className="text-xs px-2 py-1 rounded-md bg-white/10">#{t}</span>)}
          {task.calendar_synced && <span className="text-xs px-2 py-1 rounded-md bg-blue-50 text-blue-700">✓ Calendar</span>}
          {task.reminder_enabled && <span className="text-xs px-2 py-1 rounded-md bg-purple-50 text-purple-700">🔔 promemoria attivo</span>}
        </div>

        <div className="flex gap-2 flex-wrap">
          <button data-testid="toggle-calendar" onClick={toggleCal} className="px-3 py-1.5 rounded-full text-xs bg-white/10">
            {task.calendar_synced ? "✓ In Calendar" : "+ Aggiungi a Calendar"}
          </button>
          <button data-testid="toggle-reminder" onClick={toggleReminder} className="px-3 py-1.5 rounded-full text-xs bg-white/10">
            {task.reminder_enabled ? "🔔 Promemoria attivo" : "+ Attiva promemoria"}
          </button>
          {user?.org_id && (
            <button data-testid="toggle-visibility" onClick={toggleVisibility} className="px-3 py-1.5 rounded-full text-xs bg-white/10 flex items-center gap-1.5">
              {task.visibility === "org" ? <><Users size={12} /> Condiviso col team</> : <><Lock size={12} /> Privato</>}
            </button>
          )}
          <button data-testid="delete-task" onClick={del} className="px-3 py-1.5 rounded-full text-xs bg-white/10 text-red-400">Elimina</button>
        </div>

        {/* NOTES */}
        <div className="pt-2">
          <div className="kicker mb-2">· note</div>
          <Textarea
            data-testid="task-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Aggiungi note libere sul task…"
            className="bg-white/10 rounded-2xl min-h-[80px]"
          />
          <div className="flex justify-end mt-2">
            <button data-testid="task-notes-save" onClick={saveNotes} disabled={savingNotes || notes === (task.notes || "")} className="px-4 py-1.5 rounded-full text-xs bg-black text-white disabled:opacity-40">
              {savingNotes ? "…" : "Salva note"}
            </button>
          </div>
        </div>

        <div className="mt-3 space-y-3 max-h-60 overflow-y-auto">
          {thread.map((t, i) => (
            <div key={i} className="space-y-2">
              <div className="bg-white/10 rounded-xl p-3 text-sm">{t.user}</div>
              <div className="prose-answer text-sm whitespace-pre-wrap">{t.agent}</div>
            </div>
          ))}
        </div>

        <div className="mt-3">
          <Textarea data-testid="task-chat-input" value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Modifica titolo, scadenza, priorità, tag… (parla in linguaggio naturale)" className="bg-white/10 rounded-2xl min-h-[80px]" />
          <div className="flex justify-end mt-2">
            <button data-testid="task-chat-send" onClick={send} disabled={busy} className="pill-btn">{busy ? "…" : "Invia a mAIPAL"}</button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
